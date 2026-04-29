"""Smoke test for Step 3 — Triage Classifier."""

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.schemas import CaseNoteInput
from pipeline.triage import run_triage

FLAGGED_NOTE = CaseNoteInput(
    case_note_id=uuid.uuid4(),
    client_id="client-001",
    worker_id="worker-001",
    transcript="John was becoming agitated so I gave him 5mg of diazepam to calm him down before the group activity.",
)

CLEAN_NOTE = CaseNoteInput(
    case_note_id=uuid.uuid4(),
    client_id="client-002",
    worker_id="worker-001",
    transcript="Assisted Sarah with her morning routine, prepared breakfast, and supported her to attend her physio appointment.",
)

SECLUSION_NOTE = CaseNoteInput(
    case_note_id=uuid.uuid4(),
    client_id="client-003",
    worker_id="worker-002",
    transcript="Michael was refusing to cooperate so we put him in the quiet room and locked the door until he settled down.",
)


async def main() -> None:
    cases = [
        ("FLAGGED (chemical restraint)", FLAGGED_NOTE),
        ("CLEAN (normal support)",       CLEAN_NOTE),
        ("FLAGGED (seclusion)",          SECLUSION_NOTE),
    ]

    for label, note in cases:
        result = await run_triage(note)
        status = "[FLAGGED]" if result.flagged else "[CLEAN]  "
        print(f"[{status}] {label}")
        if result.action_summary:
            print(f"          summary: {result.action_summary}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
