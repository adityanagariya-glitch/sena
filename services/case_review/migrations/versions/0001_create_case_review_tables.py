"""create case review tables

Revision ID: 0001
Revises:
Create Date: 2026-04-23

Tables created:
  - cr_rolling_summary  (UNIQUE tenant+staff+client)
  - cr_review_session
  - cr_incident_draft
  - cr_review_audit_log

RLS policies scoped by tenant_id using app.current_tenant setting.
Mirror pattern from voice service setup_rls.sql.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── cr_rolling_summary ────────────────────────────────────────────────────
    op.create_table(
        "cr_rolling_summary",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("staff_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("metadata", postgresql.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "processed_note_ids",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("tenant_id", "staff_id", "client_id", name="uq_rolling_summary_pair"),
    )
    op.create_index("ix_cr_rolling_summary_tenant", "cr_rolling_summary", ["tenant_id"])
    op.create_index("ix_cr_rolling_summary_staff", "cr_rolling_summary", ["staff_id"])
    op.create_index("ix_cr_rolling_summary_client", "cr_rolling_summary", ["client_id"])

    # ── cr_review_session ─────────────────────────────────────────────────────
    op.create_table(
        "cr_review_session",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("staff_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("drafted_case_note_id", sa.String(128), nullable=True),
        sa.Column("raw_paragraph", sa.Text(), nullable=False, server_default=""),
        sa.Column("classified_fields", postgresql.JSON(), nullable=False, server_default="{}"),
        sa.Column("missing_fields", postgresql.JSON(), nullable=False, server_default="[]"),
        sa.Column("flags", postgresql.JSON(), nullable=False, server_default="{}"),
        sa.Column("incident_detected", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("status", sa.String(30), nullable=False, server_default="input"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_cr_review_session_tenant", "cr_review_session", ["tenant_id"])
    op.create_index("ix_cr_review_session_staff", "cr_review_session", ["staff_id"])
    op.create_index("ix_cr_review_session_client", "cr_review_session", ["client_id"])
    op.create_index(
        "ix_cr_review_session_note_id", "cr_review_session", ["drafted_case_note_id"]
    )

    # ── cr_incident_draft ─────────────────────────────────────────────────────
    op.create_table(
        "cr_incident_draft",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "review_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cr_review_session.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("autofill_source", postgresql.JSON(), nullable=False, server_default="{}"),
        sa.Column("draft_fields", postgresql.JSON(), nullable=False, server_default="{}"),
        sa.Column("staff_confirmed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_cr_incident_draft_tenant", "cr_incident_draft", ["tenant_id"])
    op.create_index(
        "ix_cr_incident_draft_session", "cr_incident_draft", ["review_session_id"]
    )

    # ── cr_review_audit_log ───────────────────────────────────────────────────
    op.create_table(
        "cr_review_audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "review_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cr_review_session.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("payload", postgresql.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_cr_audit_log_tenant", "cr_review_audit_log", ["tenant_id"])
    op.create_index("ix_cr_audit_log_session", "cr_review_audit_log", ["review_session_id"])

    # ── RLS policies (tenant isolation — legal requirement) ───────────────────
    for table in (
        "cr_rolling_summary",
        "cr_review_session",
        "cr_incident_draft",
        "cr_review_audit_log",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
            USING (tenant_id = (current_setting('app.current_tenant'))::uuid);
            """
        )


def downgrade() -> None:
    for table in (
        "cr_review_audit_log",
        "cr_incident_draft",
        "cr_review_session",
        "cr_rolling_summary",
    ):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table};")
        op.drop_table(table)
