"""Request ID middleware — generates or propagates a correlation ID for every request."""

from __future__ import annotations

import uuid
from contextvars import ContextVar

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

_request_id_var: ContextVar[str] = ContextVar("request_id", default="")

REQUEST_ID_HEADER = "X-Request-ID"


def get_request_id() -> str:
    """Get the current request ID."""
    return _request_id_var.get()


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware that generates or propagates a request correlation ID."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Use incoming request ID if provided, otherwise generate one
        request_id = request.headers.get(REQUEST_ID_HEADER, str(uuid.uuid4()))

        token = _request_id_var.set(request_id)
        try:
            response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            _request_id_var.reset(token)
