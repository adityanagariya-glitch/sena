"""Smoke test for Step 5 — Evaluator Agent."""

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.session import AsyncSessionLocal
from models.schemas import CaseNoteInput, TriageResult
from pipeline.evaluator import run_evaluator
from pipeline.rag import retrieve_policy_chunks

NOTE = CaseNoteInput(
    case_note_id=uuid.uuid4(),
    client_id="client-001",
    worker_id="worker-001",
    transcript=(
        "John was becoming agitated and started hitting the table. "
        "I gave him 5mg of diazepam to calm him down before the group activity. "
        "He settled after about 20 minutes."
    ),
)

TRIAGE = TriageResult(
    flagged=True,
    action_summary="Diazepam was administered to control the participant's behaviour.",
)


async def main() -> None:
    async with AsyncSessionLocal() as db:
        chunks = await retrieve_policy_chunks(NOTE, TRIAGE, db)
        result = await run_evaluator(NOTE, TRIAGE, chunks)

    print("=== EVALUATOR OUTPUT ===\n")
    print(f"  incident_detected   : {result.incident_detected}")
    print(f"  practice_category   : {result.practice_category}")
    print(f"  policy_violation_risk: {result.policy_violation_risk.value}")
    print(f"  action_summary      : {result.action_summary}")
    print(f"\n  reasoning:\n    {result.reasoning}")


if __name__ == "__main__":
    asyncio.run(main())
