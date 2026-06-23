from __future__ import annotations

"""
Review service — runs the RP pipeline on a classified review session.

Flow:
  1. Load review_session — must exist and have raw_paragraph content
  2. Build CaseNoteInput from session data
  3. Run triage (cheap Haiku gate)
  4. If flagged: run evaluator (Sonnet, no RAG — policy context omitted for speed)
  5. Map pipeline output → FlagItem lists (risks, restrictive_practices, anomalies, improvements)
  6. Persist flags + incident_detected to review_session (status → "reviewed")
  7. Append audit log
  8. Return ReviewResponse
"""

import uuid

import structlog

from models.schemas import (
    CaseNoteInput,
    EvaluatorOutput,
    FlagItem,
    PolicyViolationRisk,
    ReviewRequest,
    ReviewResponse,
    TriageResult,
)
from repositories.review_repo import ReviewRepo
from services.pipeline.triage import run_triage
from services.pipeline.evaluator import run_evaluator

log = structlog.get_logger(__name__)

# NDIS reference strings
_RP_RULES_REF = "NDIS (Restrictive Practices and Behaviour Support) Rules 2018"
_INCIDENT_RULES_CAT1 = (
    "NDIS (Incident Management and Reportable Incidents) Rules 2016 — Category 1 (24 hours)"
)
_INCIDENT_RULES_CAT2 = (
    "NDIS (Incident Management and Reportable Incidents) Rules 2016 — Category 2 (5 business days)"
)

_SEVERITY_MAP: dict[PolicyViolationRisk, str] = {
    PolicyViolationRisk.LOW: "low",
    PolicyViolationRisk.MEDIUM: "medium",
    PolicyViolationRisk.HIGH: "high",
    PolicyViolationRisk.CRITICAL: "critical",
}


def _map_to_flags(
    triage: TriageResult,
    evaluator: EvaluatorOutput | None,
) -> tuple[list[FlagItem], list[FlagItem], list[FlagItem], list[FlagItem]]:
    """Map triage + evaluator output to the four FlagItem lists."""
    risks: list[FlagItem] = []
    restrictive_practices: list[FlagItem] = []
    anomalies: list[FlagItem] = []
    improvements: list[FlagItem] = []

    if not triage.flagged or evaluator is None:
        if not triage.flagged:
            improvements.append(FlagItem(
                category="Note Quality",
                description="No restrictive practice signals detected. Note appears compliant.",
                severity="low",
                ndis_reference=None,
            ))
        return risks, restrictive_practices, anomalies, improvements

    severity = _SEVERITY_MAP.get(evaluator.policy_violation_risk, "medium")

    # ── Restrictive practices ──────────────────────────────────────────────────
    if evaluator.incident_detected and evaluator.practice_category not in ("None", ""):
        restrictive_practices.append(FlagItem(
            category=evaluator.practice_category,
            description=evaluator.action_summary,
            severity=severity,
            ndis_reference=_RP_RULES_REF,
        ))

    # ── Risks ─────────────────────────────────────────────────────────────────
    if evaluator.reporting_required:
        if evaluator.notification_timeframe == "24 hours":
            ndis_ref = _INCIDENT_RULES_CAT1
        elif evaluator.notification_timeframe == "5 business days":
            ndis_ref = _INCIDENT_RULES_CAT2
        else:
            ndis_ref = None
        risks.append(FlagItem(
            category="Mandatory Reporting Required",
            description=(
                f"Incident must be reported to the NDIS Quality and Safeguards Commission"
                + (f" within {evaluator.notification_timeframe}." if evaluator.notification_timeframe else ".")
            ),
            severity=severity,
            ndis_reference=ndis_ref,
        ))
    elif evaluator.incident_detected:
        risks.append(FlagItem(
            category="Policy Violation Risk",
            description=evaluator.reasoning[:300],
            severity=severity,
            ndis_reference=_RP_RULES_REF,
        ))

    # ── Anomalies — trigger phrases extracted by the evaluator ────────────────
    for phrase in evaluator.trigger_phrases[:5]:
        anomalies.append(FlagItem(
            category="Evidence Phrase",
            description=phrase,
            severity="medium",
            ndis_reference=None,
        ))

    # ── Improvements — mitigating / suppression factors ───────────────────────
    for factor in evaluator.suppression_factors[:3]:
        improvements.append(FlagItem(
            category="Mitigating Factor",
            description=factor,
            severity="low",
            ndis_reference=None,
        ))

    return risks, restrictive_practices, anomalies, improvements


