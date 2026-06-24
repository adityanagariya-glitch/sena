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


def get_ws_auth(websocket: WebSocket) -> OnboardingAuthContext:
    """Extract identity from WebSocket headers.

    jwt_enabled=true   — validates RS256 Bearer token from Authorization header
                         or ?token= query param (for clients that can't set headers).
    jwt_enabled=false  — reads X-Tenant-Id / X-User-Id directly (dev only).
    """
    if not settings.jwt_enabled:
        # Dev mode: trust raw headers (never reachable in production)
        tenant_raw = websocket.headers.get("x-tenant-id") or websocket.query_params.get("tenant_id", "")
        user_raw = websocket.headers.get("x-user-id") or websocket.query_params.get("user_id", "")
        if not tenant_raw or not user_raw:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Dev mode: X-Tenant-Id and X-User-Id headers required",
            )
        try:
            return OnboardingAuthContext(
                tenant_id=UUID(tenant_raw),
                user_id=UUID(user_raw),
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid UUID header: {exc}") from exc

    # JWT mode
    raw = websocket.headers.get("authorization") or websocket.query_params.get("token", "")
    token = raw.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token (Authorization: Bearer <jwt>)",
        )

    if not settings.jwt_public_key_pem:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT_PUBLIC_KEY_PEM not configured",
        )

    try:
        payload = pyjwt.decode(
            token,
            settings.jwt_public_key_pem,
            algorithms=["RS256"],
            issuer=settings.jwt_issuer or pyjwt.api_jwt.PyJWT.OPTIONS_DEFAULT["verify_iss"],  # type: ignore[attr-defined]
            audience=settings.jwt_audience,
            options={"verify_iss": bool(settings.jwt_issuer), "verify_aud": bool(settings.jwt_audience)},
        )
    except pyjwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="JWT token expired") from exc
    except pyjwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid JWT: {exc}") from exc

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
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"JWT claim not a valid UUID: {exc}") from exc


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

    jwt_enabled=true   — validates RS256 Bearer token only.
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

    token = creds.credentials
    if not settings.jwt_public_key_pem:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT_PUBLIC_KEY_PEM not configured",
        )

    try:
        payload = pyjwt.decode(
            token,
            settings.jwt_public_key_pem,
            algorithms=["RS256"],
            issuer=settings.jwt_issuer or pyjwt.api_jwt.PyJWT.OPTIONS_DEFAULT["verify_iss"],  # type: ignore[attr-defined]
            audience=settings.jwt_audience,
            options={"verify_iss": bool(settings.jwt_issuer), "verify_aud": bool(settings.jwt_audience)},
        )
    except pyjwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="JWT token expired") from exc
    except pyjwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid JWT: {exc}") from exc

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
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"JWT claim not a valid UUID: {exc}") from exc
