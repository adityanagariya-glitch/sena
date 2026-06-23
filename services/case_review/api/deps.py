from __future__ import annotations

import base64
import json
import time
import uuid
from typing import AsyncGenerator

from fastapi import Header, HTTPException, status
from redis.asyncio import from_url as redis_from_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from clients.case_note_client import CaseNoteClient
from core.settings import settings
from models.schemas import AuthContext
from repositories.review_repo import ReviewRepo

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


# ── Case-note client (fixtures in dev, org backend when stub disabled) ────────

def get_case_note_client() -> CaseNoteClient:
    return CaseNoteClient(stub=settings.case_note_use_stub)


# ── Auth ──────────────────────────────────────────────────────────────────────
# Two modes, selected by SENA_AI_AUTH_MODE:
#   "dev_header" (default) — trust X-Tenant-Id / X-User-Id / X-User-Roles headers.
#   "jwt"                  — read the Authorization: Bearer token and derive identity
#                            from its claims (organizationId → tenant, userId → user,
#                            roles → roles). Matches the staff service: the payload is
#                            base64-decoded (signature NOT verified — the SENA gateway
#                            issues/validates tokens upstream); we only enforce expiry.


def _decode_jwt(token: str) -> dict:
    """Decode a JWT payload (no signature verification — mirrors staff/auth.py)."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("malformed JWT (expected 3 segments)")
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)  # restore base64 padding
    return json.loads(base64.urlsafe_b64decode(payload))


def _normalise_roles(raw: object) -> list[str]:
    """Roles claim may be a list of strings or of {id, name} dicts."""
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for r in raw:
        if isinstance(r, dict):
            val = r.get("name") or r.get("id")
            if val:
                out.append(str(val).strip().lower())
        elif r:
            out.append(str(r).strip().lower())
    return out


def _auth_from_jwt(authorization: str | None) -> AuthContext:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header (expected 'Bearer <token>')",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()

    try:
        claims = _decode_jwt(token)
    except Exception as exc:  # noqa: BLE001 — any decode failure is a 401
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid JWT: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    exp = claims.get("exp")
    if exp is not None and time.time() > float(exp):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="JWT token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )

    org_id = claims.get("organizationId") or claims.get("tenantId")
    user_id = claims.get("userId") or claims.get("sub")
    if not org_id or not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="JWT missing required claims (organizationId, userId)",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        return AuthContext(
            tenant_id=uuid.UUID(str(org_id)),
            user_id=uuid.UUID(str(user_id)),
            roles=_normalise_roles(claims.get("roles")),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"JWT claim is not a valid UUID: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def get_auth_context(
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_tenant_id: str = Header(default="aaaaaaaa-0000-0000-0000-000000000001", alias="X-Tenant-Id"),
    x_user_id: str = Header(default="bbbbbbbb-0000-0000-0000-000000000002", alias="X-User-Id"),
    x_user_roles: str = Header(default="worker", alias="X-User-Roles"),
) -> AuthContext:
    """
    Resolve the caller's identity.

    auth_mode == "jwt"        → from the Authorization: Bearer token's claims.
    auth_mode == "dev_header" → trust X-Tenant-Id / X-User-Id / X-User-Roles (default).
    """
    if settings.auth_mode == "jwt":
        return _auth_from_jwt(authorization)

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
