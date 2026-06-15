"""Seed demo Behaviour Support Plans for client demo scenarios.

Creates BSPs covering all three pipeline result paths:
  - AUTHORISED_REVIEW  → client has an active BSP for the detected practice
  - UNAUTHORISED       → client has no matching BSP (alert_required=True)

Also seeds BSPs for the Sarah/Liam test fixture (test_sarah_note.py).

Run:
    python scripts/seed_demo.py

Idempotent — safe to re-run (uses INSERT ... ON CONFLICT DO UPDATE).
"""

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from db.session import AsyncSessionLocal, create_tables
from models.db import BehaviourSupportPlan

DEMO_BSPS = [
    # ── AUTHORISED path demos ────────────────────────────────────────────────
    {
        "client_id": "client-demo-auth",
        "practice_type": "Physical Restraint",
        "status": "Active",
        "approved_conditions": (
            "Physical guidance permitted only when participant poses immediate risk of self-harm. "
            "Must use minimal force, two-person assist preferred. Document immediately after use."
        ),
        "authorised_by": "Dr. A. Nguyen (Behaviour Support Practitioner)",
    },
    {
        "client_id": "client-demo-chem",
        "practice_type": "Chemical Restraint",
        "status": "Active",
        "approved_dosage": "Diazepam 5mg PRN, max 1 dose per 4 hours",
        "approved_conditions": (
            "Administer only when participant exhibits severe agitation with risk of harm. "
            "Must be prescribed by treating psychiatrist. Record time, dose, and outcome."
        ),
        "authorised_by": "Dr. B. Patel (Treating Psychiatrist)",
    },
    {
        "client_id": "client-demo-mech",
        "practice_type": "Mechanical Restraint",
        "status": "Active",
        "approved_conditions": (
            "Lap safety harness approved for vehicle transport only. "
            "Must be used in conjunction with standard seatbelt. Not for behaviour management."
        ),
        "authorised_by": "Occupational Therapist — S. Kumar",
    },
    # ── UNAUTHORISED path demo (no BSP inserted — leave empty) ───────────────
    # client-demo-unauth has NO BSP → every detected practice = UNAUTHORISED

    # ── Sarah / Liam test fixture ─────────────────────────────────────────────
    {
        "client_id": "liam-001",
        "practice_type": "Physical Restraint",
        "status": "Active",
        "approved_conditions": (
            "Brief physical guidance (wrist hold, arm guide) approved to prevent self-injurious "
            "behaviour. Max duration 3 minutes. Requires two staff to be present where possible."
        ),
        "authorised_by": "Behaviour Support Practitioner — T. Walsh",
    },
    {
        "client_id": "liam-001",
        "practice_type": "Chemical Restraint",
        "status": "Active",
        "approved_dosage": "Diazepam 5mg PRN",
        "approved_conditions": (
            "PRN Diazepam approved for acute anxiety episodes per psychiatrist order. "
            "Administer only when non-pharmacological strategies have failed."
        ),
        "authorised_by": "Dr. C. Reynolds (Psychiatrist)",
    },
    {
        "client_id": "liam-001",
        "practice_type": "Environmental Restraint",
        "status": "Active",
        "approved_conditions": (
            "Child lock on vehicle doors approved for road safety. "
            "iPad access restriction after 4:30pm approved by family — not a behaviour management tool."
        ),
        "authorised_by": "Support Coordinator — M. Tran",
    },
]


async def main() -> None:
    print("=== Seeding Demo Behaviour Support Plans ===")
    await create_tables()

    async with AsyncSessionLocal() as db:
        for bsp in DEMO_BSPS:
            existing = await db.execute(
                select(BehaviourSupportPlan).where(
                    BehaviourSupportPlan.client_id == bsp["client_id"],
                    BehaviourSupportPlan.practice_type == bsp["practice_type"],
                )
            )
            row = existing.scalar_one_or_none()
            if row:
                row.status = bsp.get("status", "Active")
                row.approved_dosage = bsp.get("approved_dosage")
                row.approved_conditions = bsp.get("approved_conditions")
                row.authorised_by = bsp.get("authorised_by")
                print(f"  Updated:  {bsp['client_id']} / {bsp['practice_type']}")
            else:
                db.add(BehaviourSupportPlan(
                    id=str(uuid.uuid4()),
                    client_id=bsp["client_id"],
                    practice_type=bsp["practice_type"],
                    status=bsp.get("status", "Active"),
                    approved_dosage=bsp.get("approved_dosage"),
                    approved_conditions=bsp.get("approved_conditions"),
                    authorised_by=bsp.get("authorised_by"),
                ))
                print(f"  Inserted: {bsp['client_id']} / {bsp['practice_type']}")

        await db.commit()

    print(f"\nSeeded {len(DEMO_BSPS)} BSPs.")
    print("\nDemo client IDs:")
    print("  client-demo-auth   → Physical Restraint (Active BSP) → AUTHORISED_REVIEW")
    print("  client-demo-chem   → Chemical Restraint (Active BSP) → AUTHORISED_REVIEW")
    print("  client-demo-mech   → Mechanical Restraint (Active BSP) → AUTHORISED_REVIEW")
    print("  client-demo-unauth → No BSP → UNAUTHORISED (alert_required=true)")
    print("  liam-001           → Physical + Chemical + Environmental BSPs")


if __name__ == "__main__":
    asyncio.run(main())
