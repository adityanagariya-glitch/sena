# Tenant Isolation Integration Tests (shared/tests/test_tenant_isolation.py)
#
# Purpose: THE MOST CRITICAL tests in the codebase
# If any fail, tenant data is leaking - a legal violation under Australian privacy law
#
# Important: 
# - Tests run against REAL PostgreSQL database (not mocked)
# - RLS policies must be active and enforced
# - Uses restricted sena_app user (non-superuser) to verify RLS applies
#
# Test scenarios:
#
# 1. test_tenant_a_cannot_see_tenant_b_ocr_jobs
#    - Inserts OCR job as Tenant A
#    - Querys as Tenant B
#    - Expects: Tenant B sees 0 rows
#    - Verifies: RLS blocks cross-tenant access
#
# 2. test_system_documents_visible_to_all_tenants
#    - Inserts document chunk as SYSTEM tenant
#    - Queries as Tenant A and B
#    - Expects: Both see SYSTEM documents
#    - Verifies: Shared resource model works
#
# Test helpers:
# - _insert_as_tenant(): Sets app.current_tenant, inserts row, commits
# - _count_as_tenant(): Sets app.current_tenant, counts visible rows
#
# RLS mechanism tested:
# - app.current_tenant session variable
# - PostgreSQL RLS policies on tables
# - Restricted app user role enforcement
#
# This test suite validates the entire isolation strategy.
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
