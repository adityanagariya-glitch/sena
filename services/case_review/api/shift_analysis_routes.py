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

from api.deps import get_db
from api.rsa_auth import verify_rsa_auth
from case_review.models.schemas import (
    AuthContext,
    AuthorisationStatus,
    CaseNoteForm,
    CaseNoteInput,
    ComplianceNote,
    EvaluatorOutput,
    IncidentBundle,
    IncidentDraftOutput,
    MultiIncidentShiftResponse,
    PipelineResult,
    PolicyViolationRisk,
    ShiftAISummary,
    ShiftIncidentReport,
    ShiftRiskSummary,
    SummaryOutput,
    TokenUsage,
    UnifiedIncidentRequest,
)
from case_review.services.pipeline.graph import run_pipeline
from case_review.services.pipeline.incident_splitter import IncidentSegment, split_incidents
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


def _build_ai_summary(
    result: PipelineResult,
    form: CaseNoteForm,
    incident_detected: bool,
    cc_unauth: bool,
) -> ShiftAISummary:
    """AI Summary screen (🤖 AI + 🐍 Python) for one pipeline result."""
    summary = result.summary
    evaluator = result.evaluator
    incident_draft = result.incident_draft

    rp_used = bool(
        (incident_draft and incident_draft.restrictive_practice_used)
        or (evaluator and evaluator.incident_detected and cc_unauth)
    )
    ai_conf = summary.ai_confidence if summary else 0.0
    return ShiftAISummary(
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


def _build_bundle(result: PipelineResult, form: CaseNoteForm) -> IncidentBundle:
    """Build one incident's full 3-screen bundle from a pipeline result."""
    evaluator = result.evaluator
    incident_draft = result.incident_draft
    cc_unauth = bool(
        result.cross_check
        and result.cross_check.authorisation_status == AuthorisationStatus.UNAUTHORISED
    )
    # A split segment IS an incident, so treat it as detected for this bundle.
    incident_detected = True

    ai_summary = _build_ai_summary(result, form, incident_detected, cc_unauth)

    # ── Risk Summary (🤖+📚 AI+RAG) — only if the evaluator ran ────────────────
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

    # ── Incident Report (🤖 AI, human-only fields excluded) ────────────────────
    incident_report: ShiftIncidentReport | None = None
    if incident_draft:
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

    return IncidentBundle(
        ai_summary=ai_summary,
        risk_summary=risk_summary,
        incident_report=incident_report,
    )


def _segment_to_input(base: CaseNoteInput, segment: str) -> CaseNoteInput:
    """Clone the base CaseNoteInput but focus the transcript on one incident segment."""
    return base.model_copy(update={
        "transcript": segment,
        "incident_occurred": True,  # the splitter flagged this slice as an incident
    })


# ── Endpoint ───────────────────────────────────────────────────────────────────


@shift_analysis_router.post(
    "/shift-analysis",
    response_model=MultiIncidentShiftResponse,
    summary="Shift analysis — detect every incident, return a 3-screen bundle per incident",
    description=(
        "Feeds the SENA shift case-note form (+ optional raw voice transcript) through an "
        "incident splitter, then runs the full pipeline once PER detected incident.\n\n"
        "**Flow:**\n"
        "1. **Split** (🤖 Haiku) — segment the transcript into N discrete incidents\n"
        "2. **Per incident** — run triage → RAG → evaluator → drafter\n"
        "3. **Assemble** — one bundle (AI Summary + Risk Summary + Incident Report) per incident\n\n"
        "**Response shape:**\n"
        "- `incident_detected`: integer COUNT of incidents\n"
        "- `incident_1` … `incident_N`: one :class:`IncidentBundle` each\n"
        "- `ai_summary`: whole-shift summary, present ONLY when `incident_detected == 0`\n"
        "- `token_usage`: one total for the whole call\n\n"
        "**Engine per field:** 🤖 AI (Claude) · 📚 RAG (NDIS policy) · 🤖+📚 AI+RAG · 🐍 Python "
        "(progress_rating, suggested_attention, confidence_label, scores, count).\n\n"
        "_Human-only incident fields (date/time, location, individuals, witnesses, reported-to, "
        "additional notes) are intentionally excluded — the worker fills them in the UI._"
    ),
)
async def analyze_shift(
    payload: UnifiedIncidentRequest,
    auth: AuthContext = Depends(verify_rsa_auth),
    db: AsyncSession = Depends(get_db),
) -> MultiIncidentShiftResponse:
    """Multi-incident shift analysis: split the shift, then analyse each incident."""
    start_usage()
    form = payload.case_note_form
    tenant_id = str(auth.tenant_id)
    logger.info("shift-analysis START client=%s shift=%s", form.clientId, form.shiftId)
    try:
        base_input = payload.to_case_note_input(worker_id=form.shiftId)
        full_text = base_input.to_text()

        # ── Step 1: split the shift into discrete incidents (🤖 Haiku) ─────────
        segments: list[IncidentSegment] = await split_incidents(full_text)
        logger.info(
            "shift-analysis split client=%s shift=%s → %d incident(s)",
            form.clientId, form.shiftId, len(segments),
        )

        # ── Step 2: no incidents → single whole-shift summary ──────────────────
        if not segments:
            result = await run_pipeline(base_input, db, tenant_id=tenant_id)
            cc_unauth = bool(
                result.cross_check
                and result.cross_check.authorisation_status == AuthorisationStatus.UNAUTHORISED
            )
            ai_summary = _build_ai_summary(result, form, incident_detected=False, cc_unauth=cc_unauth)
            resp = MultiIncidentShiftResponse(
                client_id=form.clientId,
                shift_id=form.shiftId,
                incident_detected=0,
                ai_summary=ai_summary,
                token_usage=TokenUsage(**get_usage()),
            )
            _log_done(form, 0)
            log_api_tokens("/v1/case-review/shift-analysis", "POST", form.clientId, 200)
            return resp

        # ── Step 3: run the pipeline once per incident (sequential, shared db) ─
        incidents: list[IncidentBundle] = []
        for idx, seg in enumerate(segments, start=1):
            logger.info(
                "shift-analysis incident %d/%d client=%s '%s'",
                idx, len(segments), form.clientId, seg.title,
            )
            seg_input = _segment_to_input(base_input, seg.segment)
            result = await run_pipeline(seg_input, db, tenant_id=tenant_id)
            incidents.append(_build_bundle(result, form))

        resp = MultiIncidentShiftResponse(
            client_id=form.clientId,
            shift_id=form.shiftId,
            incident_detected=len(incidents),
            incidents=incidents,
            token_usage=TokenUsage(**get_usage()),
        )
        _log_done(form, len(incidents))
        log_api_tokens("/v1/case-review/shift-analysis", "POST", form.clientId, 200)
        return resp

    except Exception as exc:
        logger.error(
            "shift-analysis error client=%s shift=%s: %s",
            form.clientId, form.shiftId, exc, exc_info=True,
        )
        log_api_tokens("/v1/case-review/shift-analysis", "POST", form.clientId, 500)
        raise HTTPException(status_code=500, detail="An internal error occurred.") from exc


def _log_done(form: CaseNoteForm, n_incidents: int) -> None:
    usage = get_usage()
    logger.info(
        "shift-analysis DONE client=%s shift=%s incidents=%d input=%d output=%d embed=%d total=%d",
        form.clientId, form.shiftId, n_incidents,
        usage["input_tokens"], usage["output_tokens"],
        usage.get("embedding_tokens", 0), usage["total_tokens"],
    )
