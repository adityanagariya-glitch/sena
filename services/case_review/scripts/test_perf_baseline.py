"""Performance baseline — measures per-step latency pre/post refactor.

Runs 3 scenarios (clean, flagged, incident+alert), prints a per-step timing table
from rp_case_note_runs. Run before and after the latency refactor to diff.

Usage:
    conda activate sena_env
    python scripts/test_perf_baseline.py
"""

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.session import AsyncSessionLocal
from pipeline.graph import run_pipeline
from models.schemas import CaseNoteInput


SCENARIOS = [
    {
        "label": "CLEAN — no RP",
        "note": CaseNoteInput(
            case_note_id=uuid.uuid4(),
            client_id="perf-test-clean",
            worker_id="worker-perf",
            transcript=(
                "Had a great session with James today. We went to the park, played basketball, "
                "and made lunch together. James was calm and engaged throughout. No incidents."
            ),
        ),
    },
    {
        "label": "FLAGGED — physical restraint, no BSP",
        "note": CaseNoteInput(
            case_note_id=uuid.uuid4(),
            client_id="client-demo-unauth",
            worker_id="worker-perf",
            transcript=(
                "Tom became very agitated and started hitting himself. I grabbed his wrists "
                "and held his arms tightly against his sides for about three minutes until he "
                "calmed down. He was upset but settled after that."
            ),
        ),
    },
    {
        "label": "INCIDENT FLAGGED — worker + pipeline",
        "note": CaseNoteInput(
            case_note_id=uuid.uuid4(),
            client_id="client-demo-unauth",
            worker_id="worker-perf",
            incident_occurred=True,
            transcript=(
                "After a major meltdown at 11am, I guided Daniel into his bedroom and held "
                "the door closed from the outside for approximately fifteen minutes to give "
                "him time to calm down. He kept trying to open the door but I kept it shut "
                "until he stopped crying."
            ),
        ),
    },
]


async def run_scenario(label: str, note: CaseNoteInput) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {label}")
    print(f"{'─' * 60}")

    async with AsyncSessionLocal() as db:
        result = await run_pipeline(note, db)

    # Read the row we just wrote
    from sqlalchemy import select, text
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT processing_time_ms, triage_ms, rag_ms, evaluator_ms, "
                    "cross_check_ms, summary_ms, incident_draft_ms, alert_required "
                    "FROM rp_case_note_runs "
                    "WHERE case_note_id = :cid "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"cid": str(note.case_note_id)},
            )
        ).fetchall()

    if not rows:
        print("  [no audit row found — DB may not have new columns yet]")
        return

    row = rows[0]
    total, tr, rag, ev, cc, sm, inc, alert = row

    def ms(v):
        return f"{v:>5}ms" if v is not None else "  n/a "

    print(f"  triage:         {ms(tr)}")
    print(f"  rag:            {ms(rag)}")
    print(f"  evaluator:      {ms(ev)}")
    print(f"  cross_check:    {ms(cc)}")
    print(f"  summary:        {ms(sm)}  ← should overlap above steps")
    print(f"  incident_draft: {ms(inc)}")
    print(f"  ─────────────────────")
    print(f"  TOTAL:          {ms(total)}  alert={alert}")


async def main() -> None:
    print("\n=== PERF BASELINE ===")
    print("Running 3 scenarios. Compare before/after refactor.\n")

    for scenario in SCENARIOS:
        await run_scenario(scenario["label"], scenario["note"])

    print("\n\nDone. Compare TOTAL ms to pre-refactor values.")
    print("Expected: CLEAN ~33% faster, FLAGGED ~21% faster, INCIDENT ~16% faster.")


if __name__ == "__main__":
    asyncio.run(main())
