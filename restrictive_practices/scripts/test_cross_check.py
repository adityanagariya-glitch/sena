"""Smoke test for Step 6 — Deterministic Cross-Check."""

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete
from db.session import AsyncSessionLocal, create_tables
from models.db import BehaviourSupportPlan
from models.schemas import CaseNoteInput, EvaluatorOutput, PolicyViolationRisk
from pipeline.cross_check import run_cross_check

NOTE = CaseNoteInput(
    case_note_id=uuid.uuid4(),
    client_id="client-001",
    worker_id="worker-001",
    describe="Support session at the day centre.",
    behavioural_events="I gave him 5mg of diazepam to calm him down.",
    incident_occurred=True,
)

EVALUATOR = EvaluatorOutput(
    incident_detected=True,
    practice_category="Chemical Restraint",
    action_summary="Diazepam administered to control behaviour.",
    policy_violation_risk=PolicyViolationRisk.HIGH,
    reasoning="Medication used to control behaviour without evident authorisation.",
)


async def seed_bsp(db) -> str:
    """Insert a test BSP and return its id."""
    bsp_id = str(uuid.uuid4())
    bsp = BehaviourSupportPlan(
        id=bsp_id,
        client_id="client-001",
        practice_type="chemical restraint",
        status="Active",
        approved_dosage="Up to 5mg diazepam PRN",
        approved_conditions="Only when de-escalation techniques have failed",
        authorised_by="Dr. Jane Smith (Behaviour Support Practitioner)",
    )
    db.add(bsp)
    await db.commit()
    return bsp_id


async def cleanup_bsp(db, bsp_id: str) -> None:
    await db.execute(delete(BehaviourSupportPlan).where(BehaviourSupportPlan.id == bsp_id))
    await db.commit()


async def main() -> None:
    await create_tables()

    async with AsyncSessionLocal() as db:
        # Case 1: No BSP → should be UNAUTHORISED
        result = await run_cross_check(NOTE, EVALUATOR, db)
        print("=== Case 1: No BSP (expect UNAUTHORISED) ===")
        print(f"  status : {result.authorisation_status.value}")
        print(f"  bsp_id : {result.bsp_id}")
        print(f"  notes  : {result.notes}\n")

        # Case 2: Active BSP exists → should be AUTHORISED_REVIEW
        bsp_id = await seed_bsp(db)
        result2 = await run_cross_check(NOTE, EVALUATOR, db)
        print("=== Case 2: Active BSP exists (expect AUTHORISED_REVIEW) ===")
        print(f"  status : {result2.authorisation_status.value}")
        print(f"  bsp_id : {result2.bsp_id}")
        print(f"  notes  : {result2.notes}\n")

        # Cleanup test data
        await cleanup_bsp(db, bsp_id)


if __name__ == "__main__":
    asyncio.run(main())
