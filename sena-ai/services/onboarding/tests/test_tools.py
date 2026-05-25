from __future__ import annotations

from typing import Any

import pytest

from onboarding.services.tools import _KNOWN_TOOLS, FUNCTION_DECLS, ToolDispatcher


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
