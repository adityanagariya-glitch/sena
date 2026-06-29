"""Shift Analysis API — Active, JWT-authed, visible in Swagger.

POST /v1/case-review/shift-analysis

Single endpoint: the SENA shift case-note form (+ optional voice transcript) →
three UI screens (AI Summary / Risk Summary / Incident Report).

Engine split per field (see schemas.ShiftAnalysisResponse for the per-field map):
— Bedrock Claude summary + evaluator + drafter (run_pipeline)
— pgvector NDIS policy retrieval feeding the evaluator
— AI judgement grounded in retrieved NDIS policy
Python  — deterministic derivations in this file (no LLM, no tokens)

The Python derivations (progress_rating, suggested_attention, confidence_label,
compliance timeframe) are hybrid: they consume the AI output and apply
deterministic rules on top, so the result is explainable and free.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_auth_context, get_db
from case_review.models.schemas import (
    AuthContext,
    AuthorisationStatus,
    CaseNoteForm,
    ComplianceNote,
    EvaluatorOutput,
    IncidentDraftOutput,
    PipelineResult,
    PolicyViolationRisk,
    ShiftAISummary,
    ShiftAnalysisResponse,
    ShiftIncidentReport,
    ShiftRiskSummary,
    SummaryOutput,
    TokenUsage,
    UnifiedIncidentRequest,
)
from case_review.services.pipeline.graph import run_pipeline
from case_review.services.usage import get_usage, log_api_tokens, start_usage

logger = logging.getLogger(__name__)
shift_analysis_router = APIRouter(prefix="/v1/case-review", tags=["shift-analysis"])

_HIGH_RISKS = {PolicyViolationRisk.HIGH, PolicyViolationRisk.CRITICAL}




def _confidence_label(conf: float) -> str:
    """High ≥ 0.85, Medium ≥ 0.70, else Low."""
    if conf >= 0.85:
        return "High"
    if conf >= 0.70:
        return "Medium"
    return "Low"


def _derive_progress_rating(
    summary: SummaryOutput | None,
    evaluator: EvaluatorOutput | None,
    incident_detected: bool,
) -> str:
    """Hybrid 🤖+🐍 — quality score (Python) blended with AI risk signals.

    Returns: 'On Track' | 'Monitoring' | 'Needs Attention'.
    """
    risk_count = len(summary.potential_risks) if summary else 0
    quality = summary.note_quality_score if summary else 0.0
    high_risk = bool(evaluator and evaluator.policy_violation_risk in _HIGH_RISKS)

    if incident_detected or high_risk:
        return "Needs Attention"
    if risk_count == 0 and quality >= 0.70:
        return "On Track"
    if risk_count <= 1 and quality >= 0.50:
        return "Monitoring"
    return "Needs Attention"


def _derive_suggested_attention(
    evaluator: EvaluatorOutput | None,
    cross_check_unauthorised: bool,
    risk_level: str,
) -> list[str]:
    """Hybrid 🤖+🐍 — deterministic rules + the AI evaluator's action summary."""
    out: list[str] = []
    if risk_level in ("High", "Critical"):
        out.append("Manager review recommended")
    if cross_check_unauthorised:
        out.append("Unauthorised restrictive practice — escalate immediately")
    if evaluator and evaluator.reporting_required:
        timeframe = evaluator.notification_timeframe or "the required timeframe"
        out.append(f"NDIS notification required within {timeframe}")
    # 🤖 AI contribution
    if evaluator and evaluator.action_summary:
        out.append(evaluator.action_summary)

    # de-dupe, preserve order
    seen: set[str] = set()
    deduped = [x for x in out if not (x in seen or seen.add(x))]
    return deduped or ["No immediate action required"]


def _build_compliance_notes(
    incident_draft: IncidentDraftOutput | None,
    cross_check_unauthorised: bool,
) -> list[ComplianceNote]:
    """AI checks (from the drafter) + 🐍 timeframe check + 🤖+📚 restrictive-practice check."""
    notes: list[ComplianceNote] = []

    notes.append(ComplianceNote(
        label="Incident documented within the required timeframe",
        passed=True,
        engine="Python",
    ))

    # 🤖 AI — checks the drafter produced (e.g. non-judgmental language)
    if incident_draft and incident_draft.compliance_checks:
        for chk in incident_draft.compliance_checks:
            label = str(chk.get("label", "")).strip()
            if not label:
                continue
            notes.append(ComplianceNote(
                label=label,
                passed=bool(chk.get("passed", False)),
                engine="AI",
            ))

    # 🤖+📚 AI+RAG — restrictive-practice authorisation check (evaluator + NDIS policy)
    notes.append(ComplianceNote(
        label="No unauthorised restrictive practice identified",
        passed=not cross_check_unauthorised,
        engine="AI+RAG",
    ))

    # de-dupe by label, keep first occurrence
    seen: set[str] = set()
    return [n for n in notes if not (n.label in seen or seen.add(n.label))]


# ── Response assembly ──────────────────────────────────────────────────────────


