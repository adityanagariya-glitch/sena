-- Row-Level Security (RLS) Policies
-- Run AFTER tables are created (via Alembic migrations)
--
-- These policies enforce tenant isolation at the database level.
-- Even if application code has a bug and omits a WHERE tenant_id clause,
-- the database will filter rows based on the session variable.
--
-- USAGE: The application must SET app.current_tenant = '<uuid>' on each
-- connection/session before executing queries. See shared/src/sena_common/db/session.py

-- ============================================================
-- OCR Jobs — strict tenant isolation
-- ============================================================
DO $$
BEGIN
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'ocr_jobs') THEN
        ALTER TABLE ocr_jobs ENABLE ROW LEVEL SECURITY;
        ALTER TABLE ocr_jobs FORCE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS tenant_isolation ON ocr_jobs;
        CREATE POLICY tenant_isolation ON ocr_jobs
            USING (tenant_id = current_setting('app.current_tenant', true)::uuid);

        DROP POLICY IF EXISTS tenant_isolation_insert ON ocr_jobs;
        CREATE POLICY tenant_isolation_insert ON ocr_jobs
            FOR INSERT
            WITH CHECK (tenant_id = current_setting('app.current_tenant', true)::uuid);
    END IF;
END $$;

-- ============================================================
-- Document Chunks — allows SYSTEM tenant for shared NDIS docs
-- ============================================================
DO $$
BEGIN
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'document_chunks') THEN
        ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY;
        ALTER TABLE document_chunks FORCE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS tenant_isolation ON document_chunks;
        CREATE POLICY tenant_isolation ON document_chunks
            USING (
                tenant_id = current_setting('app.current_tenant', true)::uuid
                OR tenant_id = '00000000-0000-0000-0000-000000000000'::uuid
            );

        DROP POLICY IF EXISTS tenant_isolation_insert ON document_chunks;
        CREATE POLICY tenant_isolation_insert ON document_chunks
            FOR INSERT
            WITH CHECK (
                tenant_id = current_setting('app.current_tenant', true)::uuid
                OR tenant_id = '00000000-0000-0000-0000-000000000000'::uuid
            );
    END IF;
END $$;

-- ============================================================
-- Tenants table — no RLS (tenants are system-level, not scoped)
-- ============================================================
-- Intentionally no RLS on the tenants table itself.
-- Access control for tenant management is handled at the application layer.
