<<<<<<< HEAD
from __future__ import annotations

from typing import Any

import pytest

from onboarding.services.tools import (
    _KNOWN_TOOLS,
    FUNCTION_DECLS,
    ToolDispatcher,
    _preflight_validate,
)


class _FakeBridge:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def dispatch(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((tool, args))
        return self.response


def test_function_decls_lists_exactly_six_tools() -> None:
    names = {d["name"] for d in FUNCTION_DECLS}
    assert names == {
        "update_field",
        "clear_field",
        "add_row",
        "delete_row",
        "submit_step",
        "escalate_incident",
        "get_current_state",
    }
    assert {
        "update_field",
        "clear_field",
        "add_row",
        "delete_row",
        "submit_step",
        "get_current_state",
    } == _KNOWN_TOOLS


def test_function_decl_update_field_required_args() -> None:
    decl = next(d for d in FUNCTION_DECLS if d["name"] == "update_field")
    params = decl["parameters"]
    assert set(params["required"]) == {"section", "field", "value"}
    assert params["properties"]["repeatable_index"]["type"] == "integer"


def test_function_decl_submit_step_requires_transcript() -> None:
    decl = next(d for d in FUNCTION_DECLS if d["name"] == "submit_step")
    assert decl["parameters"]["required"] == ["confirmation_transcript"]


@pytest.mark.asyncio
async def test_dispatch_update_field_forwards_to_bridge() -> None:
    bridge = _FakeBridge({"ok": True})
    disp = ToolDispatcher(bridge=bridge)
    args = {"section": "basics", "field": "phone", "value": "0412"}
    out = await disp.dispatch("update_field", args)
    assert out == {"ok": True}
    assert bridge.calls == [("update_field", args)]


@pytest.mark.asyncio
async def test_dispatch_submit_step_returns_blockers_verbatim() -> None:
    blockers = [
        {
            "path": "basics.profile_picture",
            "label": "Profile Photo",
            "reason": "Profile photo is required",
        }
    ]
    bridge = _FakeBridge({"ok": False, "blockers": blockers})
    disp = ToolDispatcher(bridge=bridge)
    out = await disp.dispatch("submit_step", {"confirmation_transcript": "I'm done"})
    assert out == {"ok": False, "blockers": blockers}


@pytest.mark.asyncio
async def test_dispatch_unknown_tool_returns_error() -> None:
    bridge = _FakeBridge({"ok": True})
    disp = ToolDispatcher(bridge=bridge)
    out = await disp.dispatch("invent_field", {})
    assert out["ok"] is False
    assert out["code"] == "unknown_tool"


@pytest.mark.asyncio
async def test_escalate_incident_does_not_call_bridge() -> None:
    bridge = _FakeBridge({"ok": True})
    incidents: list[dict[str, Any]] = []
    disp = ToolDispatcher(bridge=bridge, on_incident=lambda args: incidents.append(args))
    out = await disp.dispatch(
        "escalate_incident",
        {
            "reason": "self_harm",
            "transcript_excerpt": "...",
        },
    )
    assert out == {"ok": True}
    assert bridge.calls == []
    assert incidents == [{"reason": "self_harm", "transcript_excerpt": "..."}]


@pytest.mark.asyncio
async def test_step_completed_flips_on_successful_submit() -> None:
    bridge = _FakeBridge({"ok": True})
    disp = ToolDispatcher(bridge=bridge)
    assert disp.step_completed is False
    await disp.dispatch("submit_step", {"confirmation_transcript": "I'm done"})
    assert disp.step_completed is True


@pytest.mark.asyncio
async def test_step_completed_stays_false_when_submit_returns_blockers() -> None:
    blockers = [{"path": "x", "label": "X", "reason": "missing"}]
    bridge = _FakeBridge({"ok": False, "blockers": blockers})
    disp = ToolDispatcher(bridge=bridge)
    await disp.dispatch("submit_step", {"confirmation_transcript": "submit"})
    assert disp.step_completed is False


@pytest.mark.asyncio
async def test_step_completed_stays_false_for_non_submit_tools() -> None:
    bridge = _FakeBridge({"ok": True})
    disp = ToolDispatcher(bridge=bridge)
    await disp.dispatch("update_field", {"section": "basics", "field": "phone", "value": "0412"})
    assert disp.step_completed is False


def test_set_turn_id_stores_value() -> None:
    bridge = _FakeBridge({"ok": True})
    disp = ToolDispatcher(bridge=bridge)
    disp.set_turn_id(42)
    assert disp._turn_id == 42


# ── update_field multi-enum value coercion ─────────────────────────────────────
# The model is told to send multi-enums as a JSON array STRING ('["English"]'),
# but the mobile sink consumes a real List (`raw is List`). _preflight_validate
# parses the stringified array into a real list before it crosses the bridge.


def test_preflight_parses_stringified_multi_enum_array_to_list() -> None:
    args = {"section": "basics", "field": "preferred_languages", "value": '["English"]'}
    assert _preflight_validate("update_field", args) is None
    assert args["value"] == ["English"]


def test_preflight_parses_multi_value_array() -> None:
    args = {
        "section": "basics",
        "field": "preferred_languages",
        "value": '["English", "Mandarin"]',
    }
    assert _preflight_validate("update_field", args) is None
    assert args["value"] == ["English", "Mandarin"]


def test_preflight_passes_real_list_through_untouched() -> None:
    # If the model ever sends a native array, it must survive unchanged.
    args = {"section": "basics", "field": "preferred_languages", "value": ["English"]}
    assert _preflight_validate("update_field", args) is None
    assert args["value"] == ["English"]


@pytest.mark.parametrize(
    "value",
    [
        "English",  # scalar enum
        "1995-06-08",  # date
        "309362545",  # NDIS number as digit-string
        "+61412345678",  # phone
        "[unquoted]",  # not valid JSON → left as-is
    ],
)
def test_preflight_leaves_scalar_strings_untouched(value: str) -> None:
    args = {"section": "basics", "field": "x", "value": value}
    assert _preflight_validate("update_field", args) is None
    assert args["value"] == value
=======
"""
Tests for the Phase C tool dispatcher.

These tests bypass Gemini entirely — they exercise ToolDispatcher directly
with a FakeRedis-backed FormStateRepo, a captured emit function in place of
the WebSocket, and a monkeypatched `fire_webhook` to assert delivery.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio

from onboarding.models.form_state import FormState
from onboarding.models.schema_spec import StepSchema
from onboarding.repositories.state_repo import FormStateRepo
from onboarding.services import tools as tools_module
from onboarding.services.tools import FUNCTION_DECLS, ToolDispatcher

FIXTURES = Path(__file__).parent.parent / "fixtures"


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def personal_schema() -> StepSchema:
    return StepSchema.model_validate_json(
        (FIXTURES / "schema_personal_information.json").read_text()
    )


@pytest_asyncio.fixture
async def seeded_repo(fake_redis, personal_schema):
    """Repo with a fresh FormState + schema saved for session_id='sid-1'."""
    repo = FormStateRepo(fake_redis)
    state = FormState(
        session_id="sid-1",
        step_id=personal_schema.step_id,
        participant_id="p-1",
    )
    state.recompute_completion(personal_schema)
    await repo.create_session(state, personal_schema, ttl_sec=3600)
    return repo


@pytest.fixture
def emitted() -> list[dict]:
    """Captures every event the dispatcher would send over the WS."""
    return []


@pytest_asyncio.fixture
async def dispatcher(seeded_repo, personal_schema, emitted):
    async def capture(evt: dict) -> None:
        emitted.append(evt)

    return ToolDispatcher(
        websocket=None,  # unused — capture() replaces send_text
        session_id="sid-1",
        repo=seeded_repo,
        schema=personal_schema,
        emit=capture,
    )


# ── FUNCTION_DECLS shape ─────────────────────────────────────────────────────


def test_function_decls_cover_all_handlers() -> None:
    names = {d["name"] for d in FUNCTION_DECLS}
    assert names == {
        "update_field",
        "get_session_context",
        "advance_step",
        "escalate_incident",
        "add_repeatable_row",
    }
    for decl in FUNCTION_DECLS:
        assert decl["parameters"]["type"] == "object"
        assert "properties" in decl["parameters"]


# ── update_field ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_field_happy_path(dispatcher, seeded_repo, emitted) -> None:
    result = await dispatcher.dispatch(
        "update_field",
        {"section": "basics", "field": "full_name", "value": "Aditya", "confidence": 0.95},
    )
    assert result["ok"] is True
    assert result["required_filled"] == 1

    state = await seeded_repo.get_state("sid-1")
    assert state.values["basics"]["full_name"]["value"] == "Aditya"
    assert state.values["basics"]["full_name"]["confidence"] == 0.95

    types_emitted = [e["type"] for e in emitted]
    assert "field_updated" in types_emitted
    assert "state" in types_emitted


@pytest.mark.asyncio
async def test_update_field_coerces_boolean(dispatcher, seeded_repo) -> None:
    await dispatcher.dispatch(
        "update_field",
        {"section": "basics", "field": "interpreter_required", "value": "yes"},
    )
    state = await seeded_repo.get_state("sid-1")
    assert state.values["basics"]["interpreter_required"]["value"] is True


@pytest.mark.asyncio
async def test_update_field_unknown_section(dispatcher) -> None:
    result = await dispatcher.dispatch(
        "update_field",
        {"section": "does_not_exist", "field": "x", "value": "y"},
    )
    assert result["ok"] is False
    assert "unknown section" in result["error"]


@pytest.mark.asyncio
async def test_update_field_unknown_field(dispatcher) -> None:
    result = await dispatcher.dispatch(
        "update_field",
        {"section": "basics", "field": "does_not_exist", "value": "y"},
    )
    assert result["ok"] is False
    assert "not in section" in result["error"]


@pytest.mark.asyncio
async def test_update_field_repeatable_with_index(dispatcher, seeded_repo) -> None:
    await dispatcher.dispatch(
        "update_field",
        {
            "section": "emergency_contacts",
            "field": "name",
            "value": "Sarah Brown",
            "repeatable_index": 0,
        },
    )
    await dispatcher.dispatch(
        "update_field",
        {
            "section": "emergency_contacts",
            "field": "name",
            "value": "Tom Brown",
            "repeatable_index": 1,
        },
    )
    state = await seeded_repo.get_state("sid-1")
    contacts = state.values["emergency_contacts"]
    assert isinstance(contacts, list)
    assert len(contacts) == 2
    assert contacts[0]["name"]["value"] == "Sarah Brown"
    assert contacts[1]["name"]["value"] == "Tom Brown"


@pytest.mark.asyncio
async def test_update_field_repeatable_exceeds_max(dispatcher) -> None:
    result = await dispatcher.dispatch(
        "update_field",
        {
            "section": "emergency_contacts",
            "field": "name",
            "value": "X",
            "repeatable_index": 10,  # max is 5
        },
    )
    assert result["ok"] is False
    assert "exceeds max" in result["error"]


# ── get_session_context ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_session_context_reports_progress(dispatcher) -> None:
    await dispatcher.dispatch(
        "update_field",
        {"section": "basics", "field": "full_name", "value": "Aditya"},
    )
    result = await dispatcher.dispatch("get_session_context", {})
    assert result["ok"] is True
    assert result["filled"]["basics.full_name"] == "Aditya"
    assert "basics.email" in result["missing_required"]
    assert result["required_filled"] >= 1


# ── advance_step ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_advance_step_rejects_when_incomplete(dispatcher) -> None:
    result = await dispatcher.dispatch(
        "advance_step", {"confirmation_transcript": "that's all"}
    )
    assert result["ok"] is False
    assert "unfilled" in result["error"]
    assert dispatcher.step_completed is False


@pytest.mark.asyncio
async def test_advance_step_fires_webhook_when_complete(
    dispatcher, seeded_repo, personal_schema, emitted, monkeypatch
) -> None:
    # Fill every field visible to recompute_completion as "required"
    fills = {
        ("basics", "full_name"): "Aditya",
        ("basics", "email"): "a@b.com",
        ("basics", "phone"): "+61400000000",
        ("basics", "date_of_birth"): "1990-01-01",
        ("basics", "gender"): "Male",
        ("basics", "bio"): "hello",
        ("basics", "preferred_language"): "English",
        ("basics", "interpreter_required"): "false",
        ("home_address", "address"): "1 Example St",
        ("home_address", "state"): "NSW",
        ("home_address", "city"): "Sydney",
        ("home_address", "zip_code"): "2000",
    }
    for (sec, fld), val in fills.items():
        await dispatcher.dispatch(
            "update_field", {"section": sec, "field": fld, "value": val}
        )

    # Repeatable: at least one emergency contact (all 4 fields)
    for field, value in [
        ("name", "Sarah"),
        ("relation", "Parent"),
        ("email", "s@b.com"),
        ("phone", "+61400111222"),
    ]:
        await dispatcher.dispatch(
            "update_field",
            {
                "section": "emergency_contacts",
                "field": field,
                "value": value,
                "repeatable_index": 0,
            },
        )

    # Stub the webhook so we don't hit the network
    fired: dict = {}

    async def fake_fire_webhook(**kwargs):
        fired.update(kwargs)
        return True

    monkeypatch.setattr(tools_module, "fire_webhook", fake_fire_webhook)

    result = await dispatcher.dispatch(
        "advance_step", {"confirmation_transcript": "that's everything, thanks"}
    )
    assert result["ok"] is True
    assert result["webhook_delivered"] is True
    assert dispatcher.step_completed is True
    assert fired["event"] == "onboarding.session.completed"
    assert fired["payload"]["step"] == "personal_information"
    assert fired["payload"]["confirmation_transcript"] == "that's everything, thanks"

    state = await seeded_repo.get_state("sid-1")
    assert state.completed is True
    assert state.completed_at is not None

    assert any(e["type"] == "step_completed" for e in emitted)


# ── escalate_incident ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_escalate_incident_appends_and_emits(dispatcher, seeded_repo, emitted) -> None:
    result = await dispatcher.dispatch(
        "escalate_incident",
        {"reason": "self_harm", "transcript_excerpt": "I feel unsafe."},
    )
    assert result["ok"] is True

    state = await seeded_repo.get_state("sid-1")
    assert len(state.escalations) == 1
    assert state.escalations[0].reason == "self_harm"
    assert state.escalations[0].transcript_excerpt == "I feel unsafe."

    escalated = [e for e in emitted if e["type"] == "escalated"]
    assert len(escalated) == 1
    assert escalated[0]["reason"] == "self_harm"


# ── unknown tool ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_unknown_tool(dispatcher) -> None:
    result = await dispatcher.dispatch("frobnicate", {})
    assert result["ok"] is False
    assert "unknown tool" in result["error"]
>>>>>>> ai-chatbot
