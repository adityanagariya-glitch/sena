import logging
import os
import secrets
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from models.db import BehaviourSupportPlan
from models.schemas import (
    AuthorisationStatus,
    BSPCreate,
    BSPResponse,
    BSPUpdateStatus,
    CaseNoteInput,
    ConfidenceLevel,
    EvaluateResponse,
    PipelineResult,
    VerdictOutcome,
    _AuthorisationSection,
    _BehaviourSupportPlan,
    _DetectedPracticeSection,
    _ReportingSection,
    _SubmissionSection,
    _VerdictSection,
)
from pipeline.graph import run_pipeline

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/restrictive-practices", tags=["restrictive-practices"])

_security = HTTPBasic(auto_error=False)


def _require_auth(credentials: Optional[HTTPBasicCredentials] = Depends(_security)) -> None:
    expected_user = os.getenv("SENA_AI_BASIC_AUTH_USER", "")
    expected_pass = os.getenv("SENA_AI_BASIC_AUTH_PASSWORD", "")
    if not expected_user or not expected_pass:
        return  # auth not configured — allow through (local dev)
    if credentials is None:
        raise HTTPException(status_code=401, detail="Unauthorized",
                            headers={"WWW-Authenticate": "Basic"})
    user_ok = secrets.compare_digest(credentials.username.encode(), expected_user.encode())
    pass_ok = secrets.compare_digest(credentials.password.encode(), expected_pass.encode())
    if not (user_ok and pass_ok):
        raise HTTPException(status_code=401, detail="Unauthorized",
                            headers={"WWW-Authenticate": "Basic"})


def _build_response(result: PipelineResult, worker_id: str) -> EvaluateResponse:
    """Transform internal PipelineResult into the human-readable API response."""
    ev = result.evaluator
    cc = result.cross_check

    # ── Verdict ───────────────────────────────────────────────────────────────
    next_steps: list[str] = []

    if not result.triage.flagged:
        outcome = VerdictOutcome.CLEAR
        risk_level = "N/A"
        action_required = "No action required. Case note passed initial screening."

    elif ev is None or not ev.incident_detected:
        outcome = VerdictOutcome.NO_INCIDENT
        risk_level = "N/A"
        action_required = "No action required. Detailed review found no violation."

    elif ev.confidence == ConfidenceLevel.LOW:
        outcome = VerdictOutcome.NO_INCIDENT
        risk_level = ev.policy_violation_risk.value
        action_required = (
            "Language in the case note is ambiguous and does not meet the threshold for "
            "a restrictive practice finding. No further action required at this stage."
        )

    elif cc and cc.authorisation_status == AuthorisationStatus.AUTHORISED_REVIEW:
        outcome = VerdictOutcome.AUTHORISED_USE
        risk_level = ev.policy_violation_risk.value
        action_required = (
            "Review the Behaviour Support Plan to confirm conditions were met. "
            "Record the use and ensure the BSP is current."
        )
        next_steps = [
            "Confirm the BSP covers this specific practice type and context.",
            "Verify the BSP is current and has not expired.",
            "Document the practice use in the participant's records.",
            "Check whether the BSP conditions (e.g. specific triggers, de-escalation first) were followed.",
        ]

    elif ev.bsp_mentioned_in_note and (cc is None or cc.bsp_id is None):
        outcome = VerdictOutcome.ADMINISTRATIVE_REVIEW
        risk_level = ev.policy_violation_risk.value
        action_required = (
            "The case note references a Behaviour Support Plan, but no matching active BSP "
            "was found in the system. Administrative verification required before escalation."
        )
        next_steps = [
            "Verify whether the PBSP has been uploaded to the system.",
            "Check whether the BSP is active and has not expired or been revoked.",
            "Confirm the BSP covers this specific practice type.",
            "Contact the authorising behaviour support practitioner to confirm current status.",
            "If BSP is confirmed active and applicable, update the system record.",
        ]

    elif ev.confidence == ConfidenceLevel.MEDIUM and (cc is None or cc.bsp_id is None):
        outcome = VerdictOutcome.POSSIBLE
        risk_level = ev.policy_violation_risk.value
        action_required = (
            "The case note suggests a possible restrictive practice, but the language is "
            "context-dependent. Escalate to a behaviour support practitioner for review."
        )
        next_steps = [
            "Escalate to a behaviour support practitioner for clinical review.",
            "Request clarification from the support worker on the specific actions described.",
            "Check whether a Behaviour Support Plan exists or is being developed for this client.",
            "If practice is confirmed, follow reporting obligations under NDIS Rules 2018.",
        ]

    else:
        outcome = VerdictOutcome.UNAUTHORISED
        risk_level = ev.policy_violation_risk.value
        timeframe = ev.notification_timeframe or "5 business days"
        action_required = (
            f"IMMEDIATE ACTION: Notify the NDIS Quality and Safeguards Commission "
            f"within {timeframe}. Document the incident and initiate a review of the "
            f"participant's Behaviour Support Plan."
        )
        next_steps = [
            f"Notify the NDIS Quality and Safeguards Commission within {timeframe}.",
            "Document the incident in the participant's records with full details.",
            "Debrief the support worker involved.",
            "Initiate a review or development of a Behaviour Support Plan for this participant.",
            "If serious injury is also involved, notify the Commission within 24 hours.",
        ]

    verdict = _VerdictSection(
        outcome=outcome,
        risk_level=risk_level,
        alert_required=result.alert_required,
        action_required=action_required,
        next_steps=next_steps,
    )

    # ── Detected practice ─────────────────────────────────────────────────────
    detected_practice = None
    if ev and ev.incident_detected:
        detected_practice = _DetectedPracticeSection(
            category=ev.practice_category,
            what_happened=ev.action_summary,
            reasoning=ev.reasoning,
            trigger_phrases=ev.trigger_phrases,
            suppression_factors=ev.suppression_factors,
        )

    # ── Authorisation ─────────────────────────────────────────────────────────
    authorisation = None
    if cc:
        bsp_on_file = cc.bsp_id is not None
        authorisation = _AuthorisationSection(
            status=cc.authorisation_status.value,
            behaviour_support_plan=_BehaviourSupportPlan(
                on_file=bsp_on_file,
                details=cc.notes or (
                    "Active Behaviour Support Plan found." if bsp_on_file
                    else "No active Behaviour Support Plan found for this client and practice type."
                ),
            ),
        )

    # ── Reporting obligations ─────────────────────────────────────────────────
    must_report = ev.reporting_required if ev else False
    reporting = _ReportingSection(
        must_report=must_report,
        notify_within=ev.notification_timeframe if ev else None,
        guidance=(
            "Under the NDIS (Restrictive Practices and Behaviour Support) Rules 2018, "
            "unauthorised use of a regulated restrictive practice is a reportable incident. "
            "Failure to report may result in regulatory action against the provider."
        ) if must_report else (
            "No mandatory reporting obligation triggered for this incident."
        ),
    )

    # ── Submission metadata ───────────────────────────────────────────────────
    submission = _SubmissionSection(
        case_note_id=str(result.case_note_id),
        client_id=result.client_id,
        worker_id=worker_id,
        screening_result=(
            "Flagged for detailed review" if result.triage.flagged
            else "Passed initial screening — no restrictive practice indicators found"
        ),
        screening_summary=result.triage.action_summary,
    )

    return EvaluateResponse(
        verdict=verdict,
        detected_practice=detected_practice,
        authorisation=authorisation,
        reporting_obligations=reporting,
        submission=submission,
        privacy=result.privacy_notice,
    )


