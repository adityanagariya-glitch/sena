"""Smoke test for Step 4 — RAG Retrieval."""

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.session import AsyncSessionLocal
from models.schemas import CaseNoteInput, TriageResult
from pipeline.rag import retrieve_policy_chunks

NOTE = CaseNoteInput(
    case_note_id=uuid.uuid4(),
    client_id="client-001",
    worker_id="worker-001",
    describe="Support session at the day centre.",
    behavioural_events="John was becoming agitated so I gave him 5mg of diazepam to calm him down.",
    incident_occurred=True,
)

TRIAGE = TriageResult(
    flagged=True,
    action_summary="Diazepam was administered to control the participant's behaviour.",
)


async def main() -> None:
    async with AsyncSessionLocal() as db:
        chunks = await retrieve_policy_chunks(NOTE, TRIAGE, db)

    print(f"Retrieved {len(chunks)} chunk(s):\n")
    for i, c in enumerate(chunks, 1):
        print(f"  [{i}] category={c.category}  risk={c.risk_level}")
        print(f"       source={c.document_source}")
        print(f"       text preview: {c.text[:120]}...")
        print()


if __name__ == "__main__":
    asyncio.run(main())
