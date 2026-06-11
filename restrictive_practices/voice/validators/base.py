"""Shared types for server-side field validation."""
from __future__ import annotations

from pydantic import BaseModel


class ValidationRejection(BaseModel):
    code: str
    reason_human: str
    suggested_fix: str | None = None
    allowed_values: list[str] | None = None
