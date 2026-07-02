"""Test Sarah's shift note for Liam through the full pipeline."""
import asyncio, sys, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.session import AsyncSessionLocal, create_tables
from models.schemas import CaseNoteInput
from pipeline.graph import run_pipeline

NOTE = CaseNoteInput(
    case_note_id=uuid.uuid4(),
    client_id="liam-001",
    worker_id="sarah-001",
    shift_date="Tuesday",
    shift_time="8:00 AM - 6:00 PM",
    worker_position="Support Worker",
    describe=(
        "Sarah's shift for Liam. Arrived 8:00 AM, mom left for work. "
        "Attended art program at community centre 9:30 AM-12:30 PM. "
        "Returned home early due to behavioural incident. Dave arrived 6:00 PM for sleepover shift."
    ),
    assisted=(
        "Breakfast (toast). Transport to and from community centre art program. "
        "Afternoon cartoons on iPad. Pasta dinner prepared and served."
    ),
    practised_skill="Community participation — art program at community centre.",
    participants_level_of_independence=(
        "Liam required full physical assistance with transport and significant prompting throughout."
    ),
    observations=(
        "Getting Liam into the van was difficult — he kept trying to wander off down the driveway. "
        "I physically guided him by the shoulders into the backseat. "
        "Applied safety harness and buckle guard (used last week due to unbuckling during transit). "
        "Engaged child locks on doors to prevent him jumping out at red lights."
    ),
    mood=(
        "Restless and not wanting to eat at start of shift. "
        "Overwhelmed and agitated at art program after another participant bumped his table. "
        "Still agitated on return home — pacing, throwing sofa cushions. "
        "Completely calm and smiling after nap at 3:00 PM."
    ),
    behavioural_events=(
        "At 11:45 at art program, Liam became overwhelmed, started shouting then hitting his own "
        "head with a closed fist. Verbal redirection failed. I grabbed his wrists and held his arms "
        "tightly down by his sides for approximately two to three minutes until he stopped. "
        "Program coordinator asked us to leave early.\n"
        "Back home at 12:30, Liam still agitated. Checked protocol and administered PRN Diazepam "
        "at 1:00 PM to reduce anxiety and prevent self-harm. "
        "Guided him to bedroom for quiet time to allow medication to take effect. "
        "He kept trying to open the bedroom door, so I held the door closed from the outside "
        "for approximately ten minutes until he stopped crying and lay down."
    ),
    any_concerns=True,
    what_went_well="Liam ate all his pasta at dinner. Calm and happy for the rest of the afternoon after nap.",
    what_needs_further_support=(
        "BSP review recommended for physical restraint and seclusion protocols. "
        "PRN Diazepam use documented — requires review against chemical restraint authorisation."
    ),
    participant_comments="N/A — non-verbal during incident.",
    medication_reminders_given=True,
    safety_hazards_observed=False,
    any_injuries=False,
    injury_description=None,
    carer_feedback=(
        "At 4:30 PM took iPad away and locked it in the kitchen cabinet as per mom's instruction "
        "— Liam gets too fixated on it before dinner (environmental restraint — access restriction). "
        "Handover to Dave at 6:00 PM — briefed on art centre incident and PRN use."
    ),
    incident_occurred=True,
)

async def main():
    await create_tables()
    async with AsyncSessionLocal() as db:
        result = await run_pipeline(NOTE, db)

    print("\n" + "="*60)
    print("  PIPELINE RESULT — Sarah / Liam shift note")
    print("="*60)
    print(f"\n  TRIAGE")
    print(f"  flagged        : {result.triage.flagged}")
    print(f"  summary        : {result.triage.action_summary}")

    if result.evaluator:
        print(f"\n  EVALUATOR")
        print(f"  incident       : {result.evaluator.incident_detected}")
        print(f"  category       : {result.evaluator.practice_category}")
        print(f"  risk           : {result.evaluator.policy_violation_risk.value}")
        print(f"  action         : {result.evaluator.action_summary}")
        print(f"  reasoning      :\n    {result.evaluator.reasoning}")

    if result.cross_check:
        print(f"\n  CROSS-CHECK")
        print(f"  status         : {result.cross_check.authorisation_status.value}")
        print(f"  bsp_id         : {result.cross_check.bsp_id}")
        print(f"  notes          : {result.cross_check.notes}")

    print(f"\n  ALERT REQUIRED : {result.alert_required}")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(main())
