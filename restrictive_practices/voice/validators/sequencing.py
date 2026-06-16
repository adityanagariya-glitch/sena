"""Server-side sequencing helpers — pure functions, no I/O."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .base import ValidationRejection
from .field_rules import validate_field

if TYPE_CHECKING:
    from voice.schema_spec import SectionSpec, StepSchema
    from voice.state import CaseNoteVoiceState


def _has_value(raw: Any) -> bool:
    if raw is None:
        return False
    if isinstance(raw, dict):
        v = raw.get("value")
        if v is None:
            return False
        if isinstance(v, str) and not v.strip():
            return False
        return not (isinstance(v, list) and not v)
    if isinstance(raw, str):
        return bool(raw.strip())
    if isinstance(raw, list):
        return bool(raw)
    return True


def next_required_field(
    schema: "StepSchema",
    state: "CaseNoteVoiceState",
    *,
    screen_field_status: dict[str, str] | None = None,
) -> dict | None:
    """First required field with no value, walking schema sections in order."""
    for section in schema.sections:
        fields = section.fields or []
        sec_vals = state.values.get(section.id) or {}
        row: dict = sec_vals if isinstance(sec_vals, dict) else {}

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
            if _has_value(raw):
                continue
            if screen_field_status is not None:
                path = f"{section.id}.{field.id}"
                if screen_field_status.get(path) == "filled":
                    continue
            return {"section_id": section.id, "field_id": field.id, "label": field.label}
    return None


def next_optional_field(
    schema: "StepSchema",
    state: "CaseNoteVoiceState",
    *,
    screen_field_status: dict[str, str] | None = None,
) -> dict | None:
    """First optional (required=False) field with no value, in schema order."""
    rendered_paths: set[str] | None = (
        set(screen_field_status.keys()) if screen_field_status else None
    )
    for section in schema.sections:
        fields = section.fields or []
        sec_vals = state.values.get(section.id) or {}
        row: dict = sec_vals if isinstance(sec_vals, dict) else {}

        for field in fields:
            if field.required:
                continue
            if field.visible_if:
                cond_f, cond_v = next(iter(field.visible_if.items()))
                actual_raw = row.get(cond_f) if isinstance(row, dict) else None
                actual = actual_raw.get("value") if isinstance(actual_raw, dict) else actual_raw
                if actual != cond_v:
                    continue
            if rendered_paths is not None:
                direct = f"{section.id}.{field.id}"
                if direct not in rendered_paths:
                    continue
            raw = row.get(field.id) if isinstance(row, dict) else None
            if not _has_value(raw):
                return {"section_id": section.id, "field_id": field.id, "label": field.label}
    return None


def section_min_unmet(section: "SectionSpec", section_values: Any) -> bool:
    """Always False for non-repeatable sections (case note has no repeatables)."""
    return False


def validate_step_complete(
    schema: "StepSchema",
    state: "CaseNoteVoiceState",
) -> list[ValidationRejection]:
    """Returns [] only if every required field passes."""
    from .cross_field import validate_cross_fields

    rejections: list[ValidationRejection] = []
    for section in schema.sections:
        fields = section.fields or []
        sec_vals = state.values.get(section.id) or {}
        row = sec_vals if isinstance(sec_vals, dict) else {}

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
                rej = validate_field(
                    section.id,
                    field.id,
                    value,
                    repeatable_index=None,
                    state=state,
                    field_spec=field,
                )
                if rej:
                    rejections.append(rej)

    rejections.extend(validate_cross_fields(state.values))
    return rejections


def validate_required_only(
    schema: "StepSchema",
    state: "CaseNoteVoiceState",
) -> list[ValidationRejection]:
    """Per-field required/validation rejections only — cross-field rules excluded."""
    rejections: list[ValidationRejection] = []
    for section in schema.sections:
        fields = section.fields or []
        sec_vals = state.values.get(section.id) or {}
        row = sec_vals if isinstance(sec_vals, dict) else {}

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
                rej = validate_field(
                    section.id,
                    field.id,
                    value,
                    repeatable_index=None,
                    state=state,
                    field_spec=field,
                )
                if rej:
                    rejections.append(rej)
    return rejections
