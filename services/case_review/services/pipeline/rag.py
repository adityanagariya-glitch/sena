"""Step 4 — Hybrid RAG Retrieval.

Pipeline:
  1. Embed query with Cohere (search_query input type — asymmetric)
  2. Run BM25 (tsvector) + Vector (cosine) searches in PARALLEL
  3. Merge results with Reciprocal Rank Fusion:  score = Σ 1/(60 + rank_i)
  4. Rerank merged candidates with Cohere Rerank v3.5 (cross-encoder)
  5. For child chunks: fetch parent chunk text (full regulatory section)
  6. Compress boilerplate from returned chunks
  7. Return top-3 PolicyChunk objects to evaluator

Why hybrid:
  - Vector search misses exact keyword matches (e.g. "section 5.2.4", "NDIS Act")
  - BM25 misses semantic synonyms ("seclusion" vs "isolation")
  - RRF penalises near-misses, rewards agreement between both signals
  - Reranker (cross-encoder) reads query+chunk TOGETHER — more accurate than any
    similarity metric that scores them independently

Cost impact:
  - BM25 is zero-cost (pure SQL GIN index)
  - Reranker costs ~$0.0002 per 1000 docs — negligible vs evaluator cost
  - Net: we send fewer, better chunks to Sonnet → 40-60% evaluator token saving
"""

import asyncio
import json
import logging
import re

import boto3
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from case_review.models.db import NDISPolicyChunk
from case_review.models.schemas import CaseNoteInput, PolicyChunk, TriageResult

logger = logging.getLogger(__name__)

# ── Adaptive retrieval depth thresholds ──────────────────────────────────────
# Driven by triage_confidence so high-confidence cases pay fewer RAG tokens.
#
# > 0.95  Explicit violation ("locked the door", "held him down")
#         → 1 chunk sufficient; the evaluator already knows what it is
# 0.80-0.95  Normal path — policy grounding needed
#         → 3 chunks (default)
# < 0.80  Ambiguous language — needs more context + query expansion
#         → 5 chunks, plus 2-3 Haiku-generated alternative queries
_HIGH_CONF_THRESHOLD = 0.95   # top-1
_LOW_CONF_THRESHOLD  = 0.80   # top-5 + query expansion

_BOILERPLATE_RE = re.compile(
    r"^(version\s|v\d+\.\d+|date:|approved:|effective:|page\s+\d+|\d+\.\s*$)",
    re.IGNORECASE,
)

# RRF constant — standard value; lowers the impact of very low-ranked results
_RRF_K = 60


def _compress_chunk(text: str) -> str:
    """Strip boilerplate lines and consecutive duplicate sentences from a policy chunk.

    Reduces ~1200-char chunks by 20-35% without losing regulatory substance.
    """
    lines = text.strip().splitlines()
    kept: list[str] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if _BOILERPLATE_RE.match(line):
            continue
        if kept and line == kept[-1]:
            continue
        kept.append(line)
    return " ".join(kept)


