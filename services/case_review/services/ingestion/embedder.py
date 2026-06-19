"""Embed document chunks via Bedrock (Cohere Embed English v3), rerank, and upsert into pgvector.

Three operations:
  embed_text()    — ingest-time: search_document input type
  embed_query()   — query-time: search_query input type (asymmetric embeddings)
  rerank_chunks() — post-retrieval: Cohere Rerank v3.5 via Bedrock agent runtime
  upsert_chunks() — store chunks with embedding + search_vector (BM25 tsvector)
"""

import asyncio
import json as _json
import logging

import boto3
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.db import NDISPolicyChunk
from services.ingestion.chunker import DocumentChunk

logger = logging.getLogger(__name__)


# ── Bedrock clients (singletons) ──────────────────────────────────────────────

_embed_client = None
_rerank_client = None


def _get_embed_client():
    global _embed_client
    if _embed_client is None:
        kwargs: dict = {"region_name": settings.aws_region}
        if settings.aws_access_key_id and settings.aws_secret_access_key:
            kwargs["aws_access_key_id"] = settings.aws_access_key_id
            kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
        _embed_client = boto3.client("bedrock-runtime", **kwargs)
    return _embed_client


def _get_rerank_client():
    """bedrock-agent-runtime hosts the Rerank API (separate from bedrock-runtime)."""
    global _rerank_client
    if _rerank_client is None:
        kwargs: dict = {"region_name": settings.aws_region}
        if settings.aws_access_key_id and settings.aws_secret_access_key:
            kwargs["aws_access_key_id"] = settings.aws_access_key_id
            kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
        _rerank_client = boto3.client("bedrock-agent-runtime", **kwargs)
    return _rerank_client


# ── Embedding ─────────────────────────────────────────────────────────────────

def _embed_sync(text: str, input_type: str = "search_document") -> list[float]:
    """Synchronous Cohere embed call via Bedrock invoke_model.

    input_type must be 'search_document' for ingest and 'search_query' for RAG retrieval.
    Cohere v3 uses asymmetric embeddings — mixing types degrades retrieval quality.
    """
    body = _json.dumps({"texts": [text], "input_type": input_type, "truncate": "END"})
    response = _get_embed_client().invoke_model(
        modelId=settings.embedding_model,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    result = _json.loads(response["body"].read())
    return result["embeddings"][0]


async def embed_text(text: str) -> list[float]:
    """Async-safe embedding for document ingest."""
    return await asyncio.to_thread(_embed_sync, text, "search_document")


async def embed_query(query: str) -> list[float]:
    """Async-safe embedding for RAG query-time retrieval."""
    return await asyncio.to_thread(_embed_sync, query, "search_query")


# ── Reranking ─────────────────────────────────────────────────────────────────

def _rerank_sync(query: str, chunks: list[DocumentChunk], top_n: int) -> list[tuple[DocumentChunk, float]]:
    """Rerank chunks using Cohere Rerank v3.5 via Bedrock agent runtime.

    Cross-encoder reranking: the model reads query + chunk TOGETHER (not as
    separate embeddings), giving much more accurate relevance scores than
    cosine distance alone.

    Falls back to identity ordering (no rerank) if Bedrock Rerank is unavailable
    in the configured region — the caller still gets valid results.

    Returns: list of (chunk, relevance_score) sorted by score descending.
    """
    try:
        client = _get_rerank_client()
        response = client.rerank(
            queries=[{"type": "TEXT", "textQuery": {"text": query}}],
            sources=[
                {
                    "type": "INLINE",
                    "inlineDocumentSource": {
                        "type": "TEXT",
                        "textDocument": {"text": chunk.text},
                    },
                }
                for chunk in chunks
            ],
            rerankingConfiguration={
                "type": "BEDROCK_RERANKING_MODEL",
                "bedrockRerankingConfiguration": {
                    "modelConfiguration": {
                        "modelArn": (
                            f"arn:aws:bedrock:{settings.aws_region}"
                            "::foundation-model/cohere.rerank-v3-5:0"
                        )
                    },
                    "numberOfResults": min(top_n, len(chunks)),
                },
            },
        )
        # Bedrock Rerank returns "results": [{"index", "relevanceScore", "document"}]
        ranked = response.get("results", [])
        return [(chunks[r["index"]], r["relevanceScore"]) for r in ranked]

    except Exception as exc:
        # Rerank not available in this region or quota exceeded — degrade gracefully
        logger.warning("rerank unavailable (%s) — using original order", type(exc).__name__)
        return [(c, 1.0 - i * 0.01) for i, c in enumerate(chunks[:top_n])]


async def rerank_chunks(
    query: str,
    chunks: list[DocumentChunk],
    top_n: int | None = None,
) -> list[tuple[DocumentChunk, float]]:
    """Async-safe reranking. Returns top-n (chunk, score) pairs sorted by relevance."""
    if not chunks:
        return []
    n = top_n or settings.rag_max_chunks
    return await asyncio.to_thread(_rerank_sync, query, chunks, n)


# ── Upserting ─────────────────────────────────────────────────────────────────

async def upsert_chunks(chunks: list[DocumentChunk], db: AsyncSession) -> int:
    """Embed each chunk and upsert into pgvector with search_vector for BM25.

    Parent chunks (is_parent=True) are stored WITHOUT an embedding — they are
    fetched by FK lookup after child chunks match, not by vector similarity.
    Only child/flat chunks are embedded.

    search_vector is populated via PostgreSQL's to_tsvector() for hybrid BM25 search.
    """
    stored = 0
    for chunk in chunks:
        # Only embed retrievable chunks (children and legacy flat chunks)
        embedding = None
        if not chunk.is_parent:
            logger.info("Embedding chunk %s (%d chars)...", chunk.chunk_id, len(chunk.text))
            embedding = await embed_text(chunk.text)

        stmt = (
            insert(NDISPolicyChunk)
            .values(
                chunk_id=chunk.chunk_id,
                text=chunk.text,
                category=chunk.category,
                document_source=chunk.document_source,
                risk_level=chunk.risk_level,
                document_type=chunk.document_type,
                embedding=embedding,
                parent_chunk_id=chunk.parent_chunk_id,
                is_parent=chunk.is_parent,
                # Populate tsvector inline — no trigger needed
                search_vector=func.to_tsvector("english", chunk.text),
            )
            .on_conflict_do_update(
                index_elements=["chunk_id"],
                set_={
                    "text": chunk.text,
                    "document_type": chunk.document_type,
                    "embedding": embedding,
                    "parent_chunk_id": chunk.parent_chunk_id,
                    "is_parent": chunk.is_parent,
                    "search_vector": func.to_tsvector("english", chunk.text),
                },
            )
        )
        await db.execute(stmt)
        stored += 1

    await db.commit()
    logger.info("Upserted %d chunks (%d with embeddings).",
                stored, sum(1 for c in chunks if not c.is_parent))
    return stored
