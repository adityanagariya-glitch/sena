"""Debug script — run pipeline directly and print full traceback."""
import asyncio
import sys
import traceback
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.session import AsyncSessionLocal, create_tables
from models.schemas import CaseNoteInput
from pipeline.graph import run_pipeline


async def main() -> None:
    await create_tables()
    note = CaseNoteInput(
        case_note_id=uuid.UUID("a1b2c3d4-0000-0000-0000-000000000001"),
        client_id="client-demo-unauth",
        worker_id="w-001",
        transcript=(
            "I held James by the arms and forced him into the chair "
            "to stop him hitting himself."
        ),
    )
    print(f"Running pipeline for {note.case_note_id}...")
    try:
        async with AsyncSessionLocal() as db:
            result = await run_pipeline(note, db)
        print(f"SUCCESS: triage_flagged={result.triage.flagged}")
        if result.evaluator:
            print(f"  incident={result.evaluator.incident_detected}")
            print(f"  category={result.evaluator.practice_category}")
            print(f"  risk={result.evaluator.policy_violation_risk}")
            print(f"  reporting_required={result.evaluator.reporting_required}")
        print(f"  alert_required={result.alert_required}")
    except Exception as exc:
        print(f"\nERROR: {type(exc).__name__}: {exc}")
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
