"""Tests for the Mongo-forwarding usage chokepoint — no real DB."""
from __future__ import annotations

from typing import TYPE_CHECKING

import sena_common.usage_logger as usage_logger_mod
from sena_common.usage_logger import UsageFeature, emit_usage

if TYPE_CHECKING:
    import pytest


def test_mapping_prefers_participant_and_step() -> None:
    args = usage_logger_mod._mongo_autolog_args(
        {
            "participant_id": "p-1",
            "user_id": "staff-9",
            "step_id": "consent",
            "feature": "voice_onboarding",
            "prompt_tokens": 5000,
            "response_tokens": 800,
            "failure_reason": None,
        }
    )
    assert args == {
        "user": "p-1",
        "screenname": "consent",
        "input_token": 5000,
        "output_token": 800,
        "error": None,
    }


def test_mapping_falls_back_to_user_id_then_feature() -> None:
    args = usage_logger_mod._mongo_autolog_args(
        {"user_id": "staff-9", "feature": "case_note_summary", "prompt_tokens": 10}
    )
    assert args["user"] == "staff-9"
    assert args["screenname"] == "case_note_summary"
    assert args["output_token"] == 0  # absent → safe default


def test_emit_usage_forwards_full_record(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(usage_logger_mod, "_forward_to_mongo", captured.update)
    emit_usage(
        tenant_id="t-1",
        user_id="u-1",
        feature=UsageFeature.VOICE_ONBOARDING,
        model="gemini-3.1-flash-live-preview",
        session_id="s-1",
        prompt_tokens=7,
        response_tokens=3,
        step_id="screen_2",
        participant_id="p-9",
    )
    assert captured["prompt_tokens"] == 7
    assert captured["step_id"] == "screen_2"
    assert captured["participant_id"] == "p-9"  # extras flow through
    assert captured["feature"] == "voice_onboarding"


def test_kill_switch_prevents_pool_creation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SENA_AI_MONGO_USAGE_AUTOLOG", "0")
    monkeypatch.setattr(usage_logger_mod, "_mongo_pool", None)
    usage_logger_mod._forward_to_mongo({"prompt_tokens": 1})
    assert usage_logger_mod._mongo_pool is None  # never spun up → nothing sent
