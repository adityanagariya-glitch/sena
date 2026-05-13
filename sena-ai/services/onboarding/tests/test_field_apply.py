"""Tests for services/field_apply.build_envelope.

Added 2026-05-12 (Agent 03B). Verifies the ``input_method`` key is
surfaced verbatim when provided and OMITTED from the envelope when None
— this matters for the Flutter contract where older clients may not
understand the key but still tolerate its presence.
"""
from __future__ import annotations

import json
from pathlib import Path

from onboarding.models.schema_spec import StepSchema
from onboarding.services.field_apply import build_envelope

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _schema() -> StepSchema:
    raw = json.loads((FIXTURES / "schema_personal_information.json").read_text())
    return StepSchema.model_validate(raw)


def _envelope_for(value: object, input_method) -> dict | None:
    return build_envelope(
        "basics",
        "full_name",
        value,
        schema=_schema(),
        enforced=False,
        input_method=input_method,
    )


def test_envelope_includes_input_method_when_voice():
    env = _envelope_for("Jane Doe", "voice")
    assert env is not None
    assert env["input_method"] == "voice"


def test_envelope_includes_input_method_when_typed():
    env = _envelope_for("Jane Doe", "typed")
    assert env is not None
    assert env["input_method"] == "typed"


def test_envelope_omits_input_method_when_none():
    env = _envelope_for("Jane Doe", None)
    assert env is not None
    assert "input_method" not in env


def test_envelope_required_keys_present():
    env = _envelope_for("Jane Doe", "voice")
    assert env is not None
    required = {"type", "section_id", "field_id", "row_index", "value", "source", "confidence"}
    assert required.issubset(env.keys())
    assert env["type"] == "field_apply"
    assert env["source"] == "voice"


def test_envelope_returns_none_when_blocked_by_coverage():
    # voice_coverage is empty in schema_personal_information.json — enforced
    # should block emission entirely (None).
    env = build_envelope(
        "basics",
        "full_name",
        "Jane",
        schema=_schema(),
        enforced=True,
        input_method="voice",
    )
    assert env is None
