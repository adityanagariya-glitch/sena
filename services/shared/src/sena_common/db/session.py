# Database Session Factory (shared/src/sena_common/db/session.py)
#
# Purpose: Creates async SQLAlchemy sessions with tenant context for RLS enforcement
#
# Key functions:
# 1. init_engine(database_url) - Initialize async engine once at app startup
#    - Creates connection pool (10 concurrent + 20 overflow)
#    - Enables pool_pre_ping for dead connection detection
#    - Returns AsyncEngine
#
# 2. close_engine() - Cleanup at app shutdown
#    - Disposes all connections
#
# 3. get_session(tenant_id) - Get session WITH tenant context
#    - Sets PostgreSQL session variable: app.current_tenant = tenant_id
#    - Used for all tenant-scoped queries
#    - RLS policies filter rows based on this variable
#    - Commits on success, rolls back on exception
#
# 4. get_session_no_tenant() - Get session WITHOUT tenant context
#    - Used only for: health checks, migrations, system operations
#    - Cannot access tenant-scoped tables (RLS will block queries)
#
# Workflow:
# - FastAPI middleware extracts tenant_id from X-Tenant-ID header
# - Middleware calls get_session(tenant_id)
# - Session immediately executes SET app.current_tenant = <uuid>
# - Query executes with RLS policies enforcing isolation
# - Middleware commits or rolls back after response
