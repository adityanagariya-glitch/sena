"""Tenant isolation integration tests.

These are the most critical tests in the entire codebase.
If any of these fail, it means tenant data is leaking — which is
a legal violation under Australian privacy law.

These tests run against a REAL Postgres database (not mocked).
RLS policies must be active and enforced.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .conftest import SYSTEM_TENANT_ID, TENANT_A_ID, TENANT_B_ID


@pytest.mark.asyncio
class TestTenantIsolation:
    """Verify that Row-Level Security prevents cross-tenant data access."""

    async def _insert_as_tenant(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        table: str,
        extra_columns: str = "",
        extra_values: str = "",
    ) -> uuid.UUID:
        """Insert a row into a tenant-scoped table and return its ID."""
        row_id = uuid.uuid4()
        await session.execute(
            text(f"SET app.current_tenant = '{tenant_id}'")
        )
        await session.execute(
            text(f"""
                INSERT INTO {table} (id, tenant_id{extra_columns})
                VALUES (:id, :tenant_id{extra_values})
            """),
            {"id": str(row_id), "tenant_id": str(tenant_id)},
        )
        await session.commit()
        return row_id

    async def _count_as_tenant(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        table: str,
    ) -> int:
        """Count rows visible to a specific tenant."""
        await session.execute(
            text(f"SET app.current_tenant = '{tenant_id}'")
        )
        result = await session.execute(text(f"SELECT count(*) FROM {table}"))
        row = result.first()
        return row[0] if row else 0

    @pytest.mark.asyncio
    async def test_tenant_a_cannot_see_tenant_b_ocr_jobs(
        self,
        test_session_factory: async_sessionmaker[AsyncSession],
        seed_tenants: None,
    ) -> None:
        """Tenant A's OCR jobs are invisible to Tenant B."""
        async with test_session_factory() as session:
            # Use the restricted app user (not superuser) for RLS to apply
            await session.execute(text("SET ROLE sena_app"))

            # Insert an OCR job as Tenant A
            await self._insert_as_tenant(
                session,
                TENANT_A_ID,
                "ocr_jobs",
                extra_columns=", document_type, status",
                extra_values=", 'drivers_licence', 'pending'",
            )

            # Query as Tenant B — should see zero of Tenant A's rows
            count_b = await self._count_as_tenant(session, TENANT_B_ID, "ocr_jobs")
            assert count_b == 0, (
                f"TENANT ISOLATION BREACH: Tenant B can see {count_b} rows "
                f"that belong to Tenant A in ocr_jobs"
            )

            # Query as Tenant A — should see their own row
            count_a = await self._count_as_tenant(session, TENANT_A_ID, "ocr_jobs")
            assert count_a >= 1, "Tenant A cannot see their own OCR jobs"

            # Reset role
            await session.execute(text("RESET ROLE"))

    @pytest.mark.asyncio
    async def test_system_documents_visible_to_all_tenants(
        self,
        test_session_factory: async_sessionmaker[AsyncSession],
        seed_tenants: None,
    ) -> None:
        """SYSTEM tenant documents (shared NDIS docs) are visible to all tenants."""
        async with test_session_factory() as session:
            await session.execute(text("SET ROLE sena_app"))

            # Insert a document chunk as SYSTEM tenant
            chunk_id = uuid.uuid4()
            await session.execute(
                text(f"SET app.current_tenant = '{SYSTEM_TENANT_ID}'")
            )
            await session.execute(
                text("""
                    INSERT INTO document_chunks
                        (id, tenant_id, document_id, chunk_index, content)
                    VALUES
                        (:id, :tenant_id, :doc_id, 0, 'NDIS Practice Standard 4.3.2')
                """),
                {
                    "id": str(chunk_id),
                    "tenant_id": str(SYSTEM_TENANT_ID),
                    "doc_id": str(uuid.uuid4()),
                },
            )
            await session.commit()

            # Tenant A should see the SYSTEM document
            await session.execute(
                text(f"SET app.current_tenant = '{TENANT_A_ID}'")
            )
            result = await session.execute(
                text("SELECT id FROM document_chunks WHERE id = :id"),
                {"id": str(chunk_id)},
            )
            assert result.first() is not None, (
                "Tenant A cannot see SYSTEM tenant document chunks. "
                "RLS policy for shared NDIS docs is broken."
            )

            # Tenant B should also see the SYSTEM document
            await session.execute(
                text(f"SET app.current_tenant = '{TENANT_B_ID}'")
            )
            result = await session.execute(
                text("SELECT id FROM document_chunks WHERE id = :id"),
                {"id": str(chunk_id)},
            )
            assert result.first() is not None, (
                "Tenant B cannot see SYSTEM tenant document chunks."
            )

            await session.execute(text("RESET ROLE"))

    @pytest.mark.asyncio
    async def test_tenant_a_cannot_see_tenant_b_document_chunks(
        self,
        test_session_factory: async_sessionmaker[AsyncSession],
        seed_tenants: None,
    ) -> None:
        """Tenant A's private document chunks are invisible to Tenant B."""
        async with test_session_factory() as session:
            await session.execute(text("SET ROLE sena_app"))

            # Insert a private document chunk as Tenant A
            chunk_id = uuid.uuid4()
            await session.execute(
                text(f"SET app.current_tenant = '{TENANT_A_ID}'")
            )
            await session.execute(
                text("""
                    INSERT INTO document_chunks
                        (id, tenant_id, document_id, chunk_index, content)
                    VALUES
                        (:id, :tenant_id, :doc_id, 0, 'Sunshine Care internal policy')
                """),
                {
                    "id": str(chunk_id),
                    "tenant_id": str(TENANT_A_ID),
                    "doc_id": str(uuid.uuid4()),
                },
            )
            await session.commit()

            # Tenant B should NOT see Tenant A's private documents
            await session.execute(
                text(f"SET app.current_tenant = '{TENANT_B_ID}'")
            )
            result = await session.execute(
                text("SELECT id FROM document_chunks WHERE id = :id"),
                {"id": str(chunk_id)},
            )
            assert result.first() is None, (
                "TENANT ISOLATION BREACH: Tenant B can see Tenant A's "
                "private document chunks"
            )

            await session.execute(text("RESET ROLE"))
