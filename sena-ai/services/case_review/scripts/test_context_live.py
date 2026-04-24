"""
Live smoke test — real Gemini API call with fixture notes.
No DB / Docker required. Just needs SENA_AI_GEMINI_API_KEY in env.

Run from service root:
    python scripts/test_context_live.py

Optional: pass --past to test incremental update (non-empty past summary).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# Allow running without editable install
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from case_review.clients.case_note_client import CaseNoteClient
from case_review.core.settings import settings  # loads sena-ai/.env via pydantic-settings
from case_review.services.llm.summarizer import summarise

# settings already resolved SENA_AI_GEMINI_API_KEY from .env — no bare os.environ needed
API_KEY = settings.gemini_api_key
MODEL   = settings.gemini_model_id

PAST_SUMMARY_EXAMPLE = (
    "Participant has been working on daily living skills. "
    "Previous sessions focused on meal preparation and community access. "
    "Generally positive engagement with occasional sensory sensitivities noted."
)


async def run(use_past: bool) -> None:
    if not API_KEY:
        print("ERROR: SENA_AI_GEMINI_API_KEY not set in environment.")
        sys.exit(1)

    client = CaseNoteClient(stub=True)
    notes  = await client.get_notes("staff-uuid-001", "client-uuid-001", limit=10)

    print(f"\n{'='*60}")
    print(f"Model      : {MODEL}")
    print(f"Notes      : {len(notes)} (from fixtures/sample_notes.json)")
    print(f"Past summary: {'yes (incremental test)' if use_past else 'empty (cold-start test)'}")
    print(f"{'='*60}\n")

    past = PAST_SUMMARY_EXAMPLE if use_past else ""

    result = await summarise(
        past_summary=past,
        new_notes=notes,
        api_key=API_KEY,
        model_id=MODEL,
    )

    print("── SUMMARY ──────────────────────────────────────────────")
    print(result.summary_text)
    print()
    print("── METADATA ─────────────────────────────────────────────")
    print(json.dumps(result.metadata, indent=2))
    print()


if __name__ == "__main__":
    use_past = "--past" in sys.argv
    asyncio.run(run(use_past))
