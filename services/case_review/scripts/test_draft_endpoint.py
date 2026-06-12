"""
Smoke-test suite for POST /v1/restrictive-practices/draft (case note drafter).

Calls run_drafter() directly — no server required.

10 scenarios covering:
  - Routine shift (no incident)
  - Physical restraint incident
  - Chemical restraint (PRN medication)
  - Injury observed
  - Safety hazard
  - Carer / family feedback
  - Overnight shift with behavioural event
  - Skill-building focused shift
  - Minimal / sparse transcript (tests draft_note gap detection)
  - Rich all-sections transcript (tests completeness)

Run:
    python scripts/test_draft_endpoint.py

See CURL EXAMPLES at the bottom for HTTP-level testing (server must be running on port 8084).
"""

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.schemas import DraftInput
from pipeline.drafter import run_drafter


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 1 — Routine community shift, no incidents
# Expected: describe/assisted/mood populated; all boolean flags False
# draft_note should be minimal or null (transcript is reasonably complete)
# ─────────────────────────────────────────────────────────────────────────────
SCENARIO_1_ROUTINE = DraftInput(
    case_note_id=uuid.UUID("d0000001-0000-0000-0000-000000000001"),
    client_id="client-demo-auth",
    worker_id="worker-grace-001",
    shift_date="12 May 2025",
    shift_time="9:00 AM - 1:00 PM",
    worker_position="Support Worker",
    transcript=(
        "Today I supported Marcus at his weekly community access shift. We started by going to "
        "Woolworths for grocery shopping. Marcus was in a great mood — he greeted the checkout "
        "staff by name and chose all his own items from the list without any prompting. After "
        "shopping we had lunch at the café next door. He ordered his own coffee independently "
        "using the menu. I gave him his midday medication reminder at 12:30pm and he took it "
        "straight away. No incidents occurred during the shift. He was calm and happy throughout. "
        "He said he really enjoyed the outing and asked if we could go to the library next week."
    ),
)

# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 2 — Physical restraint incident (prone hold, no BSP)
# Expected: behavioural_events populated; incident_occurred=True; any_concerns=True;
# injury_description present (red mark); draft_note flags urgency of BSP
# ─────────────────────────────────────────────────────────────────────────────
SCENARIO_2_PHYSICAL_RESTRAINT = DraftInput(
    case_note_id=uuid.UUID("d0000002-0000-0000-0000-000000000002"),
    client_id="client-demo-unauth",
    worker_id="worker-daniel-002",
    shift_date="17 Mar 2025",
    shift_time="2:00 PM - 8:00 PM",
    worker_position="Support Worker",
    transcript=(
        "Afternoon shift at Tom's group home. We had dinner together and I helped him with his "
        "evening hygiene routine. Around 4:45pm Tom became extremely agitated when the TV remote "
        "went missing. He started shouting and throwing cushions at the wall. I tried verbal "
        "de-escalation for about five minutes but he kept escalating. I ended up placing both "
        "hands on his shoulders and guided him firmly to the floor into a prone position and kept "
        "him there for about three minutes until he stopped struggling. After he calmed down I "
        "noticed a red mark on his left forearm. There was no behaviour support plan available "
        "on site. I'm not sure if what I did was correct. He settled by 6pm and ate dinner "
        "without any further problems."
    ),
)

# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 3 — PRN chemical restraint per approved BSP
# Expected: behavioural_events populated; medication_reminders_given=True;
# incident_occurred=True; any_concerns=True; mood reflects escalation then calm
# ─────────────────────────────────────────────────────────────────────────────
SCENARIO_3_CHEMICAL_RESTRAINT = DraftInput(
    case_note_id=uuid.UUID("d0000003-0000-0000-0000-000000000003"),
    client_id="client-demo-chem",
    worker_id="worker-priya-003",
    shift_date="2 May 2025",
    shift_time="7:00 AM - 1:00 PM",
    worker_position="Support Worker",
    transcript=(
        "Morning shift at William's residential facility. I supported him with his morning hygiene "
        "and breakfast — oats and fruit. He dressed independently and only needed prompting once "
        "for his teeth. Around 9:15am the day program bus was running late and William started "
        "getting very anxious — pacing, wringing his hands, asking me the same questions over and "
        "over. I tried verbal reassurance and his sensory supports, the weighted blanket and his "
        "favourite music, but by 9:30am he was screaming and hitting his own thighs. I checked "
        "his behaviour support plan — it authorises PRN quetiapine 25mg when de-escalation fails "
        "and self-injurious behaviour is present. I administered it at 9:40am as per the protocol. "
        "By 10:20am he had fully settled and we got to the day program without further incident. "
        "I gave him his regular morning medication as well. His mood was anxious during the "
        "escalation but calm and positive once he arrived at the day program."
    ),
)

# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 4 — Participant injury (fall, no restraint)
# Expected: any_injuries=True; injury_description populated; incident_occurred=True;
# safety_hazards_observed may be True (wet floor caused fall)
# ─────────────────────────────────────────────────────────────────────────────
SCENARIO_4_INJURY = DraftInput(
    case_note_id=uuid.UUID("d0000004-0000-0000-0000-000000000004"),
    client_id="client-demo-auth",
    worker_id="worker-nina-004",
    shift_date="8 May 2025",
    shift_time="10:00 AM - 4:00 PM",
    worker_position="Support Worker",
    transcript=(
        "I supported Lisa with her morning routine and a trip to the community garden. The shift "
        "started well — she was in a positive mood and keen to do some planting. At around 11am, "
        "while walking through the kitchen to get her gardening gloves, Lisa slipped on a wet patch "
        "near the sink. She fell and landed on her right knee. I helped her up straight away. "
        "She had a graze on her right knee — I cleaned it with antiseptic and applied a bandage "
        "from the first aid kit. I documented it and notified my supervisor by phone within the "
        "hour. Lisa said she was fine and wanted to continue, so we went to the garden as planned. "
        "She was a bit shaken at first but her mood recovered quickly once she was gardening. "
        "I made sure the wet floor was dried and reported the hazard to the facility manager. "
        "No further incidents for the rest of the shift."
    ),
)

# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 5 — Safety hazard observed (no injury)
# Expected: safety_hazards_observed=True; any_injuries=False; incident_occurred=False;
# what_needs_further_support mentions the hazard follow-up
# ─────────────────────────────────────────────────────────────────────────────
SCENARIO_5_SAFETY_HAZARD = DraftInput(
    case_note_id=uuid.UUID("d0000005-0000-0000-0000-000000000005"),
    client_id="client-demo-auth",
    worker_id="worker-aisha-005",
    shift_date="9 May 2025",
    shift_time="8:00 AM - 2:00 PM",
    worker_position="Support Worker",
    transcript=(
        "Morning support shift with David at his home. We completed his morning routine together — "
        "shower, dressing, and breakfast. David was in a good mood and chatty. During the shift I "
        "noticed that the handrail on the front steps is loose — it wobbles when you grab it. "
        "I pointed it out to David and made sure he used the wall for support when going up and "
        "down the steps today. I reported the loose handrail to the house coordinator by text and "
        "logged it in the maintenance book. No injuries occurred. We spent the afternoon doing "
        "a jigsaw puzzle together which David really enjoyed. Medication reminders were given at "
        "9am and 1pm and he took both without issues."
    ),
)

# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 6 — Carer / family feedback present
# Expected: carer_feedback populated; participant_comments present;
# no incidents; mood positive
# ─────────────────────────────────────────────────────────────────────────────
SCENARIO_6_CARER_FEEDBACK = DraftInput(
    case_note_id=uuid.UUID("d0000006-0000-0000-0000-000000000006"),
    client_id="client-demo-auth",
    worker_id="worker-sam-006",
    shift_date="10 May 2025",
    shift_time="12:00 PM - 6:00 PM",
    worker_position="Support Worker",
    transcript=(
        "Afternoon shift with Emma at her family home. We worked on her goal of cooking a meal "
        "independently — she made pasta with tomato sauce from scratch and only needed one prompt "
        "about when to add the pasta to the water. She was really proud of herself and said 'I "
        "did it all by myself' which was lovely to hear. Her mum was home for part of the shift "
        "and mentioned that Emma had been practicing setting the table every night this week and "
        "was doing it without being asked. Her mum also asked if we could work on making sandwiches "
        "next session as Emma wants to make her own school lunches. Emma's mood was great all "
        "afternoon — enthusiastic and confident. No concerns and no incidents."
    ),
)

# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 7 — Overnight / sleepover shift with behavioural event
# Expected: behavioural_events populated; incident_occurred=True; mood reflects
# unsettled overnight; what_needs_further_support mentions follow-up needed
# ─────────────────────────────────────────────────────────────────────────────
SCENARIO_7_OVERNIGHT = DraftInput(
    case_note_id=uuid.UUID("d0000007-0000-0000-0000-000000000007"),
    client_id="client-demo-unauth",
    worker_id="worker-james-007",
    shift_date="11 May 2025",
    shift_time="10:00 PM - 6:00 AM",
    worker_position="Support Worker",
    transcript=(
        "Overnight sleepover shift at the shared home with two participants. Both participants "
        "settled to bed by 10:30pm without issues. At around 1am Kevin got up and started "
        "pacing the hallway, muttering to himself. I spoke to him quietly and offered him a "
        "warm drink. He was agitated but responsive. After about 20 minutes of sitting together "
        "in the kitchen he settled and went back to bed. He slept through until 5:45am. The "
        "other participant slept through the night with no issues. I prepared breakfast for both "
        "of them before the morning shift worker arrived at 6am and did the handover. Kevin's "
        "nighttime agitation has been happening more frequently — I think the behaviour support "
        "team should be looped in. No injuries and no restraint used at any point."
    ),
)

# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 8 — Skill-building focused shift (high independence)
# Expected: practised_skill populated; participants_level_of_independence high;
# all boolean flags False; positive mood and outcomes
# ─────────────────────────────────────────────────────────────────────────────
SCENARIO_8_SKILL_BUILDING = DraftInput(
    case_note_id=uuid.UUID("d0000008-0000-0000-0000-000000000008"),
    client_id="client-demo-auth",
    worker_id="worker-alex-008",
    shift_date="12 May 2025",
    shift_time="9:00 AM - 3:00 PM",
    worker_position="Support Worker",
    transcript=(
        "Today's shift focused on building Sophie's public transport independence as part of her "
        "NDIS goal. We practiced catching the bus from her house to the shopping centre — two "
        "stops. She identified the correct bus from the timetable herself, tapped on with her "
        "Opal card without any prompting, and pressed the stop button at the right time. On the "
        "return trip she did it entirely independently — I followed behind without giving any "
        "cues. This was a huge milestone. She was so confident and excited to tell her support "
        "coordinator. We also did some grocery shopping at the centre where she compared prices "
        "on two different brands of cereal and chose the better value one. Her level of "
        "independence today was outstanding — the highest I've seen since we started working "
        "together. No concerns at all. She was bright and engaged the whole shift."
    ),
)

# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 9 — Minimal / sparse transcript
# Tests draft_note gap detection — most form fields cannot be extracted.
# Expected: most fields null; draft_note lists missing sections worker should complete
# ─────────────────────────────────────────────────────────────────────────────
SCENARIO_9_MINIMAL = DraftInput(
    case_note_id=uuid.UUID("d0000009-0000-0000-0000-000000000009"),
    client_id="client-demo-auth",
    worker_id="worker-rose-009",
    shift_date="13 May 2025",
    shift_time="2:00 PM - 6:00 PM",
    worker_position="Support Worker",
    transcript="Afternoon shift. All good. No issues.",
)

# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 10 — Rich all-sections transcript
# Covers all 6 sections explicitly. Tests completeness of extraction.
# Expected: almost all fields populated; draft_note minimal or null
# ─────────────────────────────────────────────────────────────────────────────
SCENARIO_10_RICH = DraftInput(
    case_note_id=uuid.UUID("d0000010-0000-0000-0000-000000000010"),
    client_id="client-demo-auth",
    worker_id="worker-lena-010",
    shift_date="14 May 2025",
    shift_time="8:00 AM - 4:00 PM",
    worker_position="Support Worker",
    transcript=(
        "Full-day shift with James at the community centre and his home. "
        "We started at 8am with his morning routine — shower, dressing, and breakfast. "
        "James needed one verbal prompt to brush his teeth but otherwise managed independently. "
        "At 10am we attended a woodworking class at the community centre as part of his NDIS "
        "goal to develop a practical hobby skill. James practiced using a hand saw to cut timber "
        "and sanded a small shelf he has been building over the last three sessions. The instructor "
        "noted he is showing strong spatial awareness and patience — both have improved significantly. "
        "James's level of independence at the class is moderate — he now sets up his own tools "
        "without prompting and only needs guidance on new techniques. "
        "His mood was excellent all day — enthusiastic at the class and chatty during lunch. "
        "No behavioural events occurred. He did not express any concerns and I had none either. "
        "What went really well today was the woodworking — James stayed focused for 90 minutes "
        "straight which is a new personal record for sustained attention. What could use more "
        "support is his time management in the morning routine — we ran 10 minutes late getting "
        "out the door. James commented he wants to bring the finished shelf to show his mum. "
        "I gave James his midday medication reminder at 12pm and he took it with lunch. "
        "No safety hazards were observed at the community centre or at home. No injuries. "
        "James's mum called during the shift to check how he was going and said he had been "
        "very excited about the woodworking class all week. No incidents occurred during the shift."
    ),
)


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

SCENARIOS = [
    ("SCENARIO 1  — Routine community shift (no incidents)",             SCENARIO_1_ROUTINE),
    ("SCENARIO 2  — Physical restraint incident (prone hold)",           SCENARIO_2_PHYSICAL_RESTRAINT),
    ("SCENARIO 3  — PRN chemical restraint per BSP",                     SCENARIO_3_CHEMICAL_RESTRAINT),
    ("SCENARIO 4  — Participant injury (fall + graze)",                  SCENARIO_4_INJURY),
    ("SCENARIO 5  — Safety hazard observed (loose handrail, no injury)", SCENARIO_5_SAFETY_HAZARD),
    ("SCENARIO 6  — Carer/family feedback present",                      SCENARIO_6_CARER_FEEDBACK),
    ("SCENARIO 7  — Overnight shift + nocturnal behavioural event",      SCENARIO_7_OVERNIGHT),
    ("SCENARIO 8  — Skill-building focused (high independence)",         SCENARIO_8_SKILL_BUILDING),
    ("SCENARIO 9  — Minimal transcript (gap detection test)",            SCENARIO_9_MINIMAL),
    ("SCENARIO 10 — Rich all-sections transcript (completeness test)",   SCENARIO_10_RICH),
]


