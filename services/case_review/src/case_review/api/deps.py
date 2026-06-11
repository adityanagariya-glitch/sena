from __future__ import annotations

import uuid

from fastapi import Header, HTTPException, status
from redis.asyncio import from_url as redis_from_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from case_review.clients.case_note_client import CaseNoteClient
from case_review.core.settings import settings
from case_review.models.schemas import AuthContext
from case_review.repositories.review_repo import ReviewRepo

from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession

# ── DB engine (ai-db, pgvector, port 5433) ────────────────────────────────────

_engine = create_async_engine(
    settings.ai_db_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)
_session_factory = async_sessionmaker(bind=_engine, expire_on_commit=False, class_=AsyncSession)

# ── Voice Redis (dedicated case_review instance — separate from onboarding) ────
# Lazy: from_url does not open a socket until the first command, so importing
# this module (and the REST test suite) never requires Redis to be running. The
# voice WS route builds FormStateRepo(voice_redis_client, key_prefix=
# "sena:case_review", tenant_id=<auth>) per session for NDIS tenant-scoped keys.
voice_redis_client = redis_from_url(settings.case_review_redis_url, decode_responses=True)


def get_voice_redis():
    """Dependency accessor for the dedicated case_review voice Redis client."""
    return voice_redis_client

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with _session_factory() as session:
        yield session

def get_repo(session: AsyncSession) -> ReviewRepo:
    return ReviewRepo(session)


# ── Stub case-note client ─────────────────────────────────────────────────────

def get_case_note_client() -> CaseNoteClient:
    return CaseNoteClient(stub=True)


# ── Auth (dev_header mode — pluggable seam for JWT later) ─────────────────────

async def get_auth_context(
    x_tenant_id: str = Header(default="aaaaaaaa-0000-0000-0000-000000000001", alias="X-Tenant-Id"),
    x_user_id: str = Header(default="bbbbbbbb-0000-0000-0000-000000000002", alias="X-User-Id"),
    x_user_roles: str = Header(default="worker", alias="X-User-Roles"),
) -> AuthContext:
    """
    Dev-header auth: caller passes X-Tenant-Id, X-User-Id, X-User-Roles.
    In production, swap this dep for JWT validation.
    """
    try:
        return AuthContext(
            tenant_id=uuid.UUID(x_tenant_id),
            user_id=uuid.UUID(x_user_id),
            roles=[r.strip() for r in x_user_roles.split(",")],
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid auth header: {exc}",
        ) from exc
