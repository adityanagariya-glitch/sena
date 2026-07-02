from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import jwt as pyjwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.websockets import WebSocket
from redis.asyncio import from_url as redis_from_url

from onboarding.core.settings import settings
from voice.state_repo import FormStateRepo

redis_client = redis_from_url(settings.redis_url, decode_responses=True)


def get_repo() -> FormStateRepo:
    return FormStateRepo(redis_client)


# ── JWT auth for WebSocket endpoints ─────────────────────────────────────────

@dataclass(frozen=True)
class OnboardingAuthContext:
    tenant_id: UUID
    user_id: UUID


def _decode_claims(token: str) -> dict:
    """Read JWT claims WITHOUT signature verification.

    The platform gateway / auth server already verifies the signature before
    the request reaches this service — onboarding only needs the identity
    claims. So there is NO public key, shared secret, issuer or audience to
    configure: we just base64-decode the payload and trust it. Keep it simple.
    """
    try:
        return pyjwt.decode(token, options={"verify_signature": False})
    except pyjwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Malformed JWT: {exc}"
        ) from exc


def _context_from_claims(payload: dict) -> OnboardingAuthContext:
    """Map JWT claims → OnboardingAuthContext. Raises 401 on missing/invalid."""
    org_id = payload.get("organizationId") or payload.get("tenantId") or payload.get("tenant_id")
    user_id = payload.get("userId") or payload.get("sub")
    if not org_id or not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="JWT missing required claims (organizationId/tenantId, userId/sub)",
        )
    try:
        return OnboardingAuthContext(tenant_id=UUID(str(org_id)), user_id=UUID(str(user_id)))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=f"JWT claim not a valid UUID: {exc}"
        ) from exc


def get_ws_auth(websocket: WebSocket) -> OnboardingAuthContext:
    """Extract identity from WebSocket headers.

    jwt_enabled=true   — reads claims from the Bearer token (Authorization
                         header or ?token= query param). Signature is NOT
                         re-verified here (the gateway already did).
    jwt_enabled=false  — reads X-Tenant-Id / X-User-Id directly (dev only).
    """
    if not settings.jwt_enabled:
        # Dev mode: trust raw headers/query if present, else fall back to
        # defaults so local testing needs no auth wiring. Ownership enforcement
        # is also skipped in dev (see ws_routes), so these values are only used
        # as a best-effort identity hint.
        tenant_raw = (
            websocket.headers.get("x-tenant-id")
            or websocket.query_params.get("tenant_id")
            or "00000000-0000-0000-0000-000000000001"
        )
        user_raw = (
            websocket.headers.get("x-user-id")
            or websocket.query_params.get("user_id")
            or "00000000-0000-0000-0000-000000000002"
        )
        try:
            return OnboardingAuthContext(
                tenant_id=UUID(tenant_raw),
                user_id=UUID(user_raw),
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid UUID header: {exc}") from exc

    # JWT mode — pull the bearer token, decode its claims (no signature check).
    raw = websocket.headers.get("authorization") or websocket.query_params.get("token", "")
    token = raw.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token (Authorization: Bearer <jwt>)",
        )
    return _context_from_claims(_decode_claims(token))


def get_ws_jwt_claims(websocket: WebSocket) -> dict:
    """Extract full JWT claims from WebSocket for accessing typeContext and other fields.

    jwt_enabled=false — returns empty dict (dev mode, no real JWT).
    """
    if not settings.jwt_enabled:
        return {}

    raw = websocket.headers.get("authorization") or websocket.query_params.get("token", "")
    token = raw.removeprefix("Bearer ").strip()
    if not token:
        return {}

    try:
        return _decode_claims(token)
    except Exception:
        return {}


# ── HTTP Bearer auth (for REST routes) ─────────────────────────────────────

_http_bearer = HTTPBearer(
    auto_error=False,
    description="SENA JWT — claims: organizationId, userId, exp.",
)


async def get_http_auth(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_http_bearer),
) -> OnboardingAuthContext:
    """Extract identity from HTTP Authorization Bearer header (REST routes).

    jwt_enabled=true   — reads claims from the Bearer token (no signature check).
    jwt_enabled=false  — reads X-Tenant-Id / X-User-Id headers (dev only).
    """
    if not settings.jwt_enabled:
        # Dev mode: accept headers, or use defaults if missing
        tenant_raw = request.headers.get("x-tenant-id") or "00000000-0000-0000-0000-000000000001"
        user_raw = request.headers.get("x-user-id") or "00000000-0000-0000-0000-000000000002"
        try:
            return OnboardingAuthContext(
                tenant_id=UUID(tenant_raw),
                user_id=UUID(user_raw),
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid UUID: {exc}") from exc

    if not creds:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token (Authorization: Bearer <jwt>)",
        )
    return _context_from_claims(_decode_claims(creds.credentials))
