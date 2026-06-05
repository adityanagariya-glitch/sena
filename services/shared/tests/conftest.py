# Shared Test Configuration (shared/tests/conftest.py)
#
# Purpose: Centralized pytest fixtures for all Sena AI services
#
# Test database setup:
# - Create test database engine with PostgreSQL + pgvector
# - Initialize tables via SQLAlchemy Base metadata
# - Create restricted app user for RLS testing
#
# Test tenants (deterministic UUIDs):
# - TENANT_A_ID: aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa (Sunshine Care)
# - TENANT_B_ID: bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb (Metro Disability)
# - SYSTEM_TENANT_ID: 00000000-0000-0000-0000-000000000000 (SYSTEM)
#
# Fixtures provided:
# 1. anyio_backend() - Sets asyncio as async test backend
# 2. test_engine() - Test database engine (session scope)
# 3. test_session_factory() - Session factory bound to test engine
# 4. seed_tenants() - Inserts test tenants into database
#
# Database:
# - URL: postgresql+asyncpg://sena:localdev@localhost:5432/sena_ai_test
# - Can override with TEST_DATABASE_URL environment variable
#
# RLS testing:
# - Creates sena_app restricted user (non-superuser)
# - Ensures RLS policies are properly tested
#
# Usage:
# Tests inherit fixtures automatically from conftest.py
# Example: @pytest.fixture def my_session(test_session_factory) -> ...
                "b_id": str(TENANT_B_ID),
                "sys_id": str(SYSTEM_TENANT_ID),
            },
        )
        await session.commit()
