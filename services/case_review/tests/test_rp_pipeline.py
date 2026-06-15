"""Tests for pipeline triage response parsing (pure logic — no AWS calls)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from case_review.services.pipeline.triage import _extract_json, _run_triage


# ── _extract_json ──────────────────────────────────────────────────────────────

def test_extract_json_clean() -> None:
    text = '{"flagged": true, "action_summary": "Physical restraint detected"}'
    result = _extract_json(text)
    assert result["flagged"] is True
    assert "Physical" in result["action_summary"]


def test_extract_json_strips_markdown_fence() -> None:
    text = '```json\n{"flagged": false, "action_summary": null}\n```'
    result = _extract_json(text)
    assert result["flagged"] is False


def test_extract_json_with_leading_preamble() -> None:
    text = 'Here is the result: {"flagged": true, "action_summary": "seclusion"}'
    result = _extract_json(text)
    assert result["flagged"] is True
    assert result["action_summary"] == "seclusion"


def test_extract_json_no_object_raises() -> None:
    with pytest.raises(json.JSONDecodeError):
        _extract_json("No JSON here at all")


def test_extract_json_nested_object_returns_outer() -> None:
    text = '{"flagged": false, "action_summary": null, "meta": {"k": 1}}'
    result = _extract_json(text)
    assert result["flagged"] is False
    assert result["meta"]["k"] == 1


# ── _run_triage (mocked Bedrock) ───────────────────────────────────────────────

def _mock_bedrock_response(flagged: bool, summary: str | None) -> dict:
    payload = {"flagged": flagged, "action_summary": summary}
    return {
        "output": {
            "message": {"content": [{"text": json.dumps(payload)}]}
        }
    }


def test_run_triage_flagged(monkeypatch) -> None:
    mock_client = MagicMock()
    mock_client.converse.return_value = _mock_bedrock_response(
        True, "Chemical restraint suspected"
    )
    monkeypatch.setattr(
        "case_review.services.pipeline.triage._make_client",
        lambda: mock_client,
    )
    result = _run_triage("Worker gave medication to calm participant behaviour.")
    assert result.flagged is True
    assert result.action_summary == "Chemical restraint suspected"


def test_run_triage_clear(monkeypatch) -> None:
    mock_client = MagicMock()
    mock_client.converse.return_value = _mock_bedrock_response(False, None)
    monkeypatch.setattr(
        "case_review.services.pipeline.triage._make_client",
        lambda: mock_client,
    )
    result = _run_triage("Assisted participant with morning routine. No incidents.")
    assert result.flagged is False
    assert result.action_summary is None


def test_run_triage_empty_action_summary_normalised_to_none(monkeypatch) -> None:
    mock_client = MagicMock()
    mock_client.converse.return_value = _mock_bedrock_response(False, "")
    monkeypatch.setattr(
        "case_review.services.pipeline.triage._make_client",
        lambda: mock_client,
    )
    result = _run_triage("Normal shift notes.")
    # _run_triage normalises empty string → None
    assert result.action_summary is None
