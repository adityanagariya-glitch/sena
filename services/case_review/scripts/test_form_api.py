"""
Real-data API test — 8 scenarios covering all 4 verdict outcomes and all 5 practice types.

Data sourced from:
  - NDIS Commission Regulated Restrictive Practices Guide (ndiscommission.gov.au)
  - NDS Recognising Restrictive Practices Guide (nds.org.au)
  - ClinicComply NDIS Restrictive Practices Compliance Guide 2026

Run:
    python scripts/test_form_api.py

Alternatively hit the live API with curl (server must be running on port 8084):
    See CURL EXAMPLES at the bottom of this file.
"""

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.session import AsyncSessionLocal, create_tables
from models.schemas import CaseNoteInput
from pipeline.graph import run_pipeline

# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 1 — CLEAR (triage passes, no LLM cost)
# Routine community access shift, no incidents, no concerning behaviour.
# Expected: VerdictOutcome.CLEAR, alert_required=False
# ─────────────────────────────────────────────────────────────────────────────
SCENARIO_1_CLEAR = CaseNoteInput(
    case_note_id=uuid.UUID("a0000001-0000-0000-0000-000000000001"),
    client_id="client-demo-auth",
    worker_id="worker-grace-001",
    shift_date="14 Apr 2025",
    shift_time="9:00 AM - 3:00 PM",
    worker_position="Support Worker",
    describe=(
        "Supported Marcus with community access — attended weekly grocery shopping at "
        "Woolworths and visited the local library to return books and borrow new titles. "
        "Marcus chose his own groceries independently and interacted warmly with library staff."
    ),
    assisted="Grocery shopping, library visit, meal preparation (lunch at home — toasted sandwich).",
    practised_skill="Independent shopping using a written list. Marcus located 7 of 9 items without prompting.",
    participants_level_of_independence=(
        "High independence throughout. Required prompting once to stay on budget at checkout."
    ),
    observations=(
        "Marcus was engaged and communicative. No signs of distress. "
        "He initiated conversation with a library volunteer about gardening."
    ),
    mood="Positive and relaxed throughout the entire shift.",
    behavioural_events=None,
    any_concerns=False,
    what_went_well=(
        "Marcus successfully completed the full shopping list with minimal support. "
        "He expressed pride at the checkout — commented 'I did it myself'."
    ),
    what_needs_further_support="Continue practising budget management at checkout.",
    medication_reminders_given=True,
    safety_hazards_observed=False,
    any_injuries=False,
    carer_feedback="Marcus's mother noted he was cheerful when he arrived home and showed her the groceries.",
    incident_occurred=False,
)

# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 2 — UNAUTHORISED physical restraint (no BSP on file)
# Worker used prone hold during meltdown. No behaviour support plan exists.
# Source: NDIS Commission RRP Guide — physical restraint definition +
#         "hand-over-hand guidance preventing movement" example.
# Expected: VerdictOutcome.UNAUTHORISED, alert_required=True, 5 business days reporting
# client_id="client-demo-unauth" has no BSP seeded → UNAUTHORISED path
# ─────────────────────────────────────────────────────────────────────────────
SCENARIO_2_UNAUTHORISED_PHYSICAL = CaseNoteInput(
    case_note_id=uuid.UUID("a0000002-0000-0000-0000-000000000002"),
    client_id="client-demo-unauth",
    worker_id="worker-daniel-002",
    shift_date="17 Mar 2025",
    shift_time="2:00 PM - 8:00 PM",
    worker_position="Support Worker",
    describe=(
        "Afternoon and evening shift at Tom's group home. Shift included dinner preparation "
        "and a planned walk to the park."
    ),
    assisted="Dinner preparation (pasta), personal hygiene routine before bed.",
    practised_skill="Setting the dinner table independently.",
    participants_level_of_independence="Moderate. Tom completed hygiene steps with verbal prompts only.",
    observations=(
        "Tom became increasingly distressed after the TV remote was misplaced around 4:30 PM. "
        "Escalation began with vocalising and progressed to throwing cushions."
    ),
    mood=(
        "Calm at shift start. Distress escalated sharply around 4:30 PM when TV remote went missing. "
        "Settled by 6:00 PM after de-escalation."
    ),
    behavioural_events=(
        "At approximately 4:45 PM Tom became extremely agitated — shouting, throwing cushions, "
        "and attempting to overturn the coffee table. Verbal de-escalation was attempted for "
        "approximately five minutes without effect. I then placed both hands on Tom's shoulders "
        "and guided him firmly to the floor into a prone position, keeping him restrained for "
        "approximately three minutes until he stopped struggling. No behaviour support plan was "
        "available on site. Tom had a red mark on his left forearm after the hold."
    ),
    any_concerns=True,
    what_went_well="Tom ate a full dinner and completed his hygiene routine without incident afterwards.",
    what_needs_further_support=(
        "Behaviour support plan review required urgently. "
        "De-escalation training refresh needed for all house staff."
    ),
    medication_reminders_given=True,
    safety_hazards_observed=False,
    any_injuries=True,
    injury_description="Red mark observed on Tom's left forearm following physical intervention. No broken skin.",
    incident_occurred=True,
)

# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 3 — AUTHORISED chemical restraint (active BSP on file)
# PRN quetiapine administered for behavioural management per approved BSP.
# Source: NDIS Commission RRP Guide — "Bill's GP prescribed quetiapine PRN
#         to help reduce behaviour" as chemical restraint example.
# Expected: VerdictOutcome.AUTHORISED_USE, alert_required=False
# client_id="client-demo-chem" has Chemical Restraint BSP seeded
# ─────────────────────────────────────────────────────────────────────────────
SCENARIO_3_AUTHORISED_CHEMICAL = CaseNoteInput(
    case_note_id=uuid.UUID("a0000003-0000-0000-0000-000000000003"),
    client_id="client-demo-chem",
    worker_id="worker-priya-003",
    shift_date="2 May 2025",
    shift_time="7:00 AM - 1:00 PM",
    worker_position="Support Worker",
    describe=(
        "Morning shift at residential facility. Supported William with morning routine, "
        "breakfast, and scheduled community day program attendance."
    ),
    assisted="Morning hygiene, breakfast preparation (oats and fruit), transport to day program.",
    practised_skill="Self-directed dressing with minimal prompting.",
    participants_level_of_independence="Moderate — William dressed independently, required prompting for teeth brushing.",
    observations=(
        "William became increasingly anxious around 9:15 AM when the day program bus was running late. "
        "Pacing, hand-wringing, and repeated questioning observed. "
        "Verbal reassurance provided but anxiety continued to escalate."
    ),
    mood=(
        "Anxious and agitated from approximately 9:15 AM. "
        "Settled to calm within 40 minutes of PRN administration."
    ),
    behavioural_events=(
        "At 9:30 AM William's anxiety escalated to screaming and hitting his own thighs repeatedly. "
        "Verbal de-escalation and sensory supports (weighted blanket, preferred music) attempted "
        "for 10 minutes without sufficient effect. Checked behaviour support plan — PRN quetiapine "
        "25mg approved for use when de-escalation strategies fail and self-injurious behaviour "
        "is present. Administered as per protocol at 9:40 AM. William settled by 10:20 AM "
        "and travelled to day program without further incident."
    ),
    any_concerns=True,
    what_went_well=(
        "PRN protocol followed correctly. William was calm and participated in day program activities. "
        "Incident documented and reported to supervisor same day."
    ),
    what_needs_further_support="Review effectiveness of sensory supports as first-line strategy with behaviour support practitioner.",
    medication_reminders_given=True,
    safety_hazards_observed=False,
    any_injuries=False,
    carer_feedback="Day program reported William was calm on arrival and joined group activities.",
    incident_occurred=True,
)

# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 4 — UNAUTHORISED seclusion
# Participant locked alone in room unable to leave. No BSP.
# Source: NDIS Commission — "solitary confinement in a room where they are
#         prevented from leaving voluntarily"; "seclusion does not require locking".
# Expected: VerdictOutcome.UNAUTHORISED, alert_required=True
# client_id="client-demo-unauth" has no BSP
# ─────────────────────────────────────────────────────────────────────────────
SCENARIO_4_UNAUTHORISED_SECLUSION = CaseNoteInput(
    case_note_id=uuid.UUID("a0000004-0000-0000-0000-000000000004"),
    client_id="client-demo-unauth",
    worker_id="worker-james-004",
    shift_date="22 Apr 2025",
    shift_time="3:00 PM - 9:00 PM",
    worker_position="Support Worker",
    describe="Afternoon shift at supported accommodation. Two participants on site.",
    assisted="Afternoon tea, dinner, evening wind-down routine.",
    observations=(
        "Kevin became disruptive during shared TV time — shouting at the other participant "
        "and throwing the remote control."
    ),
    mood=(
        "Agitated from approximately 5:00 PM. Became verbally aggressive toward housemate. "
        "Calmer after 45 minutes alone in room."
    ),
    behavioural_events=(
        "At 5:10 PM Kevin threw the TV remote and began shouting at his housemate. "
        "To protect the other participant and de-escalate the situation, I guided Kevin to his bedroom "
        "and stood outside the door holding it closed so he could not leave for approximately "
        "45 minutes until he had calmed down. Kevin knocked on the door repeatedly asking to come out "
        "but I told him he needed to stay in there until he was calm. "
        "No behaviour support plan authorising this was in place."
    ),
    any_concerns=True,
    what_went_well="Kevin was calm by dinner time and ate without incident.",
    what_needs_further_support=(
        "Urgent BSP development required. Staff need de-escalation training. "
        "Housemate conflict management strategies needed."
    ),
    medication_reminders_given=False,
    safety_hazards_observed=False,
    any_injuries=False,
    incident_occurred=True,
)

# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 5 — AUTHORISED mechanical restraint (wheelchair lap belt)
# Lap belt used to prevent self-injurious elopement per approved BSP.
# Source: ClinicComply — "wheelchair lap belt used to prevent participant from
#         leaving wheelchair for behavioural reasons is a mechanical restraint".
# Expected: VerdictOutcome.AUTHORISED_USE, alert_required=False
# client_id="client-demo-mech" has Mechanical Restraint BSP seeded
# ─────────────────────────────────────────────────────────────────────────────
SCENARIO_5_AUTHORISED_MECHANICAL = CaseNoteInput(
    case_note_id=uuid.UUID("a0000005-0000-0000-0000-000000000005"),
    client_id="client-demo-mech",
    worker_id="worker-aisha-005",
    shift_date="9 May 2025",
    shift_time="10:00 AM - 4:00 PM",
    worker_position="Support Worker",
    describe=(
        "Community outing to the botanical gardens. Supported Rachel in her powered wheelchair. "
        "Attended sensory garden and café for lunch."
    ),
    assisted="Transport, wheelchair navigation, lunch ordering and payment.",
    practised_skill="Communicating food preferences at café using AAC device.",
    participants_level_of_independence="Low for mobility. High for communication and decision-making.",
    observations=(
        "Rachel was highly engaged with the sensory garden — reached out to touch plants repeatedly. "
        "Several attempts to lean forward sharply and potentially fall from the wheelchair observed."
    ),
    mood="Excited and engaged throughout. No signs of distress.",
    behavioural_events=(
        "During the outing Rachel made four attempts to lunge forward sharply from her wheelchair. "
        "As per her current behaviour support plan, the padded lap belt was applied after the second "
        "attempt to prevent injury from falling. The BSP authorises use of the lap belt during "
        "community outings when lunge behaviour is observed. Rachel did not show distress at the "
        "belt's application. Belt was checked for comfort every 30 minutes and removed during "
        "seated café lunch."
    ),
    any_concerns=False,
    what_went_well="Rachel communicated her food order independently using her AAC device for the first time in the community.",
    what_needs_further_support="Review lap belt use protocol with OT at next BSP review (due June 2025).",
    medication_reminders_given=True,
    safety_hazards_observed=False,
    any_injuries=False,
    incident_occurred=True,
)

# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 6 — UNAUTHORISED environmental restraint
# Participant's bedroom door locked at night without BSP authorisation.
# Source: NDIS Commission — "locking a door to prevent a person's access"
#         as environmental restraint example.
# Expected: VerdictOutcome.UNAUTHORISED, alert_required=True
# client_id="client-demo-unauth" has no BSP
# ─────────────────────────────────────────────────────────────────────────────
SCENARIO_6_UNAUTHORISED_ENVIRONMENTAL = CaseNoteInput(
    case_note_id=uuid.UUID("a0000006-0000-0000-0000-000000000006"),
    client_id="client-demo-unauth",
    worker_id="worker-sam-006",
    shift_date="28 Apr 2025",
    shift_time="10:00 PM - 6:00 AM",
    worker_position="Support Worker",
    describe="Overnight shift at residential home for two participants. Sleepover duty.",
    assisted="Evening medication, preparing breakfast ahead of morning shift.",
    mood="Participant was unsettled at the start of the night shift — restless and repeatedly leaving room.",
    behavioural_events=(
        "Diana repeatedly left her bedroom between 11:00 PM and 1:00 AM, wandering into the kitchen "
        "and attempting to use the stove unsafely. After the third incident I locked her bedroom door "
        "from the outside using the key kept in the staff office to prevent further unsafe access to "
        "the kitchen. Diana knocked on the door for approximately 20 minutes before settling. "
        "The door remained locked from 1:15 AM until 6:00 AM when the morning worker arrived. "
        "There is no behaviour support plan in place authorising restriction of Diana's room access."
    ),
    any_concerns=True,
    what_went_well="Diana slept through the remainder of the night once settled.",
    what_needs_further_support=(
        "Kitchen safety solution required — stove guard or key switch. "
        "Urgent BSP development needed. Incident must be reported."
    ),
    medication_reminders_given=True,
    safety_hazards_observed=True,
    any_injuries=False,
    carer_feedback="Morning worker briefed on overnight incident and door locking.",
    incident_occurred=True,
)

# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 7 — NO INCIDENT DETECTED (triage flags, evaluator clears)
# Medication administered for diagnosed condition, NOT behavioural management.
# Source: NDIS Commission — chemical restraint requires medication used "to
#         control behaviour, not to treat a diagnosed medical condition".
# Expected: VerdictOutcome.NO_INCIDENT, alert_required=False
# ─────────────────────────────────────────────────────────────────────────────
SCENARIO_7_NO_INCIDENT = CaseNoteInput(
    case_note_id=uuid.UUID("a0000007-0000-0000-0000-000000000007"),
    client_id="client-demo-auth",
    worker_id="worker-nina-007",
    shift_date="5 May 2025",
    shift_time="8:00 AM - 2:00 PM",
    worker_position="Support Worker",
    describe="Morning support shift. Assisted Robert with personal care, breakfast, and GP appointment.",
    assisted="Personal hygiene, breakfast, transport to GP clinic.",
    practised_skill="Self-administering morning medication with verbal reminders.",
    participants_level_of_independence="High for personal care. Requires support for medical appointments.",
    observations=(
        "Robert was slightly drowsy in the morning, consistent with his diagnosed epilepsy medication. "
        "No unusual behaviour or distress observed."
    ),
    mood="Calm and cooperative throughout. Slightly tired but not distressed.",
    behavioural_events=(
        "Robert experienced a mild focal seizure at 10:15 AM lasting approximately 90 seconds. "
        "Per his epilepsy management plan, I administered 5mg midazolam buccally as prescribed "
        "by his neurologist for seizure management. Robert recovered within 10 minutes and we "
        "proceeded to the GP appointment as planned. GP was informed of the seizure on arrival."
    ),
    any_concerns=True,
    what_went_well="Seizure management protocol followed correctly. GP was satisfied with response.",
    what_needs_further_support="Follow up with neurologist re: recent increase in seizure frequency.",
    medication_reminders_given=True,
    safety_hazards_observed=False,
    any_injuries=False,
    carer_feedback="GP reviewed seizure management plan and confirmed current medication is appropriate.",
    incident_occurred=True,
)

# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 8 — Multi-practice complex note (physical + environmental)
# Worker physically guided participant and locked fridge — both without BSP.
# Source: NDIS Commission — physical restraint ("using physical force to
#         restrict movement") + environmental restraint ("locking cupboards,
#         doors to limit access to items").
# Expected: VerdictOutcome.UNAUTHORISED, alert_required=True
# client_id="client-demo-unauth"
# ─────────────────────────────────────────────────────────────────────────────
SCENARIO_8_MULTI_PRACTICE = CaseNoteInput(
    case_note_id=uuid.UUID("a0000008-0000-0000-0000-000000000008"),
    client_id="client-demo-unauth",
    worker_id="worker-alex-008",
    shift_date="12 May 2025",
    shift_time="12:00 PM - 6:00 PM",
    worker_position="Support Worker",
    describe=(
        "Afternoon shift at group home. Three participants on site. "
        "Activities included lunch, free time, and afternoon walk."
    ),
    assisted="Lunch preparation, afternoon walk to local park.",
    practised_skill="Turn-taking board game after afternoon walk.",
    participants_level_of_independence="Variable — Jake requires close supervision during mealtimes.",
    observations=(
        "Jake became fixated on accessing the snack cupboard repeatedly throughout the shift, "
        "attempting to access it approximately eight times between 1:00 PM and 3:00 PM."
    ),
    mood=(
        "Agitated and persistent during the afternoon. Calmer during the walk to the park. "
        "Frustrated when redirected from the kitchen."
    ),
    behavioural_events=(
        "Jake made repeated attempts to access the kitchen snack cupboard throughout the afternoon. "
        "After the sixth attempt at 2:45 PM I locked the snack cupboard and the fridge with the "
        "padlocks kept in the staff drawer to prevent Jake from consuming excess food. "
        "At 3:30 PM Jake became very agitated when he found the fridge locked and began "
        "hitting the fridge door. I physically took hold of both of Jake's wrists and pulled "
        "him away from the fridge, holding him firmly by the wrists for approximately two minutes "
        "until he stopped pulling. Jake was then guided to the lounge room. "
        "No behaviour support plan is in place for either the fridge locking or the physical hold."
    ),
    any_concerns=True,
    what_went_well="Jake was calm during the park walk and participated in the board game.",
    what_needs_further_support=(
        "Urgent BSP development. Dietitian review of Jake's eating behaviours. "
        "Environmental modifications to kitchen access should be explored through BSP process."
    ),
    medication_reminders_given=False,
    safety_hazards_observed=False,
    any_injuries=False,
    incident_occurred=True,
)


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

SCENARIOS = [
    ("SCENARIO 1 — CLEAR (routine community shift)",                   SCENARIO_1_CLEAR),
    ("SCENARIO 2 — UNAUTHORISED physical restraint (prone hold)",      SCENARIO_2_UNAUTHORISED_PHYSICAL),
    ("SCENARIO 3 — AUTHORISED chemical restraint (PRN quetiapine)",    SCENARIO_3_AUTHORISED_CHEMICAL),
    ("SCENARIO 4 — UNAUTHORISED seclusion (held in room)",             SCENARIO_4_UNAUTHORISED_SECLUSION),
    ("SCENARIO 5 — AUTHORISED mechanical restraint (lap belt)",        SCENARIO_5_AUTHORISED_MECHANICAL),
    ("SCENARIO 6 — UNAUTHORISED environmental (bedroom locked all night)", SCENARIO_6_UNAUTHORISED_ENVIRONMENTAL),
    ("SCENARIO 7 — NO INCIDENT (seizure med, not behavioural)",        SCENARIO_7_NO_INCIDENT),
    ("SCENARIO 8 — MULTI-PRACTICE (physical + environmental, no BSP)", SCENARIO_8_MULTI_PRACTICE),
]


