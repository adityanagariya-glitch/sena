from __future__ import annotations

from redis.asyncio import from_url as redis_from_url
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from voice.core.settings import settings


ai_engine = create_async_engine(
    settings.ai_db_url, pool_pre_ping=True, pool_size=10, max_overflow=20
)
shared_engine = create_async_engine(
    settings.shared_db_url, pool_pre_ping=True, pool_size=10, max_overflow=20
)
ai_session_factory = async_sessionmaker(bind=ai_engine, expire_on_commit=False, class_=AsyncSession)
shared_session_factory = async_sessionmaker(
    bind=shared_engine, expire_on_commit=False, class_=AsyncSession
)
redis_client = redis_from_url(settings.redis_url, decode_responses=True)


async def get_ai_db() -> AsyncSession:
    async with ai_session_factory() as session:
        yield session


async def get_shared_db() -> AsyncSession:
    async with shared_session_factory() as session:
        yield session