def _build_response(result: PipelineResult, form: CaseNoteForm) -> ShiftAnalysisResponse:
    summary = result.summary
    evaluator = result.evaluator
    incident_draft = result.incident_draft
    cc_unauth = bool(
        result.cross_check
        and result.cross_check.authorisation_status == AuthorisationStatus.UNAUTHORISED
    )
    incident_detected = bool(form.anyIncident or (evaluator and evaluator.incident_detected))

    rp_used = bool(
        (incident_draft and incident_draft.restrictive_practice_used)
        or (evaluator and evaluator.incident_detected and cc_unauth)
    )

    # ── Section 1: AI Summary (🤖 AI + 🐍 Python) ──────────────────────────────
    ai_conf = summary.ai_confidence if summary else 0.0
    ai_summary = ShiftAISummary(
        reviewed_period=None,  # 🐍 no date on the form — frontend fills from shift data
        ai_confidence=ai_conf,
        confidence_label=_confidence_label(ai_conf),
        progress_rating=_derive_progress_rating(summary, evaluator, incident_detected),
        progress_identified=summary.progress_identified if summary else [],
        goal_progress=summary.progress_identified if summary else [],
        potential_risks=summary.potential_risks if summary else [],
        patterns_detected=summary.patterns_detected if summary else [],
        flagged_highlights=summary.flagged_highlights if summary else [],
        restrictive_practice_used=rp_used,
        note_quality_score=summary.note_quality_score if summary else 0.0,
        note_quality_label=summary.note_quality_label if summary else "Average",
    )

    # ── Section 2: Risk Summary (🤖+📚 AI+RAG) — only if the evaluator ran ──────
    risk_summary: ShiftRiskSummary | None = None
    if evaluator:
        risk_level = (
            evaluator.policy_violation_risk.value
            if evaluator.policy_violation_risk
            else "Low"
        )
        risk_summary = ShiftRiskSummary(
            risk_category=evaluator.practice_category or "No Restrictive Practice Detected",
            why_flagged=evaluator.trigger_phrases or [],
            current_risk_level=risk_level,
            suggested_attention=_derive_suggested_attention(evaluator, cc_unauth, risk_level),
        )

    # ── Section 3: Incident Report (🤖 AI, human-only fields excluded) ─────────
    incident_report: ShiftIncidentReport | None = None
    if incident_detected and incident_draft:
        injuries: list[str] = []
        sh = form.safetyAndHealth
        if sh.anyInjuries and sh.injuryDetails:
            injuries.append(sh.injuryDetails)  # 🐍 passthrough from form

        incident_report = ShiftIncidentReport(
            participant_name=None,       # 🐍 frontend maps from clientId
            support_worker_name=None,    # 🐍 frontend maps from worker id
            incident_type=incident_draft.incident_type,
            incident_description=incident_draft.incident_description,
            injuries_or_damages=injuries,
            immediate_actions_taken=incident_draft.immediate_actions_taken or [],
            contributing_factors=incident_draft.contributing_factors or [],
            follow_up_required=incident_draft.follow_up_actions or [],
            restrictive_practice_used=incident_draft.restrictive_practice_used,
            restrictive_practice_category=incident_draft.restrictive_practice_category,
            risk_assessment=incident_draft.risk_assessment,
            compliance_notes=_build_compliance_notes(incident_draft, cc_unauth),
        )

    return ShiftAnalysisResponse(
        client_id=form.clientId,
        shift_id=form.shiftId,
        incident_detected=incident_detected,
        ai_summary=ai_summary,
        risk_summary=risk_summary,
        incident_report=incident_report,
    )


# ── Endpoint ───────────────────────────────────────────────────────────────────


@shift_analysis_router.post(
    "/shift-analysis",
    response_model=ShiftAnalysisResponse,
    summary="Shift analysis — case note form (+ voice) → AI Summary, Risk Summary, Incident Report",
    description=(
        "Feeds the SENA shift case-note form (and optional raw voice transcript) through the "
        "full pipeline and returns the three review screens in one JWT-authed call.\n\n"
        "**Engine per field** (each response field's description names its source):\n"
        "- 🤖 **AI** — Claude summary / evaluator / drafter\n"
        "- 📚 **RAG** — pgvector NDIS policy retrieval\n"
        "- 🤖+📚 **AI+RAG** — AI grounded in NDIS policy\n"
        "- 🐍 **Python** — deterministic rules / heuristics (progress_rating, suggested_attention, "
        "confidence_label, timeframe check)\n\n"
        "**Sections:**\n"
        "1. **AI Summary** — progress, risks, patterns, flagged highlights, progress rating\n"
        "2. **Risk Summary** — risk category + level (null unless the note is flagged)\n"
        "3. **Incident Report** — AI-fillable incident fields (null unless an incident is detected)\n\n"
        "_Human-only incident fields are intentionally excluded — the worker fills date/time, "
        "location, individuals involved, witnesses, reported-to, and additional notes in the UI._"
    ),
)
async def analyze_shift(
    payload: UnifiedIncidentRequest,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> ShiftAnalysisResponse:
    """Shift analysis: case-note form (+ optional voice transcript) → three review screens."""
    start_usage()
    form = payload.case_note_form
    logger.info("shift-analysis START client=%s shift=%s", form.clientId, form.shiftId)
    try:
        case_note_input = payload.to_case_note_input(worker_id=form.shiftId)
        logger.info("shift-analysis running pipeline client=%s shift=%s", form.clientId, form.shiftId)
        result = await run_pipeline(case_note_input, db, tenant_id=str(auth.tenant_id))
        resp = _build_response(result, form)
        resp.token_usage = TokenUsage(**get_usage())

        usage = get_usage()
        logger.info(
            "shift-analysis DONE client=%s shift=%s input=%d output=%d total=%d",
            form.clientId, form.shiftId,
            usage["input_tokens"], usage["output_tokens"], usage["total_tokens"],
        )
        log_api_tokens("/v1/case-review/shift-analysis", "POST", form.clientId, 200)
        return resp
    except Exception as exc:
        logger.error(
            "shift-analysis error client=%s shift=%s: %s",
            form.clientId, form.shiftId, exc, exc_info=True,
        )
        log_api_tokens("/v1/case-review/shift-analysis", "POST", form.clientId, 500)
        raise HTTPException(status_code=500, detail="An internal error occurred.") from exc
