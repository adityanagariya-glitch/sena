"""Smoke test for Step — NDIS Incident Report Drafter.

Calls run_incident_draft(note, evaluator) directly via asyncio.run.
No pytest, no DB connection. Covers: worker-flagged only, flagged + MEDIUM
evaluator, HIGH unauthorised RP, chemical restraint, seclusion, and
worker-flagged with serious injury.
"""

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.schemas import (
    CaseNoteInput,
    ConfidenceLevel,
    EvaluatorOutput,
    PolicyViolationRisk,
)
from pipeline.incident_draft import run_incident_draft

# ── Shared note builders ──────────────────────────────────────────────────────

def _make_note(
    *,
    describe: str,
    behavioural_events: str | None = None,
    any_concerns: bool = False,
    incident_occurred: bool = True,
    any_injuries: bool = False,
    injury_description: str | None = None,
    mood: str | None = None,
    shift_date: str = "14 May 2026",
    shift_time: str = "2:00 PM - 10:00 PM",
) -> CaseNoteInput:
    return CaseNoteInput(
        case_note_id=uuid.uuid4(),
        client_id="test-client-1",
        worker_id="test-worker-1",
        shift_date=shift_date,
        shift_time=shift_time,
        describe=describe,
        behavioural_events=behavioural_events,
        any_concerns=any_concerns,
        incident_occurred=incident_occurred,
        any_injuries=any_injuries,
        injury_description=injury_description,
        mood=mood,
    )


# ── Evaluator mock constructors ───────────────────────────────────────────────

def _medium_evaluator(category: str, summary: str) -> EvaluatorOutput:
    return EvaluatorOutput(
        incident_detected=True,
        practice_category=category,
        action_summary=summary,
        policy_violation_risk=PolicyViolationRisk.MEDIUM,
        confidence=ConfidenceLevel.MEDIUM,
        reasoning=(
            f"The case note contains language consistent with {category}. "
            "Confidence is MEDIUM because the note lacks explicit documentation of authorisation. "
            "Further review is required to confirm whether a BSP is on file."
        ),
        reporting_required=False,
        notification_timeframe=None,
    )


def _high_evaluator(
    category: str,
    summary: str,
    notification_timeframe: str = "5 business days",
) -> EvaluatorOutput:
    return EvaluatorOutput(
        incident_detected=True,
        practice_category=category,
        action_summary=summary,
        policy_violation_risk=PolicyViolationRisk.HIGH,
        confidence=ConfidenceLevel.HIGH,
        reasoning=(
            f"The case note contains explicit evidence of {category} used without documented "
            "authorisation. No BSP found in the system. High-confidence finding."
        ),
        reporting_required=True,
        notification_timeframe=notification_timeframe,
    )


# ── Test fixtures ─────────────────────────────────────────────────────────────

# Case 1: Worker flagged only — no prior AI evaluator findings
CASE_1_NOTE = _make_note(
    describe=(
        "Evening support shift at group home. Participant became distressed during dinner. "
        "Worker intervened physically to prevent self-harm. Incident reported to supervisor."
    ),
    behavioural_events="Participant struck head against wall. Worker held participant's arms to prevent injury.",
    any_concerns=True,
    incident_occurred=True,
)
CASE_1_EVALUATOR = None

# Case 2: Worker flagged + MEDIUM confidence evaluator — environmental restraint
CASE_2_NOTE = _make_note(
    describe="Day program support session at the activity centre.",
    behavioural_events=(
        "Participant attempted to leave the building repeatedly. "
        "Staff locked the external door to prevent the participant from leaving unaccompanied."
    ),
    any_concerns=True,
    incident_occurred=True,
)
CASE_2_EVALUATOR = _medium_evaluator(
    category="Environmental Restraint",
    summary="Staff locked external door to prevent participant from leaving the building unaccompanied.",
)

# Case 3: Unauthorised RP — HIGH confidence, physical restraint, no BSP
CASE_3_NOTE = _make_note(
    describe="Afternoon support at residential facility.",
    behavioural_events=(
        "Participant became extremely agitated and started throwing objects. "
        "Two workers physically restrained the participant on the floor for approximately 8 minutes "
        "until they calmed down. No BSP on file. Supervisor notified after the incident."
    ),
    any_concerns=True,
    incident_occurred=True,
)
CASE_3_EVALUATOR = _high_evaluator(
    category="Physical Restraint",
    summary=(
        "Two workers applied prone physical restraint for 8 minutes without documented BSP authorisation."
    ),
    notification_timeframe="5 business days",
)

