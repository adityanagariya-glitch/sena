"""add restrictive practices pipeline tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-13

Tables created:
  - rp_ndis_policy_chunks   (global NDIS reference data — no RLS; shared across tenants)
  - behaviour_support_plans (per-tenant BSP data — RLS on tenant_id)
  - rp_case_note_runs       (per-tenant pipeline audit log — RLS on tenant_id)

HNSW index on rp_ndis_policy_chunks.embedding for sub-ms ANN search.
pgvector extension must already be enabled (migration 0001 depends on it via ai-db init).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pgvector HALFVEC type — must be registered before creating the column
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # ── rp_ndis_policy_chunks ──────────────────────────────────────────────────
    # Global NDIS policy reference data. Shared across all tenants — no RLS.
    op.create_table(
        "rp_ndis_policy_chunks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("chunk_id", sa.String(64), nullable=False, unique=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("document_source", sa.String(200), nullable=False),
        sa.Column("risk_level", sa.String(50), nullable=False),
        sa.Column(
            "document_type", sa.String(100), nullable=False, server_default="Regulatory"
        ),
        # HALFVEC(1024) — Cohere Embed English v3 output dimension
        sa.Column(
            "embedding",
            sa.Text().with_variant(sa.Text(), "postgresql"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_rp_ndis_chunks_category", "rp_ndis_policy_chunks", ["category"])

    # Replace placeholder Text column with proper HALFVEC type
    op.execute("ALTER TABLE rp_ndis_policy_chunks DROP COLUMN embedding;")
    op.execute(
        "ALTER TABLE rp_ndis_policy_chunks ADD COLUMN embedding HALFVEC(1024) NOT NULL"
        " DEFAULT '{}'::HALFVEC;"
    )
    op.execute(
        "ALTER TABLE rp_ndis_policy_chunks ALTER COLUMN embedding DROP DEFAULT;"
    )

    # HNSW index — works on empty tables; IVFFlat requires pre-existing rows
    op.execute(
        """
        CREATE INDEX ix_rp_ndis_chunks_embedding_hnsw
        ON rp_ndis_policy_chunks
        USING hnsw (embedding halfvec_cosine_ops)
        WITH (m = 16, ef_construction = 64);
        """
    )

    # ── behaviour_support_plans ───────────────────────────────────────────────
    op.create_table(
        "behaviour_support_plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(100), nullable=False),
        sa.Column("client_id", sa.String(100), nullable=False),
        sa.Column("practice_type", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="Active"),
        sa.Column("approved_dosage", sa.String(200), nullable=True),
        sa.Column("approved_conditions", sa.Text(), nullable=True),
        sa.Column("authorised_by", sa.String(200), nullable=True),
        sa.Column("valid_from", sa.DateTime(), nullable=True),
        sa.Column("valid_until", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_bsp_tenant", "behaviour_support_plans", ["tenant_id"])
    op.create_index("ix_bsp_client", "behaviour_support_plans", ["client_id"])
    op.create_index("ix_bsp_practice_type", "behaviour_support_plans", ["practice_type"])

    # RLS — tenant isolation (legal mandate)
    op.execute("ALTER TABLE behaviour_support_plans ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE behaviour_support_plans FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY behaviour_support_plans_tenant_isolation ON behaviour_support_plans
        USING (tenant_id = current_setting('app.current_tenant'));
        """
    )

    # ── rp_case_note_runs ─────────────────────────────────────────────────────
    op.create_table(
        "rp_case_note_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(100), nullable=False),
        sa.Column("case_note_id", sa.String(100), nullable=False),
        sa.Column("client_id", sa.String(100), nullable=False),
        sa.Column("worker_id", sa.String(100), nullable=False),
        sa.Column("triage_flagged", sa.Boolean(), nullable=False),
        sa.Column("evaluator_output", postgresql.JSONB(), nullable=True),
        sa.Column("authorisation_status", sa.String(100), nullable=True),
        sa.Column("alert_required", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("processing_time_ms", sa.Integer(), nullable=True),
        sa.Column("triage_ms", sa.Integer(), nullable=True),
        sa.Column("rag_ms", sa.Integer(), nullable=True),
        sa.Column("evaluator_ms", sa.Integer(), nullable=True),
        sa.Column("cross_check_ms", sa.Integer(), nullable=True),
        sa.Column("summary_ms", sa.Integer(), nullable=True),
        sa.Column("incident_draft_ms", sa.Integer(), nullable=True),
        sa.Column("evaluator_output_tokens", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_rp_runs_tenant", "rp_case_note_runs", ["tenant_id"])
    op.create_index("ix_rp_runs_case_note", "rp_case_note_runs", ["case_note_id"])
    op.create_index("ix_rp_runs_client", "rp_case_note_runs", ["client_id"])

    # RLS — tenant isolation (legal mandate)
    op.execute("ALTER TABLE rp_case_note_runs ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE rp_case_note_runs FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY rp_case_note_runs_tenant_isolation ON rp_case_note_runs
        USING (tenant_id = current_setting('app.current_tenant'));
        """
    )


def downgrade() -> None:
    # downgrade destroys data — intentional; forward-only in production
    for table in ("rp_case_note_runs", "behaviour_support_plans"):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table};")
    op.drop_table("rp_case_note_runs")
    op.drop_table("behaviour_support_plans")
    op.drop_table("rp_ndis_policy_chunks")