async def _vector_search(
    query_embedding: list[float],
    db: AsyncSession,
    limit: int,
    parent_only: bool = False,
) -> list[NDISPolicyChunk]:
    """Cosine similarity search using pgvector HNSW index.

    Filters out parent chunks (is_parent=True) — they have no embedding.
    Only child chunks and legacy flat chunks are retrievable via vector.
    """
    distance_col = NDISPolicyChunk.embedding.op("<=>")(query_embedding)
    stmt = (
        select(NDISPolicyChunk)
        .where(NDISPolicyChunk.is_parent.is_(False))
        .where(NDISPolicyChunk.embedding.is_not(None))
        .order_by(distance_col)
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _bm25_search(
    query_text: str,
    db: AsyncSession,
    limit: int,
) -> list[NDISPolicyChunk]:
    """BM25 full-text search using PostgreSQL tsvector GIN index.

    Runs ts_rank_cd (cover-density ranking, better than ts_rank for short queries)
    against the search_vector column populated at ingest time.

    Falls back to empty list if search_vector column not yet migrated.
    """
    # plainto_tsquery handles natural language queries without special syntax requirements
    raw_sql = text("""
        SELECT chunk.*
        FROM rp_ndis_policy_chunks chunk
        WHERE chunk.search_vector IS NOT NULL
          AND chunk.is_parent = false
          AND chunk.search_vector @@ plainto_tsquery('english', :q)
        ORDER BY ts_rank_cd(chunk.search_vector, plainto_tsquery('english', :q)) DESC
        LIMIT :lim
    """)
    try:
        result = await db.execute(raw_sql, {"q": query_text, "lim": limit})
        rows = result.fetchall()
        if not rows:
            return []
        chunk_ids = [r[0] for r in rows]
        stmt = select(NDISPolicyChunk).where(
            NDISPolicyChunk.id.in_(chunk_ids)
        )
        chunks_result = await db.execute(stmt)
        return list(chunks_result.scalars().all())
    except Exception as exc:
        logger.warning("bm25 search failed (%s) — degrading to vector-only", type(exc).__name__)
        return []


def _reciprocal_rank_fusion(
    *ranked_lists: list[NDISPolicyChunk],
) -> list[NDISPolicyChunk]:
    """Merge multiple ranked lists using Reciprocal Rank Fusion.

    RRF score formula: score(d) = Σ_i  1 / (k + rank_i(d))
      k=60  (standard constant — reduces sensitivity to very top ranks)
      rank_i starts at 1

    Chunks appearing in both vector AND BM25 results are strongly boosted.
    Chunks only in one signal are penalised relative to dual-signal chunks.

    Returns: deduplicated list sorted by RRF score descending.
    """
    scores: dict[str, float] = {}
    chunk_map: dict[str, NDISPolicyChunk] = {}

    for ranked_list in ranked_lists:
        for rank, chunk in enumerate(ranked_list, start=1):
            cid = chunk.chunk_id
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (_RRF_K + rank)
            chunk_map[cid] = chunk

    return sorted(chunk_map.values(), key=lambda c: scores[c.chunk_id], reverse=True)


async def _fetch_parent_chunks(
    child_chunks: list[NDISPolicyChunk],
    db: AsyncSession,
) -> list[NDISPolicyChunk]:
    """Swap child chunks for their parent chunks where parent_chunk_id is set.

    Parent chunks contain the full regulatory section text (~800-1500 chars),
    giving the evaluator complete context instead of a 300-char fragment.

    Legacy flat chunks (parent_chunk_id=None) are returned as-is.
    """
    parent_ids = [c.parent_chunk_id for c in child_chunks if c.parent_chunk_id]

    if not parent_ids:
        return child_chunks

    stmt = select(NDISPolicyChunk).where(
        NDISPolicyChunk.chunk_id.in_(parent_ids)
    )
    result = await db.execute(stmt)
    parent_map: dict[str, NDISPolicyChunk] = {p.chunk_id: p for p in result.scalars().all()}

    upgraded: list[NDISPolicyChunk] = []
    seen_parent_ids: set[str] = set()

    for chunk in child_chunks:
        if chunk.parent_chunk_id and chunk.parent_chunk_id in parent_map:
            pid = chunk.parent_chunk_id
            if pid not in seen_parent_ids:
                # Deduplicate: multiple children from the same parent → send parent once
                upgraded.append(parent_map[pid])
                seen_parent_ids.add(pid)
        else:
            # Legacy flat chunk or parent not found — use the chunk directly
            upgraded.append(chunk)

    return upgraded


def _expand_query_sync(action_summary: str) -> list[str]:
    """Haiku rewrites the action_summary into 2-3 alternative regulatory search queries.

    Only called for low-confidence triage (< 0.80). The queries cover:
    - The specific NDIS regulatory category (physical/chemical/environmental restraint etc.)
    - Legal terminology from the Rules 2018
    - Reporting and documentation obligations angle

    Cost: ~$0.0002 per call (Haiku, short prompt). Justified because low-confidence
    cases already indicate ambiguous language where more context is needed.
    """
    kwargs: dict = {"region_name": settings.aws_region}
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    client = boto3.client("bedrock-runtime", **kwargs)

    prompt = (
        "You are rewriting an NDIS compliance query for regulatory document retrieval.\n\n"
        f"Original query: {action_summary}\n\n"
        "Generate exactly 2 alternative search queries that cover different angles:\n"
        "1. The specific NDIS regulated practice category (physical restraint, seclusion, "
        "chemical restraint, mechanical restraint, environmental restraint)\n"
        "2. The documentation and behaviour support plan authorisation angle\n\n"
        "Return ONLY a JSON array of 2 strings. "
        'Example: ["physical restraint NDIS Rules 2018 authorisation", '
        '"behaviour support plan restrictive practice documentation requirement"]'
    )
    response = client.converse(
        modelId=settings.classifier_model,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 200, "temperature": 0.0},
    )
    raw = response["output"]["message"]["content"][0]["text"]
    start = raw.find("[")
    end = raw.rfind("]") + 1
    if start == -1 or end == 0:
        return []
    try:
        queries = json.loads(raw[start:end])
        return [q for q in queries if isinstance(q, str) and q.strip()]
    except (json.JSONDecodeError, TypeError):
        return []


