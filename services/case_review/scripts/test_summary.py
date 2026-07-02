"""Smoke test for Step — AI Shift Summariser.

Calls run_summary() directly via asyncio.run. No pytest, no DB connection.
Covers: routine shift, flagged behavioural, multi-section rich note, sparse note,
injury reported, and worker concern.
"""

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.schemas import CaseNoteInput
from pipeline.summary import run_summary

# ── Test fixtures ─────────────────────────────────────────────────────────────

ROUTINE_CLEAN = CaseNoteInput(
    case_note_id=uuid.uuid4(),
    client_id="test-client-1",
    worker_id="test-worker-1",
    shift_date="14 May 2026",
    shift_time="9:00 AM - 1:00 PM",
    describe=(
        "Supported Emma on a community outing to the local library and café. "
        "Emma selected her own books and ordered her own coffee at the café counter."
    ),
    assisted="Travel to and from the library via accessible bus route.",
    practised_skill="Independent ordering at the café counter.",
    participants_level_of_independence="High — Emma led all transitions and made her own choices.",
    mood="Relaxed and engaged throughout the shift.",
    what_went_well="Emma initiated a conversation with the librarian unprompted. A positive milestone.",
    medication_reminders_given=True,
)

FLAGGED_BEHAVIOURAL = CaseNoteInput(
    case_note_id=uuid.uuid4(),
    client_id="test-client-1",
    worker_id="test-worker-1",
    shift_date="14 May 2026",
    shift_time="2:00 PM - 6:00 PM",
    describe="Afternoon support session at home including meal preparation and leisure activities.",
    mood="Unsettled on arrival; became increasingly agitated during meal preparation.",
    behavioural_events=(
        "Participant began shouting and knocked a plate off the bench at approximately 3:45 PM. "
        "Worker used verbal de-escalation and offered a sensory break. "
        "Participant calmed after 15 minutes in their preferred quiet space."
    ),
    any_concerns=True,
    what_needs_further_support="Triggers around meal time transitions need review with the behaviour support practitioner.",
    carer_feedback="Carer noted similar episodes earlier in the week.",
    incident_occurred=True,
)

MULTI_SECTION_RICH = CaseNoteInput(
    case_note_id=uuid.uuid4(),
    client_id="test-client-1",
    worker_id="test-worker-1",
    shift_date="14 May 2026",
    shift_time="8:00 AM - 4:00 PM",
    worker_position="Support Worker",
    describe=(
        "Full-day support covering morning routine, hydrotherapy session, grocery shopping, "
        "and return home with afternoon meal preparation."
    ),
    assisted="Morning personal care, transportation to hydrotherapy and supermarket.",
    practised_skill=(
        "Money handling at the checkout. Participant counted coins independently for the first time."
    ),
    participants_level_of_independence=(
        "Moderate — required prompting for sequencing during morning routine; "
        "fully independent at checkout with minimal verbal cue."
    ),
    observations="Hydrotherapy produced notable reduction in muscle tension; physio to be updated.",
    mood="Positive and cooperative throughout the day.",
    what_went_well="Independent coin counting at checkout — significant skill milestone.",
    what_needs_further_support="Morning sequencing still requires 2-3 verbal prompts; consider visual schedule.",
    participant_comments="Participant said 'I want to do shopping again next week.'",
    medication_reminders_given=True,
    safety_hazards_observed=False,
    carer_feedback="Family reported participant was in good spirits on return home.",
    incident_occurred=False,
)

SPARSE_NOTE = CaseNoteInput(
    case_note_id=uuid.uuid4(),
    client_id="test-client-1",
    worker_id="test-worker-1",
    mood="Okay.",
    describe="Supported participant with daily tasks.",
)

INJURY_REPORTED = CaseNoteInput(
    case_note_id=uuid.uuid4(),
    client_id="test-client-1",
    worker_id="test-worker-1",
    shift_date="14 May 2026",
    shift_time="10:00 AM - 2:00 PM",
    describe="Community outing to the park and local shops.",
    mood="Participant was happy on arrival.",
    any_injuries=True,
    injury_description=(
        "Participant tripped on uneven paving near the park entrance and sustained a minor graze "
        "to the right knee. First aid applied on site. No medical treatment required. "
        "Incident photographed and family notified at 11:20 AM."
    ),
    safety_hazards_observed=True,
    any_concerns=True,
    incident_occurred=True,
)

WORKER_CONCERN = CaseNoteInput(
    case_note_id=uuid.uuid4(),
    client_id="test-client-1",
    worker_id="test-worker-1",
    shift_date="14 May 2026",
    shift_time="6:00 PM - 10:00 PM",
    describe="Evening support shift including dinner preparation and wind-down routine.",
    mood="Subdued and quiet — less communicative than usual.",
    observations=(
        "Participant appeared to have unexplained bruising on the left forearm. "
        "When asked, participant became distressed and did not provide an explanation."
    ),
    any_concerns=True,
    what_needs_further_support=(
        "Unexplained bruising requires follow-up. Supervisor notified during shift. "
        "Safeguarding protocol initiated."
    ),
    carer_feedback="Previous carer did not document anything unusual for yesterday's shift.",
    incident_occurred=True,
)


# ── Runner ────────────────────────────────────────────────────────────────────

async def main() -> None:
    cases = [
        ("Case 1: Routine clean shift",          ROUTINE_CLEAN),
        ("Case 2: Flagged behavioural — de-escalation", FLAGGED_BEHAVIOURAL),
        ("Case 3: Multi-section rich note",       MULTI_SECTION_RICH),
        ("Case 4: Sparse note",                   SPARSE_NOTE),
        ("Case 5: Injury reported",               INJURY_REPORTED),
        ("Case 6: Worker concern — safeguarding", WORKER_CONCERN),
    ]

    for label, note in cases:
        print(f"\n=== {label} ===")
        result = await run_summary(note)
        print(f"  ai_confidence      : {result.ai_confidence:.2f}")
        print(f"  progress_identified: {result.progress_identified}")
        print(f"  potential_risks    : {result.potential_risks}")
        print(f"  patterns_detected  : {result.patterns_detected}")
        print(f"  flagged_highlights : {result.flagged_highlights}")


if __name__ == "__main__":
    asyncio.run(main())
