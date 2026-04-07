# Seed Development Data Script (scripts/seed_dev_data.py)
#
# Purpose: Populates the database with test tenants for local development
#
# Tenants created:
# 1. Sunshine Care Services (aaaaaaaa-...)
# 2. Metro Disability Support (bbbbbbbb-...)
# 3. Regional Living Assist (cccccccc-...)
# 4. SYSTEM (00000000-...) - for shared resources like NDIS templates
#
# Dependencies:
# - SQLAlchemy async engine
# - AsyncPG driver
# - PostgreSQL connection
#
# Usage:
# - Via Makefile: `make seed`
# - Directly: `python scripts/seed_dev_data.py`
#
# Function:
# - Connects to PostgreSQL asynchronously
# - Inserts deterministic UUIDs for test consistency
# - Uses INSERT...ON CONFLICT to be idempotent (safe to run multiple times)
# - Prints confirmation for each tenant seeded
