"""Standard error response helpers."""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    """Build a standard error JSONResponse."""
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
    return JSONResponse(status_code=status_code, content=body)
