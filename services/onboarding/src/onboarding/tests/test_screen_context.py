"""Tests for services/screen_context.py — pure module, no mocks needed.

render_injection_text accepts ScreenStateV2. v1 ScreenStateMessage payloads
must be normalised through from_v1() before rendering.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from voice.screen_context import (
    ScreenData,
    ScreenStateMessage,
    ScreenStateV2,
    from_v1,
    payload_hash,
    render_injection_text,
)


# ── render_injection_text (v2 native) ────────────────────────────────────────

def test_render_all_fields():
    state = ScreenStateV2(
        step_id="personal_information",
        focused_section="basics",
        focused_field="full_name",
        field_status={
            "basics.full_name": "filled",
            "basics.date_of_birth": "empty",
        },
        repeatable_rows={"emergency_contacts": 2},
    )
    text = render_injection_text(state)
    assert text.startswith("[SCREEN]")
    assert "Step: personal_information" in text
    assert "Focus: basics / full_name" in text
    assert "Filled: basics.full_name" in text
    assert "Empty: basics.date_of_birth" in text
    assert "Rows: emergency_contacts=2" in text


def test_render_minimal_no_optional_fields():
    state = ScreenStateV2()
    text = render_injection_text(state)
    assert text == "[SCREEN]"


def test_render_only_step():
    state = ScreenStateV2(step_id="medical_information")
    text = render_injection_text(state)
    assert "Step: medical_information" in text
    assert "Focus:" not in text


def test_render_v1_via_adapter():
    msg = ScreenStateMessage(
        type="screen_state",
        data=ScreenData(prefilled={"dob": "1990-01-15"}),
    )
    state = from_v1(msg)
    text = render_injection_text(state)
    assert "Filled: dob" in text


# ── Rule 7 — field_errors render with hint ───────────────────────────────────

def test_render_invalid_with_field_errors_hint():
    state = ScreenStateV2(
        focused_section="basics",
        focused_field="phone",
        field_status={
            "basics.phone": "invalid",
            "basics.email": "invalid",
        },
        field_errors={
            "basics.phone": "Must be 10 digits with no spaces",
        },
    )
    text = render_injection_text(state)
    # Phone has a reason (rendered in parens); email is invalid but reason-less.
    invalid_line = next(line for line in text.splitlines() if line.startswith("Invalid"))
    assert "basics.phone (Must be 10 digits with no spaces)" in invalid_line
    # email appears bare (sorted alphabetically before phone, no reason)
    assert "basics.email," in invalid_line or invalid_line.endswith("basics.email")


def test_render_invalid_without_field_errors_is_bare():
    state = ScreenStateV2(
        field_status={"basics.phone": "invalid"},
    )
    text = render_injection_text(state)
    invalid_line = next(line for line in text.splitlines() if line.startswith("Invalid"))
    # Bare path — no parenthesised reason after the path itself.
    assert invalid_line == "Invalid (re-ask): basics.phone"


# ── Unknown keys ignored ───────────────────────────────────────────────────────

def test_unknown_keys_silently_ignored():
    msg = ScreenStateMessage(
        type="screen_state",
        data={"current_screen": "foo", "unknown_future_key": "bar"},  # type: ignore[arg-type]
    )
    assert msg.data.current_screen == "foo"


# ── visible_fields cap ────────────────────────────────────────────────────────

def test_visible_fields_exceeds_32_raises():
    with pytest.raises(ValidationError):
        ScreenData(visible_fields=[f"field_{i}" for i in range(33)])


def test_visible_fields_exactly_32_ok():
    d = ScreenData(visible_fields=[f"field_{i}" for i in range(32)])
    assert len(d.visible_fields) == 32  # type: ignore[arg-type]


# ── current_screen length cap ─────────────────────────────────────────────────

def test_current_screen_too_long_raises():
    with pytest.raises(ValidationError):
        ScreenData(current_screen="x" * 65)


# ── app_context length cap ────────────────────────────────────────────────────

def test_app_context_too_long_raises():
    with pytest.raises(ValidationError):
        ScreenData(app_context="x" * 257)


# ── payload_hash idempotency ──────────────────────────────────────────────────

def test_payload_hash_same_input_same_hash():
    data = {"current_screen": "foo", "visible_fields": ["a", "b"]}
    assert payload_hash(data) == payload_hash(data)


def test_payload_hash_different_input_different_hash():
    a = {"current_screen": "foo"}
    b = {"current_screen": "bar"}
    assert payload_hash(a) != payload_hash(b)


def test_payload_hash_key_order_independent():
    a = {"b": 1, "a": 2}
    b = {"a": 2, "b": 1}
    assert payload_hash(a) == payload_hash(b)
