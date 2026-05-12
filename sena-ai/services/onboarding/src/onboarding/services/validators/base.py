"""Shared types for server-side field validation."""
from __future__ import annotations

from pydantic import BaseModel


class ValidationRejection(BaseModel):
    code: str           # snake_case, e.g. "phone_invalid_format"
    reason_human: str   # exact AppStrings text (byte-for-byte match with Flutter)
    suggested_fix: str | None = None
    allowed_values: list[str] | None = None
