-- Row-Level Security (RLS) Policies (scripts/setup_rls.sql)
--
-- Purpose: Enforces tenant isolation at the database layer
-- Runs after tables are created via Alembic migrations
--
-- How it works:
# 1. Each table has one or more RLS policies
# 2. Policies filter rows based on current_setting('app.current_tenant')
# 3. Application MUST set this variable before each query
# 4. Even if app code forgets WHERE tenant_id clause, DB filters rows
# 5. Superusers bypass RLS - that's why sena_app is not a superuser
#
# Tables protected:
# - ocr_jobs: Strict isolation (can only see own tenant's jobs)
# - document_chunks: Partial isolation (can see own + SYSTEM tenant chunks)
#   This allows all tenants to access shared NDIS policy documents
# - tenants: No RLS (system table, managed at app layer)
#
# Implementation:
# - Uses PostgreSQL POLICY system
# - Policies applied with ALTER TABLE...ENABLE ROW LEVEL SECURITY
# - FORCE ROW LEVEL SECURITY ensures policies cannot be disabled except by superuser
#
# Used by: Application middleware (sena_common/middleware/tenant_context.py)
# Sets: SET app.current_tenant = '<uuid>' before executing queries
