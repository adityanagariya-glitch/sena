# Database Package (shared/src/sena_common/db/__init__.py)
#
# Purpose: Database layer for all Sena AI services
#
# Contents:
# - base.py: SQLAlchemy declarative base, Tenant model, mixins
# - session.py: Async session factory with tenant context
#
# Features:
# - Async SQLAlchemy with asyncpg driver
# - Tenant context propagation for RLS
# - Connection pooling
# - Lifecycle management (startup/shutdown)
