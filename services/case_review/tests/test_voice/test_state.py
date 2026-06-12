"""Tests for CaseNoteVoiceState."""
from __future__ import annotations

import pytest

from voice.schema import build_case_note_schema
from voice.state import CaseNoteVoiceState


def _make_state() -> CaseNoteVoiceState:
    return CaseNoteVoiceState(
        session_id="s-1",
        case_note_id="cn-1",
        worker_id="w-1",
        client_id="liam-1",
    )


def test_set_field_happy_path() -> None:
    state = _make_state()
    state.set_field("shift", "shift_date", "2026-05-21", source="voice", confidence=0.9, turn_id=1)
    fv = state.values["shift"]["shift_date"]
    assert fv["value"] == "2026-05-21"
    assert fv["confidence"] == 0.9
    assert fv["source"] == "voice"


def test_set_field_confidence_stamping() -> None:
    state = _make_state()
    state.set_field("wellbeing", "mood", "happy", source="voice", confidence=0.75, turn_id=2)
    fv = state.values["wellbeing"]["mood"]
    assert fv["confidence"] == 0.75
    assert fv["turn_id"] == 2


def test_clear_field() -> None:
    state = _make_state()
    state.set_field("shift", "shift_date", "2026-05-21", source="voice", confidence=1.0, turn_id=1)
    # Clearing is done by set_field with value=None (used by ToolDispatcher._clear_field)
    state.set_field("shift", "shift_date", None, source="voice", confidence=1.0, turn_id=2)
    fv = state.values.get("shift", {}).get("shift_date")
    assert fv is None or fv.get("value") is None


def test_recompute_completion_empty() -> None:
    state = _make_state()
    schema = build_case_note_schema()
    state.recompute_completion(schema)
    assert state.completion.required_total > 0
    assert state.completion.required_filled == 0


def test_recompute_completion_partial() -> None:
    state = _make_state()
    schema = build_case_note_schema()
    state.set_field("shift", "shift_date", "2026-05-21", source="voice", confidence=1.0, turn_id=1)
    state.recompute_completion(schema)
    assert state.completion.required_filled >= 1


def test_recompute_completion_full() -> None:
    state = _make_state()
    schema = build_case_note_schema()
    required_fields = [
        ("shift", "shift_date", "2026-05-21"),
        ("shift", "shift_time", "07:00-15:00"),
        ("shift", "worker_position", "Support Worker"),
        ("summary", "describe", "Morning shift at Liam's house."),
        ("activities", "assisted", "personal care, breakfast"),
        ("wellbeing", "mood", "settled"),
    ]
    for sec, fld, val in required_fields:
        state.set_field(sec, fld, val, source="voice", confidence=1.0, turn_id=1)
    state.recompute_completion(schema)
    assert state.completion.required_filled == state.completion.required_total


def test_to_case_note_payload_shape() -> None:
    state = _make_state()
    state.set_field("shift", "shift_date", "2026-05-21", source="voice", confidence=1.0, turn_id=1)
    state.set_field("wellbeing", "mood", "happy", source="voice", confidence=0.9, turn_id=2)
    payload = state.to_case_note_payload()
    assert "case_note_id" in payload
    assert "shift_date" in payload
    assert payload["shift_date"] == "2026-05-21"
    assert payload["mood"] == "happy"


def test_pending_confirmation_lock() -> None:
    state = _make_state()
    state.pending_confirmation = {
        "section_id": "wellbeing",
        "field_id": "mood",
        "value": "unsure",
        "confidence": 0.4,
        "turn_id": 1,
    }
    assert state.pending_confirmation is not None
    assert state.pending_confirmation["field_id"] == "mood"
