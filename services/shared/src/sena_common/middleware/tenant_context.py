# Tenant Context Middleware (shared/src/sena_common/middleware/tenant_context.py)
#
# Purpose: THE MOST CRITICAL infrastructure for multi-tenancy
# Extracts tenant ID from request and propagates to database session for RLS
#
# ContextVar: _tenant_context_var
# - Stores TenantContext for request duration
# - Async-safe, thread-local storage
#
# TenantContext dataclass (immutable):
# - tenant_id: UUID of current tenant
# - user_id: User identifier (from header or JWT)
# - role: User role (from header or JWT)
#
# Helper functions:
# - get_tenant_context() - Returns TenantContext or raises
# - get_tenant_id() - Convenience: returns just the UUID
#
# TenantResolver protocol:
# Two implementations:
#
# 1. HeaderTenantResolver (Development)
#    - Reads X-Tenant-ID, X-User-ID, X-User-Role from headers
#    - NO authentication performed
#    - For local development/testing only
#    - Example header: X-Tenant-ID: aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa
#
# 2. JWTTenantResolver (Production)
#    - Not yet implemented
#    - Will validate JWT token
#    - Extract tenant and user info from claims
#    - TODO: Awaiting auth system specification
#
# TenantMiddleware:
# - Integrates resolver with FastAPI
# - Exempt paths: /health, /docs, /openapi.json, /redoc (no tenant required)
# - All other paths require valid tenant context
#
# Critical flow:
# 1. Request comes in with X-Tenant-ID header
# 2. HeaderTenantResolver.resolve() validates UUID format
# 3. TenantContext created and stored in ContextVar
# 4. Request proceeds with context available via get_tenant_context()
# 5. Database session creates with this tenant_id
# 6. PostgreSQL RLS policies filter to current tenant only
# 7. After response, context is cleared
