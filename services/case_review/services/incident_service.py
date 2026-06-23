from __future__ import annotations

"""
Incident service— detect, draft, and confirm NDIS incident reports.

Three operations:

  detect  — Triage + Evaluator to decide incident_detected (bool).
            If yes, creates an IncidentDraft row and returns its ID.

  draft   — Runs the NDIS incident drafter LLM on the session's case note.
            Creates (or overwrites) the IncidentDraft row with autofilled fields.
            Staff must confirm the draft before it can be submitted.

  confirm — Staff explicitly confirms the AI draft.
            NDIS non-negotiable: no auto-submit without human sign-off.
"""

import uuid

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import IncidentDraft
from models.schemas import (
    CaseNoteInput,
    IncidentConfirmResponse,
    IncidentDetectRequest,
    IncidentDetectResponse,
    IncidentDraftOutput,
    IncidentDraftRequest,
    IncidentDraftResponse,
)
from repositories.review_repo import ReviewRepo
from services.pipeline.evaluator import run_evaluator
from services.pipeline.incident_draft import run_incident_draft
from services.pipeline.triage import run_triage

log = structlog.get_logger(__name__)


def _build_case_note_input(session) -> CaseNoteInput:
    transcript = session.raw_paragraph or None

    if not transcript:
        fields: dict = session.classified_fields or {}
        parts = [f"{k}: {v}" for k, v in fields.items() if v]
        transcript = "\n".join(parts) if parts else None

    if not transcript:
        raise ValueError(
            f"review_session {session.id} has no content "
            "(raw_paragraph is empty and classified_fields are blank)"
        )

    return CaseNoteInput(
        case_note_id=session.id,
        client_id=str(session.client_id) if session.client_id else "unknown",
        worker_id=str(session.staff_id) if session.staff_id else "unknown",
        transcript=transcript,
    )


async def _get_existing_draft(
    db: AsyncSession, review_session_id: uuid.UUID
) -> IncidentDraft | None:
    result = await db.execute(
        select(IncidentDraft).where(
            IncidentDraft.review_session_id == review_session_id
        )
    )
    return result.scalar_one_or_none()


# ── detect ─────────────────────────────────────────────────────────────────────

async def detect_incident(
    *,
    repo: ReviewRepo,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    req: IncidentDetectRequest,
) -> IncidentDetectResponse:
    # 1. Load session
    session = await repo.get_review_session(req.review_session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"review_session {req.review_session_id} not found",
        )

    log.info("incident_service.detect.start", session_id=str(session.id))

    # 2. Build CaseNoteInput
    try:
        note = _build_case_note_input(session)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    # 3. Triage — cheap gate
    triage = await run_triage(note)

    if not triage.flagged:
        log.info("incident_service.detect.clear", session_id=str(session.id))
        await repo.append_audit(
            tenant_id=tenant_id,
            review_session_id=session.id,
            action="incident_detected",
            payload={"incident_detected": False, "triage_flagged": False},
            actor_user_id=user_id,
        )
        return IncidentDetectResponse(
            review_session_id=session.id,
            incident_detected=False,
            incident_draft_id=None,
            markers=[],
        )

    # 4. Evaluator — confirm and extract markers
    evaluator = await run_evaluator(note, triage, policy_chunks=[])
    log.info(
        "incident_service.detect.evaluator",
        session_id=str(session.id),
        incident_detected=evaluator.incident_detected,
    )

    incident_draft_id: uuid.UUID | None = None

    if evaluator.incident_detected:
        # 5. Create IncidentDraft placeholder (fields filled by /draft)
        draft = await repo.create_incident_draft(
            tenant_id=tenant_id,
            review_session_id=session.id,
            autofill_source={"source": "detect", "practice_category": evaluator.practice_category},
            draft_fields={},
        )
        incident_draft_id = draft.id

        await repo.update_review_session(
            session.id,
            incident_detected=True,
        )

    await repo.append_audit(
        tenant_id=tenant_id,
        review_session_id=session.id,
        action="incident_detected",
        payload={
            "incident_detected": evaluator.incident_detected,
            "practice_category": evaluator.practice_category,
            "risk": evaluator.policy_violation_risk.value,
        },
        actor_user_id=user_id,
    )

    return IncidentDetectResponse(
        review_session_id=session.id,
        incident_detected=evaluator.incident_detected,
        incident_draft_id=incident_draft_id,
        markers=evaluator.trigger_phrases,
    )


# ── draft ──────────────────────────────────────────────────────────────────────

async def draft_incident(
    *,
    repo: ReviewRepo,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    req: IncidentDraftRequest,
) -> IncidentDraftResponse:
    # 1. Load session
    session = await repo.get_review_session(req.review_session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"review_session {req.review_session_id} not found",
        )

    log.info("incident_service.draft.start", session_id=str(session.id))

    # 2. Build CaseNoteInput
    try:
        note = _build_case_note_input(session)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    # 3. Run the incident draft LLM (Bedrock Sonnet)
    output: IncidentDraftOutput = await run_incident_draft(note, evaluator=None)

    draft_fields = output.model_dump()
    autofill_source = {
        "source": "ai_drafter",
        "session_id": str(session.id),
        "incident_type": output.incident_type,
        "reportable": output.reportable,
    }

    # 4. Upsert — update existing draft if detect already ran, else create fresh
    existing = await _get_existing_draft(db, session.id)
    if existing is not None:
        existing.draft_fields = draft_fields
        existing.autofill_source = autofill_source
        existing.status = "draft"
        existing.staff_confirmed = False
        await db.commit()
        await db.refresh(existing)
        draft = existing
    else:
        draft = await repo.create_incident_draft(
            tenant_id=tenant_id,
            review_session_id=session.id,
            autofill_source=autofill_source,
            draft_fields=draft_fields,
        )

    await repo.append_audit(
        tenant_id=tenant_id,
        review_session_id=session.id,
        action="incident_detected",
        payload={
            "incident_draft_id": str(draft.id),
            "reportable": output.reportable,
            "notification_timeframe": output.notification_timeframe,
        },
        actor_user_id=user_id,
    )

    log.info(
        "incident_service.draft.done",
        session_id=str(session.id),
        draft_id=str(draft.id),
        reportable=output.reportable,
    )

    return IncidentDraftResponse(
        incident_draft_id=draft.id,
        draft_fields=draft_fields,
        autofill_source=autofill_source,
        status=draft.status,
    )


# ── confirm ────────────────────────────────────────────────────────────────────

async def confirm_incident(
    *,
    repo: ReviewRepo,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    incident_id: uuid.UUID,
) -> IncidentConfirmResponse:
    log.info("incident_service.confirm.start", draft_id=str(incident_id))

    # 1. Confirm the draft (sets staff_confirmed=True, status="confirmed")
    draft = await repo.confirm_incident_draft(incident_id)
    if draft is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"incident_draft {incident_id} not found",
        )

    # 2. Audit — append to the parent review_session if linked
    if draft.review_session_id is not None:
        await repo.append_audit(
            tenant_id=tenant_id,
            review_session_id=draft.review_session_id,
            action="incident_confirmed",
            payload={
                "incident_draft_id": str(draft.id),
                "staff_confirmed": True,
            },
            actor_user_id=user_id,
        )

    log.info("incident_service.confirm.done", draft_id=str(draft.id))

    return IncidentConfirmResponse(
        incident_draft_id=draft.id,
        status=draft.status,
        staff_confirmed=draft.staff_confirmed,
    )
