"""Tests for services/screen_context.py — pure module, no mocks needed."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from onboarding.services.screen_context import (
    ScreenData,
    ScreenStateMessage,
    payload_hash,
    render_injection_text,
)


# ── render_injection_text ─────────────────────────────────────────────────────

def test_render_all_fields():
    msg = ScreenStateMessage(
        type="screen_state",
        data=ScreenData(
            current_screen="personal_information",
            visible_fields=["full_name", "date_of_birth"],
            prefilled={"full_name": "John Smith"},
            app_context="user is on step 1 of 5",
        ),
    )
    text = render_injection_text(msg)
    assert text.startswith("[SCREEN]")
    assert "section=personal_information" in text
    assert "visible=full_name,date_of_birth" in text
    assert "prefilled={full_name=John Smith}" in text
    assert 'note="user is on step 1 of 5"' in text


def test_render_minimal_no_optional_fields():
    msg = ScreenStateMessage(type="screen_state", data=ScreenData())
    text = render_injection_text(msg)
    assert text == "[SCREEN] ."


def test_render_only_screen():
    msg = ScreenStateMessage(
        type="screen_state",
        data=ScreenData(current_screen="medical_information"),
    )
    text = render_injection_text(msg)
    assert "section=medical_information" in text
    assert "visible=" not in text


def test_render_prefilled_only():
    msg = ScreenStateMessage(
        type="screen_state",
        data=ScreenData(prefilled={"dob": "1990-01-15"}),
    )
    text = render_injection_text(msg)
    assert "prefilled={dob=1990-01-15}" in text


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
