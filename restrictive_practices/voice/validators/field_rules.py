"""Per-field validation rules for the case-note voice assistant."""
from __future__ import annotations

from typing import Any

from .base import ValidationRejection


def validate_field(
    section_id: str,
    field_id: str,
    value: Any,
    *,
    repeatable_index: int | None = None,
    state: Any,
    field_spec: Any = None,
) -> ValidationRejection | None:
    """Return None if valid, ValidationRejection if a rule fires.

    Currently validates only the injury_description cross-field constraint:
    when any_injuries is True in the same section, injury_description must
    be non-empty. The visible_if mechanism handles gating at completion
    check time; this guard fires if the field is present but blank.
    """
    if section_id == "safety" and field_id == "injury_description":
        safety = (state.values.get("safety") or {}) if hasattr(state, "values") else {}
        any_injuries_fv = safety.get("any_injuries") if isinstance(safety, dict) else None
        any_injuries = any_injuries_fv.get("value") if isinstance(any_injuries_fv, dict) else any_injuries_fv
        if any_injuries is True and not (value and str(value).strip()):
            return ValidationRejection(
                code="injury_description_required",
                reason_human="When an injury is recorded, please describe it briefly.",
                suggested_fix="Describe the injury in a few words.",
            )
    return None
