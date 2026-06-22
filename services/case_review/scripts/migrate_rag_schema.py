"""Idempotent migration: add parent-child + hybrid search columns to rp_ndis_policy_chunks.

Run ONCE after deploying the new RAG code, BEFORE re-running ingest_ndis_policies.py.

Safe to run multiple times — all statements use IF NOT EXISTS / IF EXISTS guards.

    python scripts/migrate_rag_schema.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from db.session import AsyncSessionLocal


MIGRATION_SQL = """
-- 1. Parent-child FK column (NULL = root/flat chunk)
ALTER TABLE rp_ndis_policy_chunks
    ADD COLUMN IF NOT EXISTS parent_chunk_id VARCHAR(64)
        REFERENCES rp_ndis_policy_chunks(chunk_id) ON DELETE CASCADE;

-- 2. Flag: TRUE only for parent/section chunks
ALTER TABLE rp_ndis_policy_chunks
    ADD COLUMN IF NOT EXISTS is_parent BOOLEAN NOT NULL DEFAULT FALSE;

-- 3. BM25 tsvector — populated at ingest, queried with @@
ALTER TABLE rp_ndis_policy_chunks
    ADD COLUMN IF NOT EXISTS search_vector TSVECTOR;

-- 4. GIN index on tsvector for fast full-text search
CREATE INDEX IF NOT EXISTS idx_rp_ndis_policy_chunks_fts
    ON rp_ndis_policy_chunks USING GIN(search_vector);

-- 5. Index on parent_chunk_id for fast parent lookup during retrieval
CREATE INDEX IF NOT EXISTS idx_rp_ndis_policy_chunks_parent
    ON rp_ndis_policy_chunks(parent_chunk_id)
    WHERE parent_chunk_id IS NOT NULL;

-- 6. Backfill search_vector for existing flat chunks (legacy data)
UPDATE rp_ndis_policy_chunks
SET search_vector = to_tsvector('english', text)
WHERE search_vector IS NULL;

-- 7. Make embedding nullable so parent chunks (no embedding) can be stored
ALTER TABLE rp_ndis_policy_chunks
    ALTER COLUMN embedding DROP NOT NULL;
"""


async def main() -> None:
    print("=== RAG Schema Migration ===")
    print("Adding: parent_chunk_id, is_parent, search_vector + GIN index")
    print()

    async with AsyncSessionLocal() as db:
        for i, stmt in enumerate(
            [s.strip() for s in MIGRATION_SQL.split(";") if s.strip()], 1
        ):
            print(f"[{i}] {stmt[:80]}...")
            await db.execute(text(stmt))
        await db.commit()

    print()
    print("Migration complete.")
    print("Next step: python scripts/ingest_ndis_policies.py")
    print("  This re-ingests all PDFs with parent-child semantic chunking.")


if __name__ == "__main__":
    asyncio.run(main())
