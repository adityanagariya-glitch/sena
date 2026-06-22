"""reconcile drifted tenant_id columns on rp tables (idempotent drift repair)

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-18

Background:
  Migration 0002 already defines tenant_id on both behaviour_support_plans and
  rp_case_note_runs. However, some deployed databases had these tables created
  from an OLDER model (before tenant_id existed, e.g. via Base.metadata.create_all)
  without 0002 ever running against them, so the column is missing. Every pipeline
  request then fails:
      - /evaluate audit insert  -> column "tenant_id" of "rp_case_note_runs" missing
      - cross_check_step query   -> column "tenant_id" of "behaviour_support_plans" missing

  This migration reconciles that drift. It is intentionally IDEMPOTENT (IF NOT
  EXISTS guards) so it is a no-op on correctly-migrated databases and a repair on
  drifted ones — no manual SQL required on future deploys.

  RLS is deliberately NOT touched here: the drifted production tables run without
  the tenant-isolation policies and inserts succeed. Enabling FORCE RLS without the
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
    # ── rp_case_note_runs ─────────────────────────────────────────────────────
    op.execute(
        "ALTER TABLE rp_case_note_runs "
        "ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_rp_runs_tenant "
        "ON rp_case_note_runs (tenant_id);"
    )

    # ── behaviour_support_plans ───────────────────────────────────────────────
    op.execute(
        "ALTER TABLE behaviour_support_plans "
        "ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(100);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bsp_tenant "
        "ON behaviour_support_plans (tenant_id);"
    )


def downgrade() -> None:
    # Forward-only reconcile; do not drop the columns on downgrade since 0002
    # (the prior head) also expects tenant_id to exist on both tables.
    op.execute("DROP INDEX IF EXISTS ix_rp_runs_tenant;")
    op.execute("DROP INDEX IF EXISTS ix_bsp_tenant;")
