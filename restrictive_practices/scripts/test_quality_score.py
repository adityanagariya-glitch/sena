"""Smoke test for pipeline/quality_score.py — 3 fixtures (Premium, Average, Poor).

Run: python scripts/test_quality_score.py
"""

import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.schemas import CaseNoteInput
from pipeline.quality_score import score_note


def _make_note(**kwargs) -> CaseNoteInput:
    defaults = dict(
        case_note_id=uuid4(),
        client_id="client-test-001",
        worker_id="worker-test-001",
    )
    defaults.update(kwargs)
    return CaseNoteInput(**defaults)


# ── Fixture 1: Premium-quality note ──────────────────────────────────────────

PREMIUM = _make_note(
    describe=(
        "Participant engaged positively throughout the majority of the shift and demonstrated "
        "ongoing progress toward several NDIS goals, including emotional regulation, community "
        "participation, communication, and independence. The shift focused on community engagement, "
        "emotional processing following interpersonal conflict at home, and social interaction with "
        "peers and staff at the support office."
    ),
    assisted=(
        "Supported participant with transport into the community, social engagement at the office, "
        "café visit, and emotional support throughout discussions regarding family conflict."
    ),
    practised_skill=(
        "Emotional regulation, social communication, community participation, independent "
        "decision-making, and self-expression."
    ),
    participants_level_of_independence=(
        "Participant independently completed personal care tasks prior to leaving home, "
        "independently ordered food and drinks at the café, and appropriately initiated "
        "conversations with peers with minimal prompting."
    ),
    observations=(
        "Participant demonstrated improved confidence engaging socially within group settings "
        "compared to previous community access shifts. While discussing frustrations relating "
        "to family conflict, maintained an appropriate tone, remained regulated, and was able "
        "to reflect on emotions without escalation."
    ),
    mood=(
        "Initially mildly subdued and frustrated; presentation improved progressively throughout "
        "the shift, becoming more relaxed, engaged, and socially interactive."
    ),
    behavioural_events=(
        "No aggressive, unsafe, or escalated behaviours observed during the shift. Mild emotional "
        "distress was identified early in the shift; however, participant remained regulated and "
        "responsive to support strategies."
    ),
    any_concerns=False,
    what_went_well=(
        "Participant demonstrated positive emotional insight and effectively communicated feelings "
        "relating to family conflict without escalation. Remained socially engaged throughout the "
        "shift and independently participated in multiple community-based activities."
    ),
    what_needs_further_support=(
        "Continued support with emotional regulation strategies and building resilience around "
        "differing opinions and perceived criticism."
    ),
    participant_comments="Participant stated it helped talking about it today.",
)

# ── Fixture 2: Average-quality note ──────────────────────────────────────────

AVERAGE = _make_note(
    describe=(
        "Participant participated appropriately throughout the shift and completed planned "
        "household tasks. Support focused on meal preparation, cleaning, and social interaction. "
        "Participant appeared in a positive mood and was cooperative."
    ),
    assisted="Supported participant with cooking dinner, cleaning shared spaces, and maintaining routines.",
    practised_skill="Independent living skills and shared household responsibilities.",
    participants_level_of_independence="Participant completed most tasks independently with occasional prompting.",
    observations=(
        "Participant interacted appropriately with housemates and remained engaged throughout "
        "the shift. Demonstrated confidence completing cooking tasks."
    ),
    mood="Positive and engaged.",
    what_went_well="Participant completed planned activities successfully.",
    what_needs_further_support="Continued development of independent cooking skills.",
)

# ── Fixture 3: Poor-quality note ──────────────────────────────────────────────

POOR = _make_note(
    describe="Participant was ok today. We did some cleaning and talked for a while.",
    assisted="Cleaning and lunch.",
    practised_skill="Daily living.",
    participants_level_of_independence="Needed prompting.",
    observations="Participant was quiet.",
    mood="Low mood.",
    what_went_well="Participant helped with cleaning.",
    what_needs_further_support="Motivation.",
)


def run_tests() -> None:
    cases = [
        ("Premium", PREMIUM, "Premium"),
        ("Average", AVERAGE, "Average"),
        ("Poor", POOR, "Poor"),
    ]

    all_passed = True
    for name, note, expected_label in cases:
        score, label, gaps = score_note(note)
        passed = label == expected_label
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_passed = False
        print(f"[{status}] {name:8s} -> score={score:.3f} label={label!r} gaps={len(gaps)}")
        if not passed:
            print(f"         Expected label={expected_label!r}")
        if gaps:
            for g in gaps[:3]:
                print(f"         gap: {g}")

    print()
    if all_passed:
        print("All quality score tests PASSED.")
        sys.exit(0)
    else:
        print("Some quality score tests FAILED.")
        sys.exit(1)


if __name__ == "__main__":
    run_tests()