# Case 4: Chemical restraint — possible unauthorised use
CASE_4_NOTE = _make_note(
    describe="Morning support shift at participant's home.",
    behavioural_events=(
        "Participant was agitated and refusing morning medication. "
        "Worker crushed the participant's prescribed quetiapine and mixed it into their breakfast "
        "without consent. Participant was calmer within 30 minutes."
    ),
    any_concerns=True,
    incident_occurred=True,
)
CASE_4_EVALUATOR = _high_evaluator(
    category="Chemical Restraint",
    summary=(
        "Prescribed medication administered covertly in food without participant consent "
        "and without documented chemical restraint authorisation."
    ),
    notification_timeframe="5 business days",
)

# Case 5: Seclusion — with injury noted
CASE_5_NOTE = _make_note(
    describe="Residential facility support shift — evening routine.",
    behavioural_events=(
        "Participant became highly agitated after dinner. Staff placed participant in the "
        "seclusion room and secured the door for 25 minutes. Participant was found to have "
        "a small laceration on the hand when released, consistent with hitting the door."
    ),
    any_concerns=True,
    incident_occurred=True,
    any_injuries=True,
    injury_description=(
        "Small laceration approximately 1 cm to the left hand, sustained while inside the "
        "seclusion room. First aid applied. Family notified."
    ),
)
CASE_5_EVALUATOR = _high_evaluator(
    category="Seclusion",
    summary="Participant secured in seclusion room for 25 minutes; injury sustained during seclusion.",
    notification_timeframe="24 hours",
)

# Case 6: Worker flagged + serious injury — 24h notification expected
CASE_6_NOTE = _make_note(
    describe="Community access support — trip to local shopping centre.",
    behavioural_events=(
        "Participant slipped while exiting the accessible bus and fell heavily onto the footpath. "
        "Suspected fractured wrist — taken to emergency by ambulance. Family and supervisor notified."
    ),
    any_concerns=True,
    incident_occurred=True,
    any_injuries=True,
    injury_description="Participant fell and sustained a laceration to the scalp and suspected fractured wrist. Ambulance called.",
    mood="Participant was distressed and in pain.",
)
CASE_6_EVALUATOR = None  # Worker-flagged only; serious injury drives 24h category


# ── Runner ────────────────────────────────────────────────────────────────────

async def main() -> None:
    cases = [
        ("Case 1: Worker-flagged only — no AI findings",               CASE_1_NOTE, CASE_1_EVALUATOR),
        ("Case 2: Worker-flagged + MEDIUM evaluator (Env Restraint)",  CASE_2_NOTE, CASE_2_EVALUATOR),
        ("Case 3: Unauthorised RP — HIGH confidence, Physical Restraint", CASE_3_NOTE, CASE_3_EVALUATOR),
        ("Case 4: Chemical Restraint — covert medication",             CASE_4_NOTE, CASE_4_EVALUATOR),
        ("Case 5: Seclusion — with injury",                            CASE_5_NOTE, CASE_5_EVALUATOR),
        ("Case 6: Worker-flagged + serious injury — 24h notification", CASE_6_NOTE, CASE_6_EVALUATOR),
    ]

    for label, note, evaluator in cases:
        print(f"\n=== {label} ===")
        result = await run_incident_draft(note, evaluator)
        print(f"  incident_type             : {result.incident_type}")
        print(f"  reportable                : {result.reportable}")
        print(f"  notification_timeframe    : {result.notification_timeframe}")
        print(f"  restrictive_practice_used : {result.restrictive_practice_used}")
        print(f"  restrictive_practice_cat  : {result.restrictive_practice_category}")
        checks_summary = "; ".join(
            f"{c['label']} => {'PASS' if c['passed'] else 'FAIL'}"
            for c in result.compliance_checks
        )
        print(f"  compliance_checks         : {checks_summary or '(none)'}")


if __name__ == "__main__":
    asyncio.run(main())
