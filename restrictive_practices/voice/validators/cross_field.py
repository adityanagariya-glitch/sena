"""Cross-field validation rules for the case-note voice assistant."""
from __future__ import annotations

from typing import Any

from .base import ValidationRejection


def validate_cross_fields(state_values: dict[str, Any]) -> list[ValidationRejection]:
    """Run all cross-field rules. Returns empty list when all pass."""
    return []
