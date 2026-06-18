"""reconcile rp_case_note_runs.tenant_id (idempotent drift repair)

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-18

Background:
  Migration 0002 already defines rp_case_note_runs.tenant_id. However, some
  deployed databases had the table created from an OLDER model (before tenant_id
  existed) without 0002 ever running against them, so their table is missing the
  column — every /evaluate INSERT then fails with:
      column "tenant_id" of relation "rp_case_note_runs" does not exist

  This migration reconciles that drift. It is intentionally IDEMPOTENT (IF NOT
  EXISTS guards) so it is a no-op on correctly-migrated databases and a repair on
  drifted ones — no manual SQL required on future deploys.

  RLS is deliberately NOT touched here: the drifted production table runs without
  the tenant-isolation policy and inserts succeed. Enabling FORCE RLS without the
  app setting `app.current_tenant` on every connection would block writes, so RLS
  reconciliation is left to a separate, deliberate migration.
"""

from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add the column only where it is missing (no-op on fresh DBs from 0002).
    op.execute(
        "ALTER TABLE rp_case_note_runs "
        "ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100);"
    )
    # Index to match the model's index=True on tenant_id.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_rp_runs_tenant "
        "ON rp_case_note_runs (tenant_id);"
    )


def downgrade() -> None:
    # Forward-only reconcile; do not drop the column on downgrade since 0002
    # (the prior head) also expects tenant_id to exist.
    op.execute("DROP INDEX IF EXISTS ix_rp_runs_tenant;")