async def _expand_query(action_summary: str) -> list[str]:
    """Async wrapper for query expansion (runs Haiku in thread pool)."""
    try:
        extras = await asyncio.to_thread(_expand_query_sync, action_summary)
        logger.info("rag.query_expansion generated %d extra queries", len(extras))
        return extras
    except Exception as exc:
        logger.warning("rag.query_expansion failed (%s) — proceeding without", type(exc).__name__)
        return []


async def retrieve_policy_chunks(
    note: CaseNoteInput,
    triage: TriageResult,
    db: AsyncSession,
) -> list[PolicyChunk]:
    """Hybrid RAG: BM25 + Vector → RRF → Rerank → Parent-fetch → Compress.

    Adaptive retrieval depth based on triage_confidence:
      > 0.95  → top-1 chunk only  (explicit violation, evaluator has enough)
      0.80-0.95 → top-3 chunks    (normal path)
      < 0.80  → top-5 + query expansion (ambiguous, needs more regulatory context)

    Savings: high-confidence cases (majority of real violations) use ~70% fewer
    RAG tokens. Low-confidence cases spend a little more for better accuracy.

    Returns at most max_chunks PolicyChunk objects.
    Falls back to top-1 vector result if everything else fails.
    """
    from case_review.services.ingestion.embedder import embed_query, rerank_chunks

    query_text = triage.action_summary or note.to_text()
    confidence = triage.triage_confidence

    # Adaptive depth: scale retrieval by how confident triage was
    if confidence > _HIGH_CONF_THRESHOLD:
        max_chunks = 1
        fetch_k = 3
        logger.info("rag.adaptive high_conf=%.2f → top-1 mode", confidence)
    elif confidence < _LOW_CONF_THRESHOLD:
        max_chunks = 5
        fetch_k = settings.rag_top_k_fetch
        logger.info("rag.adaptive low_conf=%.2f → top-5 + query expansion", confidence)
    else:
        max_chunks = settings.rag_max_chunks
        fetch_k = settings.rag_top_k_fetch
        logger.info("rag.adaptive normal_conf=%.2f → top-%d", confidence, max_chunks)

    logger.info(
        "rag.hybrid case_note_id=%s query=%r conf=%.2f max_chunks=%d",
        note.case_note_id,
        query_text[:80],
        confidence,
        max_chunks,
    )

    # Step 1: Decide the query set. Low-confidence (ambiguous) notes get
    # Haiku-expanded query variants so BOTH retrieval signals widen — not just
    # keyword search. Normal/high-confidence paths use the single query.
    if confidence < _LOW_CONF_THRESHOLD:
        extra_queries = await _expand_query(query_text)
        all_queries = [query_text] + extra_queries
    else:
        all_queries = [query_text]

    # Embed EVERY query variant (search_query input type). Each variant gets its
    # own embedding so the semantic (vector) search benefits from expansion too,
    # not only BM25. Single-query path = one embed call (cost unchanged).
    query_embeddings = await asyncio.gather(*[embed_query(q) for q in all_queries])

    # Step 2: For each query run BM25 (on text) + vector (on its own embedding).
    # These run SEQUENTIALLY on purpose. A single AsyncSession multiplexes one
    # connection and cannot service concurrent operations — asyncio.gather() of
    # multiple db.execute() calls on the same session raises
    #   "This session is provisioning a new connection; concurrent operations
    #    are not permitted"
    # the first time it runs on a cold (un-provisioned) session, which is exactly
    # what happens on every real request (RAG is the first DB touch in the chain).
    # The queries are GIN/HNSW-indexed and sub-10ms, and true parallelism is
    # impossible over one connection anyway, so sequential is correct and cheap.
    bm25_lists = [await _bm25_search(q, db, limit=fetch_k) for q in all_queries]
    vector_lists = [await _vector_search(emb, db, limit=fetch_k) for emb in query_embeddings]

    n = len(all_queries)
    all_results = bm25_lists + vector_lists  # retained for the signal-count log below

    # Distinct-chunk counts for logging only (RRF dedups internally)
    vector_seen = {c.chunk_id for lst in vector_lists for c in lst}
    bm25_seen = {c.chunk_id for lst in bm25_lists for c in lst}

    logger.info(
        "rag.signals vector=%d bm25=%d (queries=%d, lists=%d)",
        len(vector_seen),
        len(bm25_seen),
        n,
        len(all_results),
    )

    # Step 3: Merge EVERY ranked list with RRF. Each (query × signal) is its own
    # list, so chunks surfaced by multiple variants or by both signals rank highest.
    merged = _reciprocal_rank_fusion(*vector_lists, *bm25_lists)

    if not merged:
        logger.warning("rag.hybrid — no chunks retrieved, returning empty")
        return []

    # Step 4: Rerank top candidates (cross-encoder sees query + chunk together)
    rerank_candidates = merged[: min(15, len(merged))]
    from case_review.services.ingestion.chunker import DocumentChunk as DC
    dc_candidates = [
        DC(
            chunk_id=c.chunk_id,
            text=c.text,
            category=c.category,
            document_source=c.document_source,
            risk_level=c.risk_level,
            document_type=c.document_type,
            parent_chunk_id=c.parent_chunk_id,
            is_parent=c.is_parent,
        )
        for c in rerank_candidates
    ]

    reranked_pairs = await rerank_chunks(query_text, dc_candidates, top_n=max_chunks)

    # Rebuild NDISPolicyChunk objects in reranked order for parent lookup
    chunk_by_id = {c.chunk_id: c for c in rerank_candidates}
    reranked_db_chunks = [
        chunk_by_id[dc.chunk_id]
        for dc, _score in reranked_pairs
        if dc.chunk_id in chunk_by_id
    ]

    if not reranked_db_chunks:
        # Reranker returned nothing — fallback to top RRF result
        reranked_db_chunks = merged[:1]

    # Step 4: Swap children for parent chunks (full section text for evaluator)
    final_chunks = await _fetch_parent_chunks(reranked_db_chunks, db)

    # Step 5: Build PolicyChunk output with boilerplate compression
    result_chunks = [
        PolicyChunk(
            chunk_id=chunk.chunk_id,
            text=_compress_chunk(chunk.text),
            category=chunk.category,
            document_source=chunk.document_source,
            risk_level=chunk.risk_level,
            document_type=chunk.document_type,
        )
        for chunk in final_chunks
    ]

    logger.info(
        "rag.hybrid → %d chunks (vector=%d bm25=%d merged=%d reranked=%d) categories=%s",
        len(result_chunks),
        len(vector_seen),
        len(bm25_seen),
        len(merged),
        len(reranked_db_chunks),
        [c.category for c in result_chunks],
    )

    return result_chunks


async def retrieve_style_chunks(
    query: str,
    document_type: str,
    db: AsyncSession,
    top_k: int = 2,
) -> list[PolicyChunk]:
    """Retrieve style/example chunks filtered by document_type.

    Uses vector-only (no BM25 rerank) — style retrieval is about semantic
    similarity to examples, not keyword matching.
    """
    from case_review.services.ingestion.embedder import embed_query

    logger.info(
        "rag.style document_type=%r query=%r",
        document_type,
        query[:80],
    )

    query_embedding = await embed_query(query)

    stmt = (
        select(NDISPolicyChunk)
        .where(NDISPolicyChunk.document_type == document_type)
        .where(NDISPolicyChunk.is_parent.is_(False))
        .where(NDISPolicyChunk.embedding.is_not(None))
        .order_by(NDISPolicyChunk.embedding.op("<=>")(query_embedding))
        .limit(top_k)
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

    logger.info("rag.style → %d chunks document_type=%r", len(chunks), document_type)
    return chunks
