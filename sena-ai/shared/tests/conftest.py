"""Test fixtures for all Sena AI services.

Provides:
- Test database with RLS policies
- Test tenants (Tenant A, Tenant B, SYSTEM)
- Async HTTP client for FastAPI testing
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Tenant UUIDs — deterministic for test assertions
TENANT_A_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TENANT_B_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
SYSTEM_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")

# Database URL for tests (override with TEST_DATABASE_URL env var)
TEST_DATABASE_URL = "postgresql+asyncpg://sena:localdev@localhost:5432/sena_ai_test"


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
async def test_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Create a test database engine."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)

    # Create tables and RLS policies
    async with engine.begin() as conn:
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "pgvector"'))
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))

        # Import all models so Base.metadata has them
        from sena_common.db.base import Base

        await conn.run_sync(Base.metadata.create_all)

        # Create restricted app user for RLS testing
        await conn.execute(text("""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sena_app') THEN
                    CREATE ROLE sena_app LOGIN PASSWORD 'localdev';
                END IF;
            END $$
        """))
        await conn.execute(text("GRANT ALL ON ALL TABLES IN SCHEMA public TO sena_app"))
        await conn.execute(text("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO sena_app"))

    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
async def test_session_factory(
    test_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Create session factory bound to test engine."""
    return async_sessionmaker(bind=test_engine, expire_on_commit=False)


@pytest.fixture
async def seed_tenants(
    test_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Insert test tenants if they don't exist."""
    async with test_session_factory() as session:
        # Check if tenants already exist
        result = await session.execute(
            text("SELECT id FROM tenants WHERE id = :id"),
            {"id": str(TENANT_A_ID)},
        )
        if result.first() is not None:
            return

        await session.execute(
            text("""
                INSERT INTO tenants (id, name, slug, is_active)
                VALUES
                    (:a_id, 'Sunshine Care Services', 'sunshine-care', true),
                    (:b_id, 'Metro Disability Support', 'metro-disability', true),
                    (:sys_id, 'SYSTEM', 'system', true)
                ON CONFLICT (id) DO NOTHING
            """),
            {
                "a_id": str(TENANT_A_ID),
                "b_id": str(TENANT_B_ID),
                "sys_id": str(SYSTEM_TENANT_ID),
            },
        )
        await session.commit()
