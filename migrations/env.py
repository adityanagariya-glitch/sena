# Alembic Environment Configuration (migrations/env.py)
#
# Purpose: Configures Alembic to run async database migrations with SQLAlchemy
#
# Key Functions:
# 1. run_migrations_offline() - Runs migrations without connecting to DB
# 2. run_migrations_online() - Connects to PostgreSQL and runs migrations
# 3. run_async_migrations() - Uses asyncio to handle async SQLAlchemy engine
#
# Workflow:
# - Reads Alembic config from alembic.ini
# - Uses Base.metadata from sena_common.db.base (SQLAlchemy declarative models)
# - Creates async_engine using asyncpg driver
# - Determines if running offline or online and executes accordingly
# - Automatically generates migrations from model changes
#
# Used by: 'make migrate' command