def _print_result(label: str, result) -> None:
    w = 70
    print(f"\n{'='*w}")
    print(f"  {label}")
    print(f"{'='*w}")

    # Metadata
    print(f"  case_note_id      : {result.case_note_id}")

    # Section 1
    print(f"\n  [S1] describe     : {result.describe!r}")

    # Section 2
    print(f"  [S2] assisted     : {result.assisted!r}")
    print(f"       practised_skill          : {result.practised_skill!r}")
    print(f"       independence_level       : {result.participants_level_of_independence!r}")
    print(f"       observations             : {result.observations!r}")

    # Section 3
    print(f"  [S3] mood                    : {result.mood!r}")
    print(f"       behavioural_events       : {result.behavioural_events!r}")
    print(f"       any_concerns             : {result.any_concerns}")

    # Section 4
    print(f"  [S4] what_went_well          : {result.what_went_well!r}")
    print(f"       what_needs_further_support: {result.what_needs_further_support!r}")
    print(f"       participant_comments     : {result.participant_comments!r}")

    # Section 5
    print(f"  [S5] medication_reminders    : {result.medication_reminders_given}")
    print(f"       safety_hazards_observed  : {result.safety_hazards_observed}")
    print(f"       any_injuries             : {result.any_injuries}")
    if result.any_injuries:
        print(f"       injury_description       : {result.injury_description!r}")

    # Section 6
    print(f"  [S6] carer_feedback          : {result.carer_feedback!r}")
    print(f"       incident_occurred        : {result.incident_occurred}")

    # Draft quality note
    print(f"\n  [META] draft_note : {result.draft_note!r}")


async def main() -> None:
    passed = 0
    failed = 0

    for label, payload in SCENARIOS:
        print(f"\nRunning: {label}")
        try:
            result = await run_drafter(payload)
            _print_result(label, result)
            passed += 1
        except Exception as exc:
            print(f"\n  !! FAILED: {type(exc).__name__}: {exc}")
            failed += 1

    print(f"\n{'='*70}")
    print(f"  Results: {passed} passed, {failed} failed")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    asyncio.run(main())


# ─────────────────────────────────────────────────────────────────────────────
# CURL EXAMPLES (server running on port 8084)
# ─────────────────────────────────────────────────────────────────────────────
#
# SCENARIO 1 — Routine shift:
#
# curl -s -X POST http://localhost:8084/v1/restrictive-practices/draft \
#   -H "Content-Type: application/json" \
#   -d '{
#     "transcript": "Today I supported Marcus at grocery shopping. He was in a great mood and chose all his own items without prompting. I gave him his midday medication reminder. No incidents occurred.",
#     "worker_id": "worker-grace-001",
#     "client_id": "client-demo-auth",
#     "shift_date": "12 May 2025",
#     "shift_time": "9:00 AM - 1:00 PM",
#     "worker_position": "Support Worker"
#   }' | python -m json.tool
#
# SCENARIO 2 — Physical restraint:
#
# curl -s -X POST http://localhost:8084/v1/restrictive-practices/draft \
#   -H "Content-Type: application/json" \
#   -d '{
#     "transcript": "At 4:45pm Tom became extremely agitated. He started throwing cushions. I placed both hands on his shoulders and guided him firmly to the floor into a prone position for about three minutes. I noticed a red mark on his left forearm afterwards. No behaviour support plan was on site.",
#     "worker_id": "worker-daniel-002",
#     "client_id": "client-demo-unauth",
#     "shift_date": "17 Mar 2025",
#     "shift_time": "2:00 PM - 8:00 PM"
#   }' | python -m json.tool
#
# SCENARIO 9 — Minimal transcript (gap detection):
#
# curl -s -X POST http://localhost:8084/v1/restrictive-practices/draft \
#   -H "Content-Type: application/json" \
#   -d '{
#     "transcript": "Afternoon shift. All good. No issues.",
#     "worker_id": "worker-rose-009",
#     "client_id": "client-demo-auth",
#     "shift_date": "13 May 2025"
#   }' | python -m json.tool
#
# Then chain /draft output into /evaluate:
#
# curl -s -X POST http://localhost:8084/v1/restrictive-practices/evaluate \
#   -H "Content-Type: application/json" \
#   -d '{
#     "case_note_id": "d0000002-0000-0000-0000-000000000002",
#     "client_id": "client-demo-unauth",
#     "worker_id": "worker-daniel-002",
#     "behavioural_events": "At 4:45pm Tom became extremely agitated. I placed both hands on his shoulders and guided him to the floor in a prone position for three minutes. No BSP on site.",
#     "any_concerns": true,
#     "any_injuries": true,
#     "injury_description": "Red mark on left forearm.",
#     "incident_occurred": true
#   }' | python -m json.tool
