"""End-to-end smoke test for Step 7 — full LangGraph pipeline."""

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.session import AsyncSessionLocal, create_tables
from models.schemas import CaseNoteInput
from pipeline.graph import run_pipeline

FLAGGED_NOTE = CaseNoteInput(
    case_note_id=uuid.uuid4(),
    client_id="client-e2e-001",
    worker_id="worker-001",
    transcript=(
        "John was becoming agitated and started hitting the table. "
        "I gave him 5mg of diazepam to calm him down before the group activity. "
        "He settled after about 20 minutes."
    ),
)

CLEAN_NOTE = CaseNoteInput(
    case_note_id=uuid.uuid4(),
    client_id="client-e2e-002",
    worker_id="worker-001",
    transcript=(
        "Assisted Sarah with her morning routine, prepared breakfast, "
        "and supported her to attend her physio appointment. She was in good spirits."
    ),
)


def _print_result(label: str, result) -> None:
    print(f"\n{'='*55}")
    print(f"  {label}")
    print(f"{'='*55}")
    print(f"  triage.flagged       : {result.triage.flagged}")
    if result.triage.action_summary:
        print(f"  triage.summary       : {result.triage.action_summary}")
    if result.evaluator:
        print(f"  evaluator.category   : {result.evaluator.practice_category}")
        print(f"  evaluator.risk       : {result.evaluator.policy_violation_risk.value}")
    if result.cross_check:
        print(f"  cross_check.status   : {result.cross_check.authorisation_status.value}")
    print(f"  alert_required       : {result.alert_required}")


async def main() -> None:
    await create_tables()

    async with AsyncSessionLocal() as db:
        print("\nRunning FLAGGED note (chemical restraint)...")
        r1 = await run_pipeline(FLAGGED_NOTE, db)
        _print_result("FLAGGED NOTE — chemical restraint", r1)

    async with AsyncSessionLocal() as db:
        print("\nRunning CLEAN note (no practice)...")
        r2 = await run_pipeline(CLEAN_NOTE, db)
        _print_result("CLEAN NOTE — normal support", r2)


if __name__ == "__main__":
    asyncio.run(main())
