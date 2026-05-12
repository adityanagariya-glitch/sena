"""Tests for sequencing helpers — pure functions, no I/O."""
from __future__ import annotations

import pytest

from onboarding.models.form_state import FormState
from onboarding.models.schema_spec import FieldSpec, FieldType, SectionSpec, StepSchema
from onboarding.services.validators.sequencing import next_optional_field


def _make_schema(required_field_id: str = "name", optional_field_id: str = "nickname") -> StepSchema:
    """Minimal schema with one required and one optional field in the same section."""
    return StepSchema(
        step_id="step1",
        step_label="Personal Info",
        progress_percent=10,
        sections=[
            SectionSpec(
                id="basics",
                label="Basics",
                fields=[
                    FieldSpec(id=required_field_id, type=FieldType.text, label="Full Name", required=True),
                    FieldSpec(id=optional_field_id, type=FieldType.text, label="Nickname", required=False),
                ],
            )
        ],
    )


def _make_state(session_id: str = "sid-1") -> FormState:
    return FormState(session_id=session_id, step_id="step1", participant_id="p-1")


# ── next_optional_field ───────────────────────────────────────────────────────


def test_next_optional_field_returns_first_empty_optional_in_schema_order() -> None:
    """With no values filled, next_optional_field points at the first optional field."""
    schema = _make_schema()
    state = _make_state()

    result = next_optional_field(schema, state)

    assert result is not None
    assert result["section_id"] == "basics"
    assert result["field_id"] == "nickname"
    assert result["label"] == "Nickname"


def test_next_optional_field_returns_none_when_all_optionals_filled() -> None:
    """When every optional field has a value, returns None."""
    schema = _make_schema()
    state = _make_state()
    state.values["basics"] = {"nickname": {"value": "Nikki"}}

    result = next_optional_field(schema, state)

    assert result is None


# ── section_min_unmet ────────────────────────────────────────────────────────
from onboarding.services.validators.sequencing import section_min_unmet  # noqa: E402


class _FakeRep:
    def __init__(self, min_val: int) -> None:
        self.min = min_val


class _FakeSection:
    def __init__(self, is_repeatable: bool = True, rep_min: int | None = None) -> None:
        self.is_repeatable = is_repeatable
        self.repeatable = _FakeRep(rep_min) if rep_min is not None else None


def test_section_min_unmet_non_repeatable() -> None:
    s = _FakeSection(is_repeatable=False)
    assert section_min_unmet(s, []) is False


def test_section_min_unmet_min_zero() -> None:
    s = _FakeSection(is_repeatable=True, rep_min=0)
    assert section_min_unmet(s, []) is False


def test_section_min_unmet_min_one_no_rows() -> None:
    s = _FakeSection(is_repeatable=True, rep_min=1)
    assert section_min_unmet(s, []) is True


def test_section_min_unmet_min_one_one_row() -> None:
    s = _FakeSection(is_repeatable=True, rep_min=1)
    assert section_min_unmet(s, [{"description": {"value": "Wake up"}}]) is False


def test_section_min_unmet_min_two_one_row() -> None:
    s = _FakeSection(is_repeatable=True, rep_min=2)
    assert section_min_unmet(s, [{"description": {"value": "Wake up"}}]) is True


def test_section_min_unmet_none_values() -> None:
    s = _FakeSection(is_repeatable=True, rep_min=1)
    assert section_min_unmet(s, None) is True  # None treated as 0 rows


def test_section_min_unmet_dict_values() -> None:
    s = _FakeSection(is_repeatable=True, rep_min=1)
    assert section_min_unmet(s, {"key": "val"}) is True  # dict (wrong type) treated as 0 rows
