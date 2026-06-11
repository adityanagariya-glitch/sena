"""add case note runs table

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-11

Tables created:
  - rp_case_note_runs  (performance metrics for case note processing)
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── rp_case_note_runs ─────────────────────────────────────────────────────
    op.create_table(
        "rp_case_note_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("case_note_id", sa.String(256), nullable=False),
        sa.Column("client_id", sa.String(256), nullable=False),
        sa.Column("worker_id", sa.String(256), nullable=False),
        sa.Column("triage_flagged", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("evaluator_output", postgresql.JSON(), nullable=True),
        sa.Column("authorisation_status", sa.String(64), nullable=True),
        sa.Column("alert_required", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("processing_time_ms", sa.Integer(), nullable=True),
        sa.Column("triage_ms", sa.Integer(), nullable=True),
        sa.Column("reg_ms", sa.Integer(), nullable=True),
        sa.Column("evaluator_ms", sa.Integer(), nullable=True),
        sa.Column("cross_check_ms", sa.Integer(), nullable=True),
        sa.Column("summary_ms", sa.Integer(), nullable=True),
        sa.Column("incident_draft_ms", sa.Integer(), nullable=True),
        sa.Column("evaluator_output_tokens", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_rp_case_note_runs_case_note_id", "rp_case_note_runs", ["case_note_id"])
    op.create_index("ix_rp_case_note_runs_client_id", "rp_case_note_runs", ["client_id"])
    op.create_index("ix_rp_case_note_runs_worker_id", "rp_case_note_runs", ["worker_id"])


def downgrade() -> None:
    op.drop_table("rp_case_note_runs")
