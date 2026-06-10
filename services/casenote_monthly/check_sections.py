"""Internal per-section usage & timing check (NOT part of the production API).

Runs the same 7-section pipeline as api_main but records each section's token
usage and wall-clock time individually, then writes a detailed breakdown to
output/usage_sections.json. Use this to see which section is slow / token-heavy.

The production path (api_main._generate_report) is unchanged — this is a separate
diagnostic harness that reuses api_main's building blocks.

Run:
    cd /home/main/SENA/services/casenote_monthly
    /home/main/SENA/ai-sena/bin/python check_sections.py
"""
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import api_main as A
from config import MODEL_ID
from stats import compute_stats
import prompt as P

# ── Load example.json (file starts with a U+200B zero-width space) ─────────────
raw = json.loads((HERE / "example.json").read_bytes().lstrip(b"\xe2\x80\x8b").decode("utf-8"))
DATA = raw.get("data", raw)
CLIENT_ID = DATA.get("client", {}).get("id", "demo-client")
DATE_FROM = DATA.get("dateFrom", "2026-05-01")
DATE_TO = DATA.get("dateTo", "2026-05-31")


async def _timed_section(i: int, sec: dict, subs: dict) -> tuple[int, str, dict, float]:
    """Run one section, returning (index, text, usage, elapsed_sec)."""
    t0 = time.monotonic()
    text, usage = await asyncio.to_thread(A._call_bedrock, sec, subs)
    elapsed = round(time.monotonic() - t0, 2)
    print(f"  section {i} done  in={usage.get('inputTokens', 0)} "
          f"out={usage.get('outputTokens', 0)}  {elapsed}s")
    return i, text, usage, elapsed


async def main() -> None:
    print(f"Per-section check — client={CLIENT_ID}  period={DATE_FROM} → {DATE_TO}\n")

    stats = compute_stats(DATA, DATE_FROM, DATE_TO)

    # Discover sections (same logic as api_main._generate_report)
    sections: list[tuple[int, dict]] = []
    for i in range(1, 50):
        obj = getattr(P, f"section_{i}", None)
        if obj is None:
            continue
        sec = A._normalize(obj)
        if "user" in sec:
            sections.append((i, sec))

    wave1 = [(i, sec) for i, sec in sections if i != 7]
    wave2 = [(i, sec) for i, sec in sections if i == 7]

    base_subs = A._build_subs(DATA, {}, stats)

    # Wave 1: sections 1–6 in parallel
    print("Wave 1: sections 1–6 in parallel")
    wall0 = time.monotonic()
    wave1_results = await asyncio.gather(
        *[_timed_section(i, sec, base_subs) for i, sec in wave1]
    )
    section_outputs = {i: text for i, text, _, _ in wave1_results}

    # Wave 2: section 7 (uses 3/4/5 context)
    print("Wave 2: section 7")
    for i, sec in wave2:
        idx, text, usage, elapsed = await _timed_section(
            i, sec, A._build_subs(DATA, section_outputs, stats)
        )
        section_outputs[idx] = text
        wave1_results = list(wave1_results) + [(idx, text, usage, elapsed)]
    wall = round(time.monotonic() - wall0, 2)

    # Build per-section breakdown
    per_section: dict[str, dict] = {}
    tot_in = tot_out = 0
    for i, text, usage, elapsed in sorted(wave1_results, key=lambda r: r[0]):
        in_t = usage.get("inputTokens", 0)
        out_t = usage.get("outputTokens", 0)
        tot_in += in_t
        tot_out += out_t
        per_section[f"section_{i}"] = {
            "inputTokens": in_t,
            "outputTokens": out_t,
            "totalTokens": in_t + out_t,
            "elapsed_sec": elapsed,
            "chars": len(text),
        }

    report = {
        "model": MODEL_ID,
        "client_id": CLIENT_ID,
        "period": f"{DATE_FROM} → {DATE_TO}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "wall_clock_sec": wall,
        "sections": per_section,
        "totals": {
            "inputTokens": tot_in,
            "outputTokens": tot_out,
            "totalTokens": tot_in + tot_out,
        },
    }

    out_dir = HERE / "output"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "usage_sections.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"\n{'='*60}")
    print(f"wall-clock : {wall}s   (parallel wave 1 + sequential section 7)")
    print(f"sum of section times : {sum(s['elapsed_sec'] for s in per_section.values()):.1f}s")
    print(f"tokens : in={tot_in:,}  out={tot_out:,}  total={tot_in + tot_out:,}")
    print(f"saved → output/usage_sections.json")
    print(f"{'='*60}")
    # Quick slowest/heaviest callout
    slowest = max(per_section.items(), key=lambda kv: kv[1]["elapsed_sec"])
    heaviest = max(per_section.items(), key=lambda kv: kv[1]["totalTokens"])
    print(f"slowest section  : {slowest[0]}  ({slowest[1]['elapsed_sec']}s)")
    print(f"heaviest section : {heaviest[0]}  ({heaviest[1]['totalTokens']:,} tokens)")


if __name__ == "__main__":
    asyncio.run(main())
