"""Add parent-child chunking + BM25 hybrid search columns to rp_ndis_policy_chunks.

Revision ID: 0005
Revises:     0004
Create Date: 2026-06-19

Changes
-------
1. parent_chunk_id  — self-referential FK (child → parent section chunk)
2. is_parent        — boolean flag, default false; true for section-level chunks
3. search_vector    — TSVECTOR column for BM25 full-text search via GIN index
4. GIN index        — idx_rp_ndis_policy_chunks_fts on search_vector
5. Partial index    — idx_rp_ndis_policy_chunks_parent on parent_chunk_id
6. Backfill         — populate search_vector for all existing flat chunks
7. embedding        — make nullable so parent chunks (no embedding) can be stored

All statements are idempotent (IF NOT EXISTS / IF EXISTS guards).
Safe to run on a live database; does NOT lock existing rows.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Self-referential FK: child chunk → parent section chunk
    op.execute("""
        ALTER TABLE rp_ndis_policy_chunks
            ADD COLUMN IF NOT EXISTS parent_chunk_id VARCHAR(64)
                REFERENCES rp_ndis_policy_chunks(chunk_id) ON DELETE CASCADE
    """)

    # 2. Parent flag — existing rows default to false (all were flat chunks)
    op.execute("""
        ALTER TABLE rp_ndis_policy_chunks
            ADD COLUMN IF NOT EXISTS is_parent BOOLEAN NOT NULL DEFAULT FALSE
    """)

    # 3. BM25 tsvector column — populated at ingest
    op.execute("""
        ALTER TABLE rp_ndis_policy_chunks
            ADD COLUMN IF NOT EXISTS search_vector TSVECTOR
    """)

    # 4. GIN index for fast @@ full-text search
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_rp_ndis_policy_chunks_fts
            ON rp_ndis_policy_chunks USING GIN(search_vector)
    """)

    # 5. Partial index on parent_chunk_id for fast parent lookups during retrieval
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_rp_ndis_policy_chunks_parent
            ON rp_ndis_policy_chunks(parent_chunk_id)
            WHERE parent_chunk_id IS NOT NULL
    """)

    # 6. Backfill search_vector for legacy flat chunks
    op.execute("""
        UPDATE rp_ndis_policy_chunks
        SET search_vector = to_tsvector('english', text)
        WHERE search_vector IS NULL
    """)

    # 7. Make embedding nullable — parent chunks have no embedding (retrieved by FK)
    op.execute("""
        ALTER TABLE rp_ndis_policy_chunks
            ALTER COLUMN embedding DROP NOT NULL
    """)


def downgrade() -> None:
    # Reverse in opposite order
    op.execute("ALTER TABLE rp_ndis_policy_chunks ALTER COLUMN embedding SET NOT NULL")
    op.execute("DROP INDEX IF EXISTS idx_rp_ndis_policy_chunks_parent")
    op.execute("DROP INDEX IF EXISTS idx_rp_ndis_policy_chunks_fts")
    op.execute("ALTER TABLE rp_ndis_policy_chunks DROP COLUMN IF EXISTS search_vector")
    op.execute("ALTER TABLE rp_ndis_policy_chunks DROP COLUMN IF EXISTS is_parent")
    op.execute("ALTER TABLE rp_ndis_policy_chunks DROP COLUMN IF EXISTS parent_chunk_id")
