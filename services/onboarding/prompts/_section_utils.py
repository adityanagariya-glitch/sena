from __future__ import annotations

from typing import Callable, Literal

from onboarding.voice.turn_payload import VisibleField


def _is_empty(value: object) -> bool:
    """Return True if the value counts as empty: None, "", [], {}."""
    if value is None:
        return True
    if isinstance(value, str) and value == "":
        return True
    if isinstance(value, list) and len(value) == 0:
        return True
    if isinstance(value, dict) and len(value) == 0:
        return True
    return False


def section_complete(section_prefix: str, visible_fields: list[VisibleField]) -> bool:
    """True if all required non-readonly fields whose path starts with
    section_prefix + '.' have a non-null, non-empty value.
    Empty list, None, "", {} all count as empty."""
    prefix = section_prefix + "."
    for field in visible_fields:
        if not field.path.startswith(prefix):
            continue
        if not field.required or field.readonly:
            continue
        if _is_empty(field.value):
            return False
    return True


def has_unfilled_enums(field_paths: list[str], visible_fields: list[VisibleField]) -> bool:
    """True if ANY field in field_paths is still empty (None / "" / [] / {}).
    field_paths are full dot-paths like 'basics.gender' or 'emergency_contacts.relation'."""
    field_map = {f.path: f for f in visible_fields}
    for path in field_paths:
        field = field_map.get(path)
        if field is None:
            # Field not present in visible_fields — treat as unfilled
            return True
        if _is_empty(field.value):
            return True
    return False


def has_incomplete_rows(
    section_prefix: str, min_rows: int, visible_fields: list[VisibleField]
) -> bool:
    """True if the repeatable section has fewer than min_rows rows where ALL
    required non-readonly fields have values.

    A 'row' is a set of fields sharing the same repeatable_index.
    Fields must have section == section_prefix (or path starts with section_prefix + '[').

    min_rows=0 means: True if there are ANY rows with at least one required
    field still empty (i.e., a started-but-incomplete row exists).
    """
    # Collect fields belonging to this repeatable section
    section_fields = [
        f
        for f in visible_fields
        if f.section == section_prefix or f.path.startswith(section_prefix + "[")
    ]

    if not section_fields:
        # No rows at all
        if min_rows == 0:
            return False  # No incomplete rows
        return True  # Need min_rows complete rows but have zero

    # Group by repeatable_index
    rows: dict[int | None, list[VisibleField]] = {}
    for field in section_fields:
        idx = field.repeatable_index
        rows.setdefault(idx, []).append(field)

    def row_is_complete(fields: list[VisibleField]) -> bool:
        for f in fields:
            if not f.required or f.readonly:
                continue
            if _is_empty(f.value):
                return False
        return True

    if min_rows == 0:
        # True if any row has at least one required field that is empty
        for row_fields in rows.values():
            for f in row_fields:
                if not f.required or f.readonly:
                    continue
                if _is_empty(f.value):
                    return True
        return False

    complete_count = sum(1 for row_fields in rows.values() if row_is_complete(row_fields))
    return complete_count < min_rows


def needs_guidance(field_path: str, visible_fields: list[VisibleField]) -> bool:
    """True if the field is empty OR if the field is not found in visible_fields.
    field_path is a full dot-path."""
    field_map = {f.path: f for f in visible_fields}
    field = field_map.get(field_path)
    if field is None:
        return True
    return _is_empty(field.value)


def form_completion_tier(visible_fields: list[VisibleField]) -> Literal["early", "mid", "late"]:
    """Classify form completion state.
    Count required non-readonly fields that have a non-null/non-empty value.
    early  — filled_ratio <= 0.30
    mid    — 0.30 < filled_ratio < 0.70
    late   — filled_ratio >= 0.70
    If there are no required non-readonly fields, return 'late'."""
    candidates = [f for f in visible_fields if f.required and not f.readonly]
    total_count = len(candidates)
    if total_count == 0:
        return "late"
    filled_count = sum(1 for f in candidates if not _is_empty(f.value))
    filled_ratio = filled_count / total_count
    if filled_ratio <= 0.30:
        return "early"
    if filled_ratio < 0.70:
        return "mid"
    return "late"


def step(
    *,
    always: list[str],
    if_incomplete: list[tuple[str, int, str]] | None = None,
    if_unfilled: tuple[list[str], str] | None = None,
    if_no_error: bool = False,
) -> Callable:
    """Decorator that composes a build(visible_fields) -> str function.

    always: list of text blocks always included.
    if_incomplete: list of (section_prefix, min_rows, text_block) — include
        text_block when has_incomplete_rows(section_prefix, min_rows, vf) is True.
    if_unfilled: (field_paths, text_block) — include when has_unfilled_enums is True.
    if_no_error: reserved for future use (pass False / omit).

    The decorated function body is NOT called — the decorator replaces it with
    the composed builder. The decorated function's signature must be
    `def build(visible_fields: list[VisibleField]) -> str`.

    Usage:
        @step(
            always=[_FIELD_TABLES],
            if_incomplete=[("emergency_contacts", 1, _WALKTHROUGH)],
            if_unfilled=(["basics.gender"], _ENUM_EXAMPLES),
        )
        def build(visible_fields: list[VisibleField]) -> str: ...
        PROMPT = build
    """

    def decorator(fn: Callable) -> Callable:
        def build(visible_fields: list[VisibleField]) -> str:
            parts: list[str] = list(always)

            if if_incomplete:
                for section_prefix, min_rows, text_block in if_incomplete:
                    if has_incomplete_rows(section_prefix, min_rows, visible_fields):
                        parts.append(text_block)

            if if_unfilled is not None:
                field_paths, text_block = if_unfilled
                if has_unfilled_enums(field_paths, visible_fields):
                    parts.append(text_block)

            return "\n\n".join(parts)

        build.__name__ = fn.__name__
        build.__doc__ = fn.__doc__
        return build

    return decorator
