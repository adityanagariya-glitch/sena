"""Database session factory — creates async sessions with tenant context.

Every database session automatically sets the Postgres session variable
`app.current_tenant` so that RLS policies can enforce tenant isolation.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine(database_url: str, **kwargs: Any) -> AsyncEngine:
    """Initialize the async engine. Call once at application startup."""
    global _engine, _session_factory

    _engine = create_async_engine(
        database_url,
        echo=False,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        **kwargs,
    )
    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return _engine


async def close_engine() -> None:
    """Close the engine. Call at application shutdown."""
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None


@asynccontextmanager
async def get_session(tenant_id: UUID) -> AsyncGenerator[AsyncSession, None]:
    """Get a database session with tenant context set for RLS.

    The session variable `app.current_tenant` is set immediately after
    connection checkout, before any queries execute. This ensures RLS
    policies can reference it via current_setting('app.current_tenant').
    """
    if _session_factory is None:
        raise RuntimeError("Database engine not initialized. Call init_engine() first.")

    async with _session_factory() as session:
        # Set the tenant context for RLS enforcement
        await session.execute(
            text("SET app.current_tenant = :tenant_id"),
            {"tenant_id": str(tenant_id)},
        )
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def get_session_no_tenant() -> AsyncGenerator[AsyncSession, None]:
    """Get a session WITHOUT tenant context. Use ONLY for:
    - Health checks
    - Alembic migrations
    - System-level operations that don't touch tenant data

    Any query against a tenant-scoped table will fail RLS checks
    because app.current_tenant is not set.
    """
    if _session_factory is None:
        raise RuntimeError("Database engine not initialized. Call init_engine() first.")

    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
