from __future__ import annotations

import base64
import json
import time
import uuid
from typing import AsyncGenerator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import from_url as redis_from_url

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.backends import default_backend
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False
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


# ── Auth (JWT only) ─────────────────────────────────────────────────────────
# Identity comes from the Authorization: Bearer token's claims
# (organizationId → tenant, userId → user, roles → roles). Matches the staff
# service: the payload is base64-decoded (signature NOT verified — the SENA
# gateway issues/validates tokens upstream); we only enforce expiry.


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


# HTTP Bearer scheme — declared so the OpenAPI/Swagger spec advertises auth
# (adds the "Authorize" button + per-operation lock icons). auto_error=False so we
# emit our own 401 detail rather than FastAPI's generic "Not authenticated".
_bearer_scheme = HTTPBearer(
    auto_error=False,
    description="SENA JWT — claims: organizationId, userId, roles, exp.",
)


def _auth_from_jwt(token: str | None) -> AuthContext:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token (expected 'Authorization: Bearer <jwt>')",
            headers={"WWW-Authenticate": "Bearer"},
        )

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
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> AuthContext:
    """Resolve the caller's identity from the Authorization: Bearer JWT."""
    return _auth_from_jwt(creds.credentials if creds else None)


def get_bearer_token(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str:
    """Raw bearer token to forward to member-scoped org-backend calls.

    Validation is handled by get_auth_context; this just extracts the token string.
    """
    return creds.credentials if creds else ""


# ── Signature auth (RSA public-key) ────────────────────────────────────────────

async def verify_signature_auth(request: Request) -> AuthContext:
    """Verify request signature using RSA public key.

    User signs the request body with their private key; we verify using the
    public key from settings. Signature sent in X-Signature header (base64-encoded).
    Returns a synthetic AuthContext (tenant/user = "signature-verified").
    """
    if not HAS_CRYPTO:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cryptography library not installed",
        )

    if not settings.evaluate_public_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Signature auth not configured (missing SENA_AI_EVALUATE_PUBLIC_KEY)",
        )

    sig_header = request.headers.get("X-Signature")
    if not sig_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Signature header",
        )

    body = await request.body()
    if not body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body is empty",
        )

    try:
        sig_bytes = base64.b64decode(sig_header)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid X-Signature encoding: {exc}",
        ) from exc

    try:
        public_key = serialization.load_pem_public_key(
            settings.evaluate_public_key.encode(),
            backend=default_backend(),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to load public key: {exc}",
        ) from exc

    try:
        public_key.verify(
            sig_bytes,
            body,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Signature verification failed: {exc}",
        ) from exc

    # Signature valid — return a synthetic context (no user/tenant from signature)
    return AuthContext(
        tenant_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        user_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
        roles=["signature-verified"],
    )
