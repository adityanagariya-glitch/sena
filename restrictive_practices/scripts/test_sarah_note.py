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
    transcript="""Hey, it's Sarah logging my shift for Liam on Tuesday. I got to his place around 8:00 AM, and his mom headed out for work. Liam was a bit restless right from the start, didn't really want to eat his breakfast, but we managed to get some toast down. Around 9:30, we got ready to head to the community center for his art program. Getting him into the van was tough today. He kept trying to wander off down the driveway, so I had to physically guide him by the shoulders into the backseat. Once he was in, I put his safety harness on and used the buckle guard because last week he tried to unbuckle himself while we were driving. I also engaged the child locks on the doors just so he couldn't jump out at a red light.

The art program was mostly okay until about 11:45. Another participant accidentally bumped into Liam's table and knocked his crayons on the floor. Liam got really overwhelmed and started shouting, and then he started hitting his own head with a closed fist. I tried to redirect him verbally, but it wasn't working, so I had to step in. I grabbed his wrists and held his arms tightly down by his sides for maybe two or three minutes until he stopped trying to swing at his head. The program coordinator asked us to leave to give him some space, so we packed up early.

When we got back to his house around 12:30, he was still super agitated, pacing around the living room and throwing sofa cushions. I checked his protocol and gave him his PRN Diazepam at 1:00 PM to help bring his anxiety down so he wouldn't hurt himself. To give the medication time to kick in and reduce the sensory input, I guided him into his bedroom for some quiet time. He didn't want to stay in there and kept trying to open the door, so I had to hold the door closed from the outside for about ten minutes until he stopped crying and laid down on his bed.

After he woke up from his nap around 3:00 PM, his mood completely shifted. He was totally calm and smiling again. We spent the rest of the afternoon just watching his favorite cartoons on the iPad. I made sure to take the iPad away and lock it in the kitchen cabinet at 4:30 PM because his mom mentioned he gets too fixated on it before dinner.

I made him some pasta for dinner, which he ate all of. Dave arrived at 6:00 PM for the sleepover shift. I gave Dave a quick rundown of the incident at the art center and told him about the PRN. Everything was stable when I clocked out. End of note.""",
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
