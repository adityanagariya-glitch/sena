"""add restrictive practices pipeline tables (idempotent)

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-13

Tables created:
  - rp_ndis_policy_chunks   (global NDIS reference data — no RLS; shared across tenants)
  - behaviour_support_plans (per-tenant BSP data — RLS on tenant_id)
  - rp_case_note_runs       (per-tenant pipeline audit log — RLS on tenant_id)

HNSW index on rp_ndis_policy_chunks.embedding for sub-ms ANN search.
pgvector extension must already be enabled (migration 0001 depends on it via ai-db init).

IDEMPOTENT: every object is created with IF NOT EXISTS and policies are guarded, so
this migration is safe to run against a database whose tables were bootstrapped
outside alembic (skip if present, create if missing).

NOTE on RLS: the policies below enable FORCE ROW LEVEL SECURITY keyed on
current_setting('app.current_tenant'). If the application does NOT set that GUC per
connection, enabling RLS will block all reads/writes. On databases that already run
WITHOUT RLS (e.g. tables created via create_all), DO NOT let this migration execute
the RLS block against them — stamp past 0002 instead. The CREATE POLICY statements
are guarded with DROP POLICY IF EXISTS so re-runs do not error.
"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # ── rp_ndis_policy_chunks ──────────────────────────────────────────────────
    # Global NDIS policy reference data. Shared across all tenants — no RLS.
    # embedding is HALFVEC(1024) — Cohere Embed English v3 output dimension.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS rp_ndis_policy_chunks (
            id SERIAL PRIMARY KEY,
            chunk_id VARCHAR(64) NOT NULL UNIQUE,
            text TEXT NOT NULL,
            category VARCHAR(100) NOT NULL,
            document_source VARCHAR(200) NOT NULL,
            risk_level VARCHAR(50) NOT NULL,
            document_type VARCHAR(100) NOT NULL DEFAULT 'Regulatory',
            embedding HALFVEC(1024) NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_rp_ndis_chunks_category "
        "ON rp_ndis_policy_chunks (category);"
    )
    # HNSW index — works on empty tables; IVFFlat requires pre-existing rows
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_rp_ndis_chunks_embedding_hnsw
        ON rp_ndis_policy_chunks
        USING hnsw (embedding halfvec_cosine_ops)
        WITH (m = 16, ef_construction = 64);
        """
    )

    # ── behaviour_support_plans ───────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS behaviour_support_plans (
            id VARCHAR(36) PRIMARY KEY,
            tenant_id VARCHAR(100) NOT NULL,
            client_id VARCHAR(100) NOT NULL,
            practice_type VARCHAR(100) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'Active',
            approved_dosage VARCHAR(200),
            approved_conditions TEXT,
            authorised_by VARCHAR(200),
            valid_from TIMESTAMP,
            valid_until TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_bsp_tenant ON behaviour_support_plans (tenant_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_bsp_client ON behaviour_support_plans (client_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_bsp_practice_type ON behaviour_support_plans (practice_type);")

    # ── rp_case_note_runs ─────────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS rp_case_note_runs (
            id VARCHAR(36) PRIMARY KEY,
            tenant_id VARCHAR(100) NOT NULL,
            case_note_id VARCHAR(100) NOT NULL,
            client_id VARCHAR(100) NOT NULL,
            worker_id VARCHAR(100) NOT NULL,
            triage_flagged BOOLEAN NOT NULL,
            evaluator_output JSONB,
            authorisation_status VARCHAR(100),
            alert_required BOOLEAN NOT NULL DEFAULT false,
            processing_time_ms INTEGER,
            triage_ms INTEGER,
            rag_ms INTEGER,
            evaluator_ms INTEGER,
            cross_check_ms INTEGER,
            summary_ms INTEGER,
            incident_draft_ms INTEGER,
            evaluator_output_tokens INTEGER,
            created_at TIMESTAMP NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_rp_runs_tenant ON rp_case_note_runs (tenant_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_rp_runs_case_note ON rp_case_note_runs (case_note_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_rp_runs_client ON rp_case_note_runs (client_id);")

    # ── RLS — tenant isolation (legal mandate) ────────────────────────────────
    # Guarded so re-runs don't error. See module docstring re: app.current_tenant.
    for table in ("behaviour_support_plans", "rp_case_note_runs"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table};")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
            USING (tenant_id = current_setting('app.current_tenant'));
            """
        )


def downgrade() -> None:
    # downgrade destroys data — intentional; forward-only in production
    for table in ("rp_case_note_runs", "behaviour_support_plans"):
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table};")
    op.execute("DROP TABLE IF EXISTS rp_case_note_runs;")
    op.execute("DROP TABLE IF EXISTS behaviour_support_plans;")
    op.execute("DROP TABLE IF EXISTS rp_ndis_policy_chunks;")
