"""Request context management using contextvars for thread/async-safe isolation.

Provides:
  - RequestContext: user_id, org_id, role, token
  - contextvars for thread/task-safe storage
  - cleanup utilities
"""
import contextvars
import logging
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

# Thread-safe context variables for per-request isolation
_request_context: contextvars.ContextVar["RequestContext"] = contextvars.ContextVar(
    "request_context", default=None
)


@dataclass
class RequestContext:
    """Isolated request state: auth claims, request metadata, timing."""
    user_id: str
    org_id: str
    role: str
    jwt_token: str
    request_id: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    metadata: dict = field(default_factory=dict)

    def __repr__(self) -> str:
        """String representation for logging."""
        return (
            f"RequestContext(user_id={self.user_id}, org_id={self.org_id}, "
            f"role={self.role}, request_id={self.request_id})"
        )


def set_request_context(ctx: RequestContext) -> None:
    """Store request context in contextvars."""
    _request_context.set(ctx)
    logger.debug(f"Request context set: {ctx}")


def get_request_context() -> Optional[RequestContext]:
    """Retrieve current request context (None if not set)."""
    return _request_context.get()


def clear_request_context() -> None:
    """Clear the request context (call after request handling)."""
    _request_context.set(None)
    logger.debug("Request context cleared")


def require_request_context() -> RequestContext:
    """Get request context, raise ValueError if not set."""
    ctx = get_request_context()
    if ctx is None:
        raise ValueError("No request context set. Did you forget AuthMiddleware?")
    return ctx
