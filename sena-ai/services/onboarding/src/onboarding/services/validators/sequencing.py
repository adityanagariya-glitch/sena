"""Server-side sequencing helpers — pure functions, no I/O."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .base import ValidationRejection
from .field_rules import validate_field

if TYPE_CHECKING:
    from onboarding.models.form_state import FormState
    from onboarding.models.schema_spec import SectionSpec, StepSchema


def _has_value(raw: Any) -> bool:
    if raw is None:
        return False
    if isinstance(raw, dict):
        v = raw.get("value")
        if v is None:
            return False
        if isinstance(v, str) and not v.strip():
            return False
        if isinstance(v, list) and not v:
            return False
        return True
    if isinstance(raw, str):
        return bool(raw.strip())
    if isinstance(raw, list):
        return bool(raw)
    return True


def next_required_field(schema: StepSchema, state: FormState) -> dict | None:
    """First required field with no value, walking schema sections in order.

    Returns {"section_id", "field_id", "label"} or None when all required fields filled.
    """
    for section in schema.sections:
        is_rep = getattr(section, "is_repeatable", False)
        fields = section.item_fields if is_rep else (section.fields or [])
        sec_vals = state.values.get(section.id) or {}
        row: dict = (sec_vals[0] if isinstance(sec_vals, list) and sec_vals else {}) if is_rep else (sec_vals if isinstance(sec_vals, dict) else {})

        for field in fields:
            if not field.required:
                continue
            if field.visible_if:
                cond_f, cond_v = next(iter(field.visible_if.items()))
                actual_raw = row.get(cond_f) if isinstance(row, dict) else None
                actual = actual_raw.get("value") if isinstance(actual_raw, dict) else actual_raw
                if actual != cond_v:
                    continue
            raw = row.get(field.id) if isinstance(row, dict) else None
            if not _has_value(raw):
                return {"section_id": section.id, "field_id": field.id, "label": field.label}
    return None


def next_optional_field(schema: StepSchema, state: FormState) -> dict | None:
    """First optional (required=False) field with no value, in schema order.

    Rule-5 anchor: returns a deterministic next-optional pointer so the prompt
    model iterates optional fields predictably. Mirrors next_required_field shape.
    Returns None when every optional is filled (or the step has none).
    """
    for section in schema.sections:
        is_rep = getattr(section, "is_repeatable", False)
        fields = section.item_fields if is_rep else (section.fields or [])
        sec_vals = state.values.get(section.id) or {}
        row: dict = (sec_vals[0] if isinstance(sec_vals, list) and sec_vals else {}) if is_rep else (sec_vals if isinstance(sec_vals, dict) else {})

        for field in fields:
            if field.required:
                continue
            raw = row.get(field.id) if isinstance(row, dict) else None
            if not _has_value(raw):
                return {"section_id": section.id, "field_id": field.id, "label": field.label}
    return None


def section_min_unmet(section: SectionSpec, section_values: Any) -> bool:
    """Return True when a repeatable section has fewer rows than its declared minimum.

    Always returns False for non-repeatable sections or sections with min=0.
    Robust against section_values being None, a plain dict, or an empty list.
    """
    if not getattr(section, "is_repeatable", False):
        return False
    rep = getattr(section, "repeatable", None)
    if rep is None or getattr(rep, "min", 0) == 0:
        return False
    min_rows: int = rep.min
    rows = section_values if isinstance(section_values, list) else []
    return len(rows) < min_rows


def validate_step_complete(schema: StepSchema, state: FormState) -> list[ValidationRejection]:
    """Aggregate gate for /complete — returns [] only if every required field passes.

    Runs field validators AND cross-field invariants. Fails closed.
    """
    from .cross_field import validate_cross_fields

    rejections: list[ValidationRejection] = []
    for section in schema.sections:
        is_rep = getattr(section, "is_repeatable", False)
        fields = section.item_fields if is_rep else (section.fields or [])
        sec_vals = state.values.get(section.id) or {}
        rows = sec_vals if (is_rep and isinstance(sec_vals, list)) else ([sec_vals] if isinstance(sec_vals, dict) else [{}])

        for row_idx, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            for field in fields:
                if field.visible_if:
                    cond_f, cond_v = next(iter(field.visible_if.items()))
                    actual_raw = row.get(cond_f)
                    actual = actual_raw.get("value") if isinstance(actual_raw, dict) else actual_raw
                    if actual != cond_v:
                        continue
                raw = row.get(field.id)
                if field.required and not _has_value(raw):
                    rejections.append(ValidationRejection(
                        code="required_field_missing",
                        reason_human="This field is required.",
                        suggested_fix=f"Please provide a value for {field.label}.",
                    ))
                    continue
                value = raw.get("value") if isinstance(raw, dict) else raw
                if value is not None:
                    rej = validate_field(section.id, field.id, value,
                                         repeatable_index=row_idx if is_rep else None, state=state)
                    if rej:
                        rejections.append(rej)

    rejections.extend(validate_cross_fields(state.values))
    return rejections
