"""Step 4 — Targeted RAG Retrieval.

Embeds the triage action_summary (or transcript fallback) and retrieves the
top-K most semantically similar NDIS policy chunks from pgvector using the
HNSW cosine index. Results feed the evaluator with grounding context.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from ingestion.embedder import embed_query
from models.db import NDISPolicyChunk
from models.schemas import CaseNoteInput, PolicyChunk, TriageResult

logger = logging.getLogger(__name__)


async def retrieve_policy_chunks(
    note: CaseNoteInput,
    triage: TriageResult,
    db: AsyncSession,
) -> list[PolicyChunk]:
    """Embed the query and retrieve top-K relevant NDIS policy chunks."""
    # Prefer the focused action_summary over the full transcript —
    # it's a clean 1-sentence description of the suspected practice.
    query_text = triage.action_summary or note.to_text()

    logger.info(
        "rag retrieve case_note_id=%s query=%r",
        note.case_note_id,
        query_text[:80],
    )

    query_embedding = await embed_query(query_text)

    stmt = (
        select(NDISPolicyChunk)
        # <=> = pgvector cosine distance operator; ORDER BY ASC = most similar first
        .order_by(NDISPolicyChunk.embedding.op("<=>")(query_embedding))
        .limit(settings.rag_top_k)
    )

    result = await db.execute(stmt)
    rows = result.scalars().all()

    chunks = [
        PolicyChunk(
            chunk_id=row.chunk_id,
            text=row.text,
            category=row.category,
            document_source=row.document_source,
            risk_level=row.risk_level,
            document_type=row.document_type,
        )
        for row in rows
    ]

    logger.info(
        "rag retrieved %d chunks categories=%s",
        len(chunks),
        [c.category for c in chunks],
    )

    return chunks
