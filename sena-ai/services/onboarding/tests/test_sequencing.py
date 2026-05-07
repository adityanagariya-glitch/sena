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
