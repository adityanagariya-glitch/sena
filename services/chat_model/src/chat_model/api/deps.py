from dataclasses import dataclass
from uuid import UUID
from typing import AsyncGenerator, Optional

import jwt
import redis.asyncio as redis
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from chat_model.core.settings import settings
from chat_model.services.chat_service import ChatService


@dataclass(frozen=True)
class AuthContext:
    """Authentication context extracted from request headers."""
    tenant_id: UUID
    user_id: UUID
    role: str


def _parse_uuid(value: str, field: str) -> UUID:
    """Parse and validate UUID value."""
    try:
        return UUID(value)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid {field}"
        ) from exc


def get_auth_context_from_dev_headers(
    x_tenant_id: Optional[str] = None,
    x_user_id: Optional[str] = None,
    x_user_role: Optional[str] = None,
) -> AuthContext:
    """Parse auth context from dev headers."""
    if not x_tenant_id or not x_user_id or not x_user_role:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing tenant/user headers (X-Tenant-ID, X-User-ID, X-User-Role)"
        )
    return AuthContext(
        tenant_id=_parse_uuid(x_tenant_id, "tenant_id"),
        user_id=_parse_uuid(x_user_id, "user_id"),
        role=x_user_role,
    )


def get_auth_context_from_jwt(authorization: Optional[str]) -> AuthContext:
    """Parse auth context from JWT bearer token."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid bearer token"
        )
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
    role = str(payload.get("role", "user"))

    return AuthContext(tenant_id=tenant_id, user_id=user_id, role=role)


async def auth_context_dependency(
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-ID"),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-ID"),
    x_user_role: Optional[str] = Header(default=None, alias="X-User-Role"),
) -> AuthContext:
    """Extract auth context from headers based on auth mode."""
    if settings.auth_mode == "jwt":
        return get_auth_context_from_jwt(authorization)
    return get_auth_context_from_dev_headers(x_tenant_id, x_user_id, x_user_role)


# Singleton instances
_chat_service: Optional[ChatService] = None
_redis_client: Optional[redis.Redis] = None
_db_engine = None
_async_session_maker = None


async def initialize_chat_service(redis_client: redis.Redis) -> ChatService:
    """Initialize singleton chat service on app startup."""
    global _chat_service
    _chat_service = ChatService(redis_client)
    return _chat_service


async def get_chat_service() -> ChatService:
    """Get singleton chat service instance."""
    if _chat_service is None:
        raise RuntimeError("Chat service not initialized. Call initialize_chat_service on app startup.")
    return _chat_service


async def get_redis_client() -> redis.Redis:
    """Get Redis client instance."""
    if _redis_client is None:
        raise RuntimeError("Redis client not initialized. Call initialize_redis_client on app startup.")
    return _redis_client


async def initialize_redis_client() -> redis.Redis:
    """Initialize Redis client on app startup."""
    global _redis_client
    _redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


async def shutdown_redis_client() -> None:
    """Close Redis client on app shutdown."""
    if _redis_client is not None:
        await _redis_client.aclose()


async def initialize_db_engine() -> None:
    """Initialize database engine on app startup."""
    global _db_engine, _async_session_maker
    _db_engine = create_async_engine(settings.ai_db_url, echo=False, future=True)
    _async_session_maker = async_sessionmaker(_db_engine, class_=AsyncSession, expire_on_commit=False)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Get database session for dependency injection."""
    if _async_session_maker is None:
        raise RuntimeError("Database not initialized. Call initialize_db_engine on app startup.")
    async with _async_session_maker() as session:
        yield session


async def shutdown_db_engine() -> None:
    """Close database engine on app shutdown."""
    if _db_engine is not None:
        await _db_engine.dispose()