@router.post("/evaluate", response_model=EvaluateResponse, dependencies=[Depends(_require_auth)])
async def evaluate_case_note(
    payload: CaseNoteInput,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> EvaluateResponse:
    """Run a case note through the full restrictive practice detection pipeline."""
    response.headers["X-Privacy-Classification"] = "Sensitive-Health-Information-APP3"
    response.headers["X-Data-Retention"] = "No-Retention-Session-Only"
    try:
        result = await run_pipeline(payload, db)
        return _build_response(result, worker_id=payload.worker_id)
    except Exception as exc:
        logger.error(
            "Pipeline error case_note_id=%s: %s",
            payload.case_note_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc


@router.post("/bsp", response_model=BSPResponse, status_code=201)
async def create_bsp(
    payload: BSPCreate,
    db: AsyncSession = Depends(get_db),
) -> BSPResponse:
    """Register a new Behaviour Support Plan for a client.

    Called by the platform backend when a practitioner's BSP is approved.
    One row per (client_id, practice_type) combination. To replace an existing
    authorisation, revoke the old record first then POST a new one.
    """
    bsp = BehaviourSupportPlan(
        id=str(uuid.uuid4()),
        client_id=payload.client_id,
        practice_type=payload.practice_type,
        status=payload.status,
        approved_dosage=payload.approved_dosage,
        approved_conditions=payload.approved_conditions,
        authorised_by=payload.authorised_by,
        valid_from=payload.valid_from,
        valid_until=payload.valid_until,
    )
    db.add(bsp)
    try:
        await db.commit()
        await db.refresh(bsp)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"DB error: {exc}") from exc

    return _bsp_to_response(bsp)


@router.get("/bsp/{client_id}", response_model=list[BSPResponse])
async def list_bsps(
    client_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[BSPResponse]:
    """Return all BSP records for a given client, ordered by creation date descending."""
    result = await db.execute(
        select(BehaviourSupportPlan)
        .where(BehaviourSupportPlan.client_id == client_id)
        .order_by(BehaviourSupportPlan.created_at.desc())
    )
    rows = result.scalars().all()
    return [_bsp_to_response(r) for r in rows]


@router.patch("/bsp/{bsp_id}/status", response_model=BSPResponse)
async def update_bsp_status(
    bsp_id: str,
    payload: BSPUpdateStatus,
    db: AsyncSession = Depends(get_db),
) -> BSPResponse:
    """Update the status of a BSP (e.g. revoke or expire it).

    Valid values: Active | Expired | Revoked
    """
    result = await db.execute(
        select(BehaviourSupportPlan).where(BehaviourSupportPlan.id == bsp_id)
    )
    bsp = result.scalar_one_or_none()
    if bsp is None:
        raise HTTPException(status_code=404, detail=f"BSP {bsp_id} not found.")

    allowed = {"Active", "Expired", "Revoked"}
    if payload.status not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status '{payload.status}'. Must be one of: {', '.join(sorted(allowed))}",
        )

    bsp.status = payload.status
    await db.commit()
    await db.refresh(bsp)
    return _bsp_to_response(bsp)


def _bsp_to_response(bsp: BehaviourSupportPlan) -> BSPResponse:
    return BSPResponse(
        id=bsp.id,
        client_id=bsp.client_id,
        practice_type=bsp.practice_type,
        status=bsp.status,
        approved_dosage=bsp.approved_dosage,
        approved_conditions=bsp.approved_conditions,
        authorised_by=bsp.authorised_by,
        valid_from=bsp.valid_from,
        valid_until=bsp.valid_until,
        created_at=bsp.created_at,
    )


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "restrictive-practice-detection"}
