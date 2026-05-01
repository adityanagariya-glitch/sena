"""Async SQLAlchemy engine and session factory."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import settings

engine = create_async_engine(
    settings.rp_database_url,
    echo=False,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields an async DB session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_tables() -> None:
    """Create all tables + vector index. Dev/test only — use Alembic in prod."""
    from sqlalchemy import text

    from models.db import Base

    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        # HNSW index for fast cosine similarity search (must be created after table exists)
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_rp_chunks_embedding "
            "ON rp_ndis_policy_chunks USING hnsw (embedding halfvec_cosine_ops)"
        ))
        # Add document_type column to existing tables without data loss
        await conn.execute(text(
            "ALTER TABLE rp_ndis_policy_chunks "
            "ADD COLUMN IF NOT EXISTS document_type VARCHAR(100) DEFAULT 'Regulatory'"
        ))
