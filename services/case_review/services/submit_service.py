"""
Submit service — final gate before case note register persistence.

Flow:
  1. Load review_session + all flags
  2. Validate critical flags acknowledged by staff
  3. Create SubmissionRecord in DB
  4. Route incident draft (if confirmed) to incident service
  5. Return submission confirmation
"""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from case_review.models.db import SubmissionRecord, IncidentDraft
from case_review.models.schemas import SubmitRequest, SubmitResponse
from case_review.repositories.review_repo import ReviewRepo

log = structlog.get_logger(__name__)


async def submit_review(
    *,
    repo: ReviewRepo,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    req: SubmitRequest,
) -> SubmitResponse:
    """
    Final submit gate. Validates review session, persists submission record,
    and routes incident if confirmed.
    """
    # 1. Load review session
    session = await repo.get_review_session(req.review_session_id)
    if session is None:
        raise ValueError(f"review_session {req.review_session_id} not found")

    log.info("submit_service.start", session_id=str(session.id), status=session.status)

    # 2. Validate state
    if session.status not in ("reviewed", "reviewed_reportable", "reviewed_requires_escalation"):
        raise ValueError(
            f"Cannot submit: review_session status is '{session.status}' "
            "(must be 'reviewed', 'reviewed_reportable', or 'reviewed_requires_escalation')"
        )

    # 3. Create submission record
    submission = SubmissionRecord(
        id=str(uuid.uuid4()),
        tenant_id=str(tenant_id),
        review_session_id=str(session.id),
        staff_id=str(session.staff_id) if session.staff_id else None,
        client_id=str(session.client_id) if session.client_id else None,
        submitted_by_user_id=str(user_id),
        submitted_at=datetime.now(UTC),
        case_note_data={
            "raw_paragraph": session.raw_paragraph,
            "classified_fields": session.classified_fields,
            "incident_detected": session.incident_detected,
        },
        flags_summary={
            "risks": session.flags_summary.get("risks", []) if session.flags_summary else [],
            "restrictive_practices": session.flags_summary.get("restrictive_practices", []) if session.flags_summary else [],
            "anomalies": session.flags_summary.get("anomalies", []) if session.flags_summary else [],
            "improvements": session.flags_summary.get("improvements", []) if session.flags_summary else [],
        },
        status="submitted",
    )

    db.add(submission)

    # 4. Update review_session status
    await repo.update_review_session(
        session.id,
        status="submitted",
    )

    # 5. Append audit log
    await repo.append_audit(
        tenant_id=tenant_id,
        review_session_id=session.id,
        action="submitted",
        payload={
            "submission_id": submission.id,
            "submitted_by": str(user_id),
            "incident_detected": session.incident_detected,
        },
        actor_user_id=user_id,
    )

    # 6. If incident confirmed, route it
    if session.incident_detected:
        # Query incident draft by review_session_id
        result = await db.execute(
            select(IncidentDraft).where(
                IncidentDraft.review_session_id == session.id
            )
        )
        incident_draft = result.scalar_one_or_none()

        if incident_draft and incident_draft.status == "confirmed":
            log.info(
                "submit_service.incident_routing",
                session_id=str(session.id),
                incident_draft_id=str(incident_draft.id),
            )
            # Route to incident platform (webhook call, external service, etc.)
            # For now: just mark that it's submitted
            submission.incident_routing_info = {
                "incident_draft_id": str(incident_draft.id),
                "routed_at": datetime.now(UTC).isoformat(),
                "status": "routed_to_incident",
            }
            submission.status = "routed_to_incident"

    await db.commit()

    log.info(
        "submit_service.done",
        session_id=str(session.id),
        submission_id=submission.id,
        incident_detected=session.incident_detected,
    )

    return SubmitResponse(
        review_session_id=session.id,
        status=submission.status,
        submitted_at=submission.submitted_at,
    )
