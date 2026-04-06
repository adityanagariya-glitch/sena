"""Standard API response schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ResponseMetadata(BaseModel):
    request_id: str = ""
    tenant_id: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ApiResponse(BaseModel, Generic[T]):
    """Standard response envelope for all API endpoints."""

    status: str  # "success" or "error"
    data: T | None = None
    error: dict[str, Any] | None = None
    metadata: ResponseMetadata = Field(default_factory=ResponseMetadata)


class HealthResponse(BaseModel):
    service: str
    version: str
    status: str  # "healthy" or "unhealthy"
    database: str  # "connected" or "disconnected"
