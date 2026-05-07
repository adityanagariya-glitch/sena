"""Tests for prompt_builder token interpolation.

Uses a minimal stub template injected via monkeypatch so tests are not
sensitive to the full onboarding_system.md content.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from onboarding.models.form_state import FormState
from onboarding.models.schema_spec import FieldSpec, FieldType, SectionSpec, StepSchema
from onboarding.models.session_bootstrap import SessionBootstrap
from onboarding.services import prompt_builder as pb


# ── Helpers ───────────────────────────────────────────────────────────────────

_STUB_TEMPLATE = (
    "__PARTICIPANT_NAME__ "
    "__NEXT_OPTIONAL_FIELD__ "
    "__STEP_LABEL__ "
    "__SCHEMA_JSON__ "
    "__STATE_JSON__ "
    "__LIVE_STATE_JSON__ "
    "__CROSS_SCREEN_SUMMARY__ "
    "__BOOTSTRAP_MODE__ "
    "__GROUNDING_SECTION__ "
    "__VOICE_COVERAGE_SECTION__ "
    "__NEXT_REQUIRED_FIELD__ "
    "__PENDING_VALIDATION_ERRORS__"
)


def _make_schema() -> StepSchema:
    return StepSchema(
        step_id="step1",
        step_label="Personal Info",
        progress_percent=10,
        sections=[
            SectionSpec(
                id="basics",
                label="Basics",
                fields=[
                    FieldSpec(id="full_name", type=FieldType.text, label="Full Name", required=True),
                    FieldSpec(id="nickname", type=FieldType.text, label="Nickname", required=False),
                ],
            )
        ],
    )


def _make_state() -> FormState:
    return FormState(session_id="sid-1", step_id="step1", participant_id="p-1")


def _build(schema, state, bootstrap=None, monkeypatch=None):
    if monkeypatch:
        mock_path = MagicMock(spec=Path)
        mock_path.read_text.return_value = _STUB_TEMPLATE
        monkeypatch.setattr(pb, "_TEMPLATE_PATH", mock_path)
    return pb.build_system_prompt(schema, state, bootstrap=bootstrap)


# ── Token: __PARTICIPANT_NAME__ ───────────────────────────────────────────────


def test_participant_name_token_interpolated_when_present(monkeypatch) -> None:
    schema = _make_schema()
    state = _make_state()
    bootstrap = SessionBootstrap(participant_display_name="Jane")

    result = _build(schema, state, bootstrap=bootstrap, monkeypatch=monkeypatch)

    assert "Jane" in result
    assert "__PARTICIPANT_NAME__" not in result


def test_participant_name_token_falls_back_to_unknown_when_missing(monkeypatch) -> None:
    schema = _make_schema()
    state = _make_state()
    bootstrap = SessionBootstrap()  # no display name

    result = _build(schema, state, bootstrap=bootstrap, monkeypatch=monkeypatch)

    assert "unknown" in result
    assert "__PARTICIPANT_NAME__" not in result


# ── Token: __NEXT_OPTIONAL_FIELD__ ───────────────────────────────────────────


def test_next_optional_field_token_interpolated(monkeypatch) -> None:
    schema = _make_schema()
    state = _make_state()  # nickname not filled — next optional should appear

    result = _build(schema, state, monkeypatch=monkeypatch)

    assert "nickname" in result
    assert "__NEXT_OPTIONAL_FIELD__" not in result


def test_next_optional_field_token_empty_when_none_remain(monkeypatch) -> None:
    schema = _make_schema()
    state = _make_state()
    state.values["basics"] = {"nickname": {"value": "Nikki"}}  # optional filled

    result = _build(schema, state, monkeypatch=monkeypatch)

    # Token replaced with empty string; "nickname" may appear elsewhere in JSON
    assert "__NEXT_OPTIONAL_FIELD__" not in result
    # Specifically the token position should be empty (adjacent tokens collapse)
    assert "basics.nickname" not in result
