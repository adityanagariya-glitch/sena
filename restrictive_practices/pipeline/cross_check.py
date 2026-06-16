"""Step 6 — Deterministic Cross-Check.

Pure SQL lookup against behaviour_support_plans. No LLM involved.
Answers: was this practice pre-authorised for this specific client?

Decision tree:
  evaluator.incident_detected=False  → NO_INCIDENT_DETECTED
  no matching active BSP found       → UNAUTHORISED_RESTRICTIVE_PRACTICE
  matching BSP found                 → AUTHORISED_USE (Review Required)
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import BehaviourSupportPlan
from models.schemas import (
    AuthorisationStatus,
    CaseNoteInput,
    CrossCheckResult,
    EvaluatorOutput,
)

logger = logging.getLogger(__name__)


async def run_cross_check(
    note: CaseNoteInput,
    evaluator: EvaluatorOutput,
    db: AsyncSession,
) -> CrossCheckResult:
    """Check whether the detected practice is authorised in a current BSP."""
    if not evaluator.incident_detected:
        return CrossCheckResult(
            authorisation_status=AuthorisationStatus.NO_INCIDENT,
            notes="Evaluator found no regulated restrictive practice.",
        )

    now = datetime.now(timezone.utc).replace(tzinfo=None)  # DB stores naive UTC

    # Case-insensitive match on practice_type — evaluator may vary capitalisation
    stmt = select(BehaviourSupportPlan).where(
        and_(
            BehaviourSupportPlan.client_id == note.client_id,
            func.lower(BehaviourSupportPlan.practice_type) == evaluator.practice_category.lower(),
            BehaviourSupportPlan.status == "Active",
            # valid_from null = always valid from start; valid_until null = no expiry
            BehaviourSupportPlan.valid_from.is_(None) | (BehaviourSupportPlan.valid_from <= now),
            BehaviourSupportPlan.valid_until.is_(None) | (BehaviourSupportPlan.valid_until >= now),
        )
    )

    result = await db.execute(stmt)
    bsp: BehaviourSupportPlan | None = result.scalars().first()

    logger.info(
        "cross_check case_note_id=%s client=%s category=%s bsp_found=%s",
        note.case_note_id,
        note.client_id,
        evaluator.practice_category,
        bsp is not None,
    )

    if bsp is None:
        return CrossCheckResult(
            authorisation_status=AuthorisationStatus.UNAUTHORISED,
            conditions_met=False,
            notes=(
                f"No active Behaviour Support Plan found for client '{note.client_id}' "
                f"authorising '{evaluator.practice_category}'."
            ),
        )

    # BSP exists — authorised but must still be reviewed for conditions compliance
    conditions_note = ""
    if bsp.approved_conditions:
        conditions_note = f" Approved conditions: {bsp.approved_conditions}"
    if bsp.approved_dosage:
        conditions_note += f" Approved dosage: {bsp.approved_dosage}"

    return CrossCheckResult(
        authorisation_status=AuthorisationStatus.AUTHORISED_REVIEW,
        bsp_id=bsp.id,
        conditions_met=True,
        notes=(
            f"Active BSP found (authorised by: {bsp.authorised_by or 'unknown'})."
            + conditions_note
        ),
    )
