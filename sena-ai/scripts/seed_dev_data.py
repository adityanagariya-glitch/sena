"""Seed development data — populates the database with test tenants and sample data.

Run with: make seed
Or manually: python scripts/seed_dev_data.py
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DATABASE_URL = "postgresql+asyncpg://sena:localdev@localhost:5432/sena_ai"

# Deterministic UUIDs for dev/test consistency
TENANTS = [
    {
        "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "name": "Sunshine Care Services",
        "slug": "sunshine-care",
    },
    {
        "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "name": "Metro Disability Support",
        "slug": "metro-disability",
    },
    {
        "id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
        "name": "Regional Living Assist",
        "slug": "regional-living",
    },
    {
        "id": "00000000-0000-0000-0000-000000000000",
        "name": "SYSTEM",
        "slug": "system",
    },
]


async def seed() -> None:
    engine = create_async_engine(DATABASE_URL)

    async with engine.begin() as conn:
        for tenant in TENANTS:
            await conn.execute(
                text("""
                    INSERT INTO tenants (id, name, slug, is_active)
                    VALUES (:id, :name, :slug, true)
                    ON CONFLICT (id) DO NOTHING
                """),
                tenant,
            )
            print(f"  Seeded tenant: {tenant['name']} ({tenant['id']})")

    await engine.dispose()
    print("\nDone. 4 tenants seeded (3 orgs + SYSTEM).")
    print("Use these tenant IDs in X-Tenant-ID headers for local testing.")


if __name__ == "__main__":
    asyncio.run(seed())
