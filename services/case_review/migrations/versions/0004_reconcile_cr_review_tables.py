"""reconcile missing cr_* review tables (idempotent drift repair)

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-18

Background:
  Migration 0001 creates the four cr_* review tables. However, some deployed
  databases never had 0001 applied (the schema was bootstrapped outside alembic,
  e.g. a partial manual run / create_all), so these tables are simply ABSENT:
      cr_rolling_summary, cr_review_session, cr_incident_draft, cr_review_audit_log
  Any review-session / rolling-summary / incident-draft endpoint then 500s with
  asyncpg UndefinedTableError.

  This migration reconciles that drift. It is intentionally IDEMPOTENT
  (CREATE TABLE / CREATE INDEX ... IF NOT EXISTS) so it is a no-op on databases
  that already have these tables from 0001, and a repair on drifted ones.

  RLS is deliberately NOT enabled here. 0001 enables FORCE ROW LEVEL SECURITY with
  a policy keyed on current_setting('app.current_tenant'), but the application code
  never sets that GUC — on the drifted production DB the existing rp_* tables run
  WITHOUT RLS for exactly this reason. Enabling FORCE RLS here would block every
  read/write. Tenant isolation is enforced in application code. Re-enabling RLS is
  a separate, deliberate change that must land together with app code that sets
  app.current_tenant per connection.

  Order matters: cr_review_session is created before cr_incident_draft and
  cr_review_audit_log, which carry FKs to it.
"""

from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── cr_rolling_summary ────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS cr_rolling_summary (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL,
            staff_id UUID NOT NULL,
            client_id UUID NOT NULL,
            summary_text TEXT NOT NULL DEFAULT '',
            metadata JSON NOT NULL DEFAULT '{}',
            processed_note_ids VARCHAR[] NOT NULL DEFAULT '{}',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_rolling_summary_pair UNIQUE (tenant_id, staff_id, client_id)
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_cr_rolling_summary_tenant ON cr_rolling_summary (tenant_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_cr_rolling_summary_staff  ON cr_rolling_summary (staff_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_cr_rolling_summary_client ON cr_rolling_summary (client_id);")

    # ── cr_review_session (referenced by the two tables below) ─────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS cr_review_session (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL,
            staff_id UUID,
            client_id UUID,
            drafted_case_note_id VARCHAR(128),
            raw_paragraph TEXT NOT NULL DEFAULT '',
            classified_fields JSON NOT NULL DEFAULT '{}',
            missing_fields JSON NOT NULL DEFAULT '[]',
            flags JSON NOT NULL DEFAULT '{}',
            incident_detected BOOLEAN NOT NULL DEFAULT false,
            status VARCHAR(30) NOT NULL DEFAULT 'input',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_cr_review_session_tenant  ON cr_review_session (tenant_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_cr_review_session_staff   ON cr_review_session (staff_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_cr_review_session_client  ON cr_review_session (client_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_cr_review_session_note_id ON cr_review_session (drafted_case_note_id);")

    # ── cr_incident_draft (FK -> cr_review_session) ───────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS cr_incident_draft (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL,
            review_session_id UUID REFERENCES cr_review_session(id) ON DELETE SET NULL,
            autofill_source JSON NOT NULL DEFAULT '{}',
            draft_fields JSON NOT NULL DEFAULT '{}',
            staff_confirmed BOOLEAN NOT NULL DEFAULT false,
            status VARCHAR(30) NOT NULL DEFAULT 'draft',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_cr_incident_draft_tenant  ON cr_incident_draft (tenant_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_cr_incident_draft_session ON cr_incident_draft (review_session_id);")

    # ── cr_review_audit_log (FK -> cr_review_session) ─────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS cr_review_audit_log (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL,
            review_session_id UUID NOT NULL REFERENCES cr_review_session(id) ON DELETE RESTRICT,
            actor_user_id UUID,
            action VARCHAR(60) NOT NULL,
            payload JSON NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_cr_audit_log_tenant  ON cr_review_audit_log (tenant_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_cr_audit_log_session ON cr_review_audit_log (review_session_id);")


def downgrade() -> None:
    # Forward-only reconcile; do not drop tables on downgrade since 0001 (an
    # ancestor revision) also expects these tables to exist.
    pass
