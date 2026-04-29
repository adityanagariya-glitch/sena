"""Embed document chunks via Gemini embeddings and upsert into pgvector."""

import asyncio
import logging

from google import genai
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from ingestion.chunker import DocumentChunk
from models.db import NDISPolicyChunk

logger = logging.getLogger(__name__)


def _make_client() -> genai.Client:
    """Build a google-genai client — Vertex AI if project set, else AI Studio."""
    if settings.use_vertex_ai:
        return genai.Client(
            vertexai=True,
            project=settings.gcp_project,
            location=settings.gcp_location,
        )
    return genai.Client(api_key=settings.gemini_api_key)


_client = _make_client()


def _embed_sync(text: str) -> list[float]:
    result = _client.models.embed_content(
        model=settings.embedding_model,
        contents=text,
    )
    return result.embeddings[0].values


async def embed_text(text: str) -> list[float]:
    """Async-safe embedding: offloads the blocking SDK call to a thread."""
    return await asyncio.to_thread(_embed_sync, text)


async def embed_query(query: str) -> list[float]:
    """Embed a RAG query string."""
    return await embed_text(query)


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
                embedding=embedding,
            )
            .on_conflict_do_update(
                index_elements=["chunk_id"],
                set_={"text": chunk.text, "embedding": embedding},
            )
        )
        await db.execute(stmt)
        stored += 1

    await db.commit()
    logger.info("Upserted %d chunks.", stored)
    return stored
