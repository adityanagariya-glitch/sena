from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from uuid import UUID
from fastapi import Header, HTTPException, status

from voice.core.settings import settings


@dataclass(frozen=True)
class AuthContext:
    tenant_id: UUID
    user_id: UUID
    role: str
    staff_id: UUID | None


def _parse_uuid(value: str, field: str) -> UUID:
    try:
        return UUID(value)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid {field}"
        ) from exc


# ── Simple JWT: read claims from the header, no public key ─────────────────────
# The SENA gateway issues/validates the token signature upstream; this service
# only needs the identity claims. So we base64-decode the payload (signature NOT
# re-verified) and enforce expiry. No public key / issuer / audience config.
# A well-formed, unexpired token with the required claims → allow; else → 401.

_KNOWN_ROLES = ("admin", "manager", "support_worker")


def _decode_jwt_claims(token: str) -> dict:
    """Base64-decode a JWT payload segment. No signature verification."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("malformed JWT (expected 3 segments)")
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)  # restore base64 padding
    return json.loads(base64.urlsafe_b64decode(payload))


def _pick_role(claims: dict) -> str:
    """Normalise the role/roles claim to one of voice's known role strings.

    Accepts a single `role` string or a `roles` list (of strings or
    {id, name} dicts). Normalises ("Support Worker" → "support_worker") and
    returns the highest-privilege known role found, else "support_worker"
    so any validly-authenticated caller can use the standard endpoints.
    """
    raw: list[str] = []
    single = claims.get("role")
    if single:
        raw.append(str(single))
    roles_claim = claims.get("roles")
    if isinstance(roles_claim, list):
        for r in roles_claim:
            if isinstance(r, dict):
                val = r.get("name") or r.get("id")
                if val:
                    raw.append(str(val))
            elif r:
                raw.append(str(r))
    normalised = {r.strip().lower().replace(" ", "_").replace("-", "_") for r in raw}
    for known in _KNOWN_ROLES:  # admin > manager > support_worker
        if known in normalised:
            return known
    return "support_worker"


def get_auth_context_from_dev_headers(
    x_tenant_id: str | None,
    x_user_id: str | None,
    x_user_role: str | None,
    x_staff_id: str | None = None,
) -> AuthContext:
    if not x_tenant_id or not x_user_id or not x_user_role:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing tenant/user headers"
        )
    return AuthContext(
        tenant_id=_parse_uuid(x_tenant_id, "tenant_id"),
        user_id=_parse_uuid(x_user_id, "user_id"),
        role=x_user_role,
        staff_id=_parse_uuid(x_staff_id, "staff_id") if x_staff_id else None,
    )


def get_auth_context_from_jwt(authorization: str | None) -> AuthContext:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1]
    try:
        claims = _decode_jwt_claims(token)
    except Exception as exc:  # any decode failure is a 401
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {exc}"
        ) from exc

    exp = claims.get("exp")
    if exp is not None and time.time() > float(exp):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")

    # Platform claim names (same as onboarding / case_review):
    #   organizationId | tenantId | tenant_id → tenant
    #   userId | sub → user
    org_raw = claims.get("organizationId") or claims.get("tenantId") or claims.get("tenant_id")
    user_raw = claims.get("userId") or claims.get("sub")
    if not org_raw or not user_raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="JWT missing required claims (organizationId/tenantId, userId/sub)",
        )

    tenant_id = _parse_uuid(str(org_raw), "tenant_id")
    user_id = _parse_uuid(str(user_raw), "sub")
    role = _pick_role(claims)
    staff_claim = claims.get("staff_id")
    # Case-note flows treat the authenticated user as the staff member when no
    # explicit staff_id claim is present.
    staff_id = _parse_uuid(str(staff_claim), "staff_id") if staff_claim else user_id
    return AuthContext(tenant_id=tenant_id, user_id=user_id, role=role, staff_id=staff_id)


async def auth_context_dependency(
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    x_user_role: str | None = Header(default=None, alias="X-User-Role"),
    x_staff_id: str | None = Header(default=None, alias="X-Staff-ID"),
) -> AuthContext:
    if settings.auth_mode == "jwt":
        return get_auth_context_from_jwt(authorization)
    return get_auth_context_from_dev_headers(x_tenant_id, x_user_id, x_user_role, x_staff_id)


def require_roles(ctx: AuthContext, allowed: set[str]) -> None:
    if ctx.role not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden role")
