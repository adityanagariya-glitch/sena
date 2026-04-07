"""Tenant context middleware — propagates tenant_id from request to DB session.

This is the single most critical piece of shared infrastructure. Every request
(except health checks) must carry a tenant identifier. The middleware:
1. Extracts tenant_id from the request (via header in dev, JWT in prod)
2. Stores it in a context variable for the duration of the request
3. Sets the Postgres session variable so RLS policies can enforce isolation
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Protocol

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

# Context variable — accessible anywhere in the request lifecycle
_tenant_context_var: ContextVar["TenantContext | None"] = ContextVar(
    "tenant_context", default=None
)


@dataclass(frozen=True)
class TenantContext:
    """Immutable tenant context for the current request."""

    tenant_id: uuid.UUID
    user_id: str
    role: str


def get_tenant_context() -> TenantContext:
    """Get the current tenant context. Raises if not set."""
    ctx = _tenant_context_var.get()
    if ctx is None:
        raise RuntimeError(
            "Tenant context not set. Are you outside of a request, "
            "or did the request bypass the tenant middleware?"
        )
    return ctx


def get_tenant_id() -> uuid.UUID:
    """Convenience: get just the tenant_id from the current context."""
    return get_tenant_context().tenant_id


class TenantResolver(Protocol):
    """Protocol for extracting tenant context from a request.

    Implementations:
    - HeaderTenantResolver: reads from X-Tenant-ID header (local dev)
    - JWTTenantResolver: validates JWT and extracts claims (production)
    """

    async def resolve(self, request: Request) -> TenantContext: ...


class HeaderTenantResolver:
    """Dev/test resolver — reads tenant info from request headers.

    NOT for production use. No authentication is performed.
    """

    async def resolve(self, request: Request) -> TenantContext:
        tenant_id_str = request.headers.get("X-Tenant-ID")
        if not tenant_id_str:
            raise ValueError("Missing X-Tenant-ID header")

        try:
            tenant_id = uuid.UUID(tenant_id_str)
        except ValueError:
            raise ValueError(f"Invalid tenant ID format: {tenant_id_str}")

        user_id = request.headers.get("X-User-ID", "anonymous")
        role = request.headers.get("X-User-Role", "unknown")

        return TenantContext(tenant_id=tenant_id, user_id=user_id, role=role)


class JWTTenantResolver:
    """Production resolver — validates JWT and extracts tenant claims.

    TODO: Implement after client confirms auth system.
    Depends on: QUESTIONS_FOR_CLIENT.md §2.1
    """

    async def resolve(self, request: Request) -> TenantContext:
        raise NotImplementedError(
            "JWT validation not yet implemented. "
            "Waiting on auth system confirmation from platform team."
        )


# Paths that skip tenant context (health checks, OpenAPI docs)
_EXEMPT_PATHS: set[str] = {"/health", "/docs", "/openapi.json", "/redoc"}


class TenantMiddleware(BaseHTTPMiddleware):
    """Middleware that extracts and propagates tenant context for every request."""

    def __init__(self, app: ASGIApp, resolver: TenantResolver) -> None:
        super().__init__(app)
        self.resolver = resolver

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Skip tenant enforcement for exempt paths
        if request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        try:
            context = await self.resolver.resolve(request)
        except (ValueError, NotImplementedError) as e:
            from sena_common.schemas.errors import error_response

            return error_response(
                status_code=401,
                code="TENANT_RESOLUTION_FAILED",
                message=str(e),
            )

        # Set the context variable for this request
        token = _tenant_context_var.set(context)
        try:
            response = await call_next(request)
            return response
        finally:
            _tenant_context_var.reset(token)
