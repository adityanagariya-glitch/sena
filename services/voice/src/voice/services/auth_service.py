from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID
import jwt
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
        payload = jwt.decode(
            token,
            settings.jwt_public_key_pem,
            algorithms=["RS256"],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from exc

    tenant_id = _parse_uuid(str(payload.get("tenant_id")), "tenant_id")
    user_id = _parse_uuid(str(payload.get("sub")), "sub")
    role = str(payload.get("role", "support_worker"))
    staff_claim = payload.get("staff_id")
    staff_id = _parse_uuid(str(staff_claim), "staff_id") if staff_claim else None
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
