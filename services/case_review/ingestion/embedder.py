"""Embed document chunks via Bedrock (Cohere Embed English v3) and upsert into pgvector."""

import asyncio
import json as _json
import logging

import boto3
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from ingestion.chunker import DocumentChunk
from models.db import NDISPolicyChunk

logger = logging.getLogger(__name__)


def _make_client():
    kwargs: dict = {"region_name": settings.aws_region}
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    return boto3.client("bedrock-runtime", **kwargs)


_client = None


def _get_client():
    global _client
    if _client is None:
        _client = _make_client()
    return _client


def _embed_sync(text: str, input_type: str = "search_document") -> list[float]:
    """Synchronous Cohere embed call via Bedrock invoke_model.

    input_type must be 'search_document' for ingest and 'search_query' for RAG retrieval.
    Cohere v3 uses these to apply asymmetric embedding — mixing them degrades retrieval quality.
    """
    body = _json.dumps({"texts": [text], "input_type": input_type, "truncate": "END"})
    response = _get_client().invoke_model(
        modelId=settings.embedding_model,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    result = _json.loads(response["body"].read())
    return result["embeddings"][0]


async def embed_text(text: str) -> list[float]:
    """Async-safe embedding for document ingest — offloads blocking SDK call to thread pool."""
    return await asyncio.to_thread(_embed_sync, text, "search_document")


async def embed_query(query: str) -> list[float]:
    """Async-safe embedding for RAG queries."""
    return await asyncio.to_thread(_embed_sync, query, "search_query")


async def upsert_chunks(chunks: list[DocumentChunk], db: AsyncSession) -> int:
    """Embed each chunk and upsert into pgvector. Returns count stored."""
    stored = 0
    for chunk in chunks:
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
            )
            .on_conflict_do_update(
                index_elements=["chunk_id"],
                set_={"text": chunk.text, "document_type": chunk.document_type, "embedding": embedding},
            )
        )
        await db.execute(stmt)
        stored += 1

    await db.commit()
    logger.info("Upserted %d chunks.", stored)
    return stored