def _build_case_note_input(session) -> CaseNoteInput:
    """Build a CaseNoteInput from a ReviewSession row."""
    transcript = session.raw_paragraph or None

    # If raw_paragraph is empty, assemble from classified_fields as fallback
    if not transcript:
        fields: dict = session.classified_fields or {}
        parts = [f"{k}: {v}" for k, v in fields.items() if v]
        transcript = "\n".join(parts) if parts else None

    if not transcript:
        raise ValueError(
            f"review_session {session.id} has no content to review "
            "(raw_paragraph is empty and classified_fields are blank)"
        )

    return CaseNoteInput(
        case_note_id=session.id,
        client_id=str(session.client_id) if session.client_id else "unknown",
        worker_id=str(session.staff_id) if session.staff_id else "unknown",
        transcript=transcript,
    )


async def review_session_pipeline(
    *,
    repo: ReviewRepo,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    req: ReviewRequest,
) -> ReviewResponse:
    # ── 1. Load session ────────────────────────────────────────────────────────
    session = await repo.get_review_session(req.review_session_id)
    if session is None:
        raise ValueError(f"review_session {req.review_session_id} not found")

    log.info("review_service.start", session_id=str(session.id))

    # ── 2. Build CaseNoteInput ─────────────────────────────────────────────────
    note = _build_case_note_input(session)

    # ── 3. Triage ──────────────────────────────────────────────────────────────
    triage = await run_triage(note)
    log.info(
        "review_service.triage",
        session_id=str(session.id),
        flagged=triage.flagged,
        confidence=triage.confidence,
    )

    # ── 4. Evaluator (only when triage flags something) ────────────────────────
    evaluator: EvaluatorOutput | None = None
    if triage.flagged:
        # policy_chunks=[] — runs without RAG; evaluation is still grounded via
        # the evaluator's built-in NDIS knowledge in the system prompt.
        evaluator = await run_evaluator(note, triage, policy_chunks=[])
        log.info(
            "review_service.evaluator",
            session_id=str(session.id),
            incident_detected=evaluator.incident_detected,
            risk=evaluator.policy_violation_risk.value,
        )

    # ── 5. Map to FlagItem lists ───────────────────────────────────────────────
    risks, rps, anomalies, improvements = _map_to_flags(triage, evaluator)

    # ── 6. Persist ─────────────────────────────────────────────────────────────
    flags_payload = {
        "risks": [f.model_dump() for f in risks],
        "restrictive_practices": [f.model_dump() for f in rps],
        "anomalies": [f.model_dump() for f in anomalies],
        "improvements": [f.model_dump() for f in improvements],
    }
    incident_detected = evaluator.incident_detected if evaluator else False

    session = await repo.update_review_session(
        session.id,
        flags=flags_payload,
        incident_detected=incident_detected,
        status="reviewed",
    )
    assert session is not None

    # ── 7. Audit ───────────────────────────────────────────────────────────────
    action = "ai_flag_raised" if incident_detected else "ai_review_complete"
    await repo.append_audit(
        tenant_id=tenant_id,
        review_session_id=session.id,
        action=action,
        payload={
            "triage_flagged": triage.flagged,
            "incident_detected": incident_detected,
            "risk": evaluator.policy_violation_risk.value if evaluator else None,
        },
        actor_user_id=user_id,
    )

    # ── 8. Return ──────────────────────────────────────────────────────────────
    log.info("review_service.done", session_id=str(session.id), action=action)
    return ReviewResponse(
        review_session_id=session.id,
        risks=risks,
        restrictive_practices=rps,
        anomalies=anomalies,
        improvements=improvements,
        status=session.status,
    )