def _print_result(label: str, result) -> None:
    w = 65
    print(f"\n{'='*w}")
    print(f"  {label}")
    print(f"{'='*w}")
    print(f"  triage.flagged         : {result.triage.flagged}")
    if result.triage.action_summary:
        print(f"  triage.summary         : {result.triage.action_summary}")
    if result.evaluator:
        print(f"  evaluator.incident     : {result.evaluator.incident_detected}")
        print(f"  evaluator.category     : {result.evaluator.practice_category}")
        print(f"  evaluator.risk         : {result.evaluator.policy_violation_risk.value}")
        print(f"  evaluator.reporting    : {result.evaluator.reporting_required}")
        if result.evaluator.notification_timeframe:
            print(f"  evaluator.notify_within: {result.evaluator.notification_timeframe}")
    if result.cross_check:
        print(f"  cross_check.status     : {result.cross_check.authorisation_status.value}")
        print(f"  cross_check.bsp_id     : {result.cross_check.bsp_id}")
    print(f"  alert_required         : {result.alert_required}")


async def main() -> None:
    await create_tables()

    for label, note in SCENARIOS:
        print(f"\nRunning: {label}")
        async with AsyncSessionLocal() as db:
            result = await run_pipeline(note, db)
        _print_result(label, result)

    print(f"\n{'='*65}")
    print("  All scenarios complete.")
    print(f"{'='*65}\n")


if __name__ == "__main__":
    asyncio.run(main())


# ─────────────────────────────────────────────────────────────────────────────
# CURL EXAMPLES (server running on port 8084)
# ─────────────────────────────────────────────────────────────────────────────
#
# SCENARIO 2 — Unauthorised physical restraint:
#
# curl -s -X POST http://localhost:8084/v1/restrictive-practices/evaluate \
#   -H "Content-Type: application/json" \
#   -d '{
#     "case_note_id": "a0000002-0000-0000-0000-000000000002",
#     "client_id": "client-demo-unauth",
#     "worker_id": "worker-daniel-002",
#     "shift_date": "17 Mar 2025",
#     "shift_time": "2:00 PM - 8:00 PM",
#     "worker_position": "Support Worker",
#     "describe": "Afternoon and evening shift at Tom'\''s group home.",
#     "behavioural_events": "At approximately 4:45 PM Tom became extremely agitated. I then placed both hands on Tom'\''s shoulders and guided him firmly to the floor into a prone position, keeping him restrained for approximately three minutes. No behaviour support plan was available on site.",
#     "any_concerns": true,
#     "any_injuries": true,
#     "injury_description": "Red mark observed on Tom'\''s left forearm following physical intervention.",
#     "incident_occurred": true
#   }' | python -m json.tool
#
# SCENARIO 3 — Authorised chemical restraint:
#
# curl -s -X POST http://localhost:8084/v1/restrictive-practices/evaluate \
#   -H "Content-Type: application/json" \
#   -d '{
#     "case_note_id": "a0000003-0000-0000-0000-000000000003",
#     "client_id": "client-demo-chem",
#     "worker_id": "worker-priya-003",
#     "shift_date": "2 May 2025",
#     "shift_time": "7:00 AM - 1:00 PM",
#     "worker_position": "Support Worker",
#     "describe": "Morning shift at residential facility.",
#     "behavioural_events": "At 9:30 AM William'\''s anxiety escalated to screaming and self-injurious behaviour. Checked behaviour support plan — PRN quetiapine 25mg approved. Administered as per protocol at 9:40 AM. William settled by 10:20 AM.",
#     "any_concerns": true,
#     "medication_reminders_given": true,
#     "incident_occurred": true
#   }' | python -m json.tool
#
# SCENARIO 7 — No incident (seizure medication):
#
# curl -s -X POST http://localhost:8084/v1/restrictive-practices/evaluate \
#   -H "Content-Type: application/json" \
#   -d '{
#     "case_note_id": "a0000007-0000-0000-0000-000000000007",
#     "client_id": "client-demo-auth",
#     "worker_id": "worker-nina-007",
#     "shift_date": "5 May 2025",
#     "shift_time": "8:00 AM - 2:00 PM",
#     "worker_position": "Support Worker",
#     "describe": "Morning support shift. Assisted Robert with personal care and GP appointment.",
#     "behavioural_events": "Robert experienced a mild focal seizure at 10:15 AM. Per his epilepsy management plan, administered 5mg midazolam buccally as prescribed by his neurologist for seizure management.",
#     "any_concerns": true,
#     "medication_reminders_given": true,
#     "incident_occurred": true
#   }' | python -m json.tool
