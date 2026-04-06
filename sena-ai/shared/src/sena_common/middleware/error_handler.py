"""Global error handling middleware for FastAPI services."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class TenantIsolationError(Exception):
    """Raised when a tenant isolation boundary is violated."""

    pass


class ResourceNotFoundError(Exception):
    """Raised when a requested resource does not exist."""

    def __init__(self, resource: str, identifier: str) -> None:
        self.resource = resource
        self.identifier = identifier
        super().__init__(f"{resource} not found: {identifier}")


def _build_error_body(
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "status": "error",
        "data": None,
        "error": {
            "code": code,
            "message": message,
        },
    }
    if details:
        body["error"]["details"] = details
    return body


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    details = [
        {
            "field": " -> ".join(str(loc) for loc in err["loc"]),
            "message": err["msg"],
            "type": err["type"],
        }
        for err in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content=_build_error_body(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Request validation failed",
            details=details,
        ),
    )


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=_build_error_body(
            status_code=exc.status_code,
            code="HTTP_ERROR",
            message=str(exc.detail),
        ),
    )


async def tenant_isolation_handler(
    request: Request, exc: TenantIsolationError
) -> JSONResponse:
    logger.critical(
        "TENANT ISOLATION VIOLATION",
        extra={"path": request.url.path},
    )
    return JSONResponse(
        status_code=403,
        content=_build_error_body(
            status_code=403,
            code="TENANT_ISOLATION_VIOLATION",
            message="Access denied",
        ),
    )


async def resource_not_found_handler(
    request: Request, exc: ResourceNotFoundError
) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content=_build_error_body(
            status_code=404,
            code="RESOURCE_NOT_FOUND",
            message=str(exc),
        ),
    )


async def unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    logger.exception("Unhandled exception", extra={"path": request.url.path})
    return JSONResponse(
        status_code=500,
        content=_build_error_body(
            status_code=500,
            code="INTERNAL_ERROR",
            message="An unexpected error occurred",
        ),
    )
