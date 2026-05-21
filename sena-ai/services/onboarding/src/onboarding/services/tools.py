"""Tool dispatcher for the onboarding voice agent (v2).

Six tools. Mobile is authoritative. The dispatcher is a thin proxy that
hands every tool call to MobileBridge, except escalate_incident which is a
pure backend side-effect (audit + alert).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

import structlog

log = structlog.get_logger(__name__)


class _Bridge(Protocol):
    async def dispatch(self, tool: str, args: dict[str, Any]) -> dict[str, Any]: ...


_KNOWN_TOOLS = frozenset({
    "propose_field", "clear_field", "add_row", "delete_row", "submit_step",
})


FUNCTION_DECLS: list[dict[str, Any]] = [
    {
        "name": "propose_field",
        "description": (
            "Save a value the participant just said into the named field. "
            "Mobile validates and returns {ok:true} or {ok:false, reason}. "
            "Speak the reason verbatim on rejection."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "section": {"type": "string"},
                "field": {"type": "string"},
                "value": {},
                "repeatable_index": {"type": "integer"},
            },
            "required": ["section", "field", "value"],
        },
    },
    {
        "name": "clear_field",
        "description": "Blank out a previously-filled scalar.",
        "parameters": {
            "type": "object",
            "properties": {
                "section": {"type": "string"},
                "field": {"type": "string"},
                "repeatable_index": {"type": "integer"},
            },
            "required": ["section", "field"],
        },
    },
    {
        "name": "add_row",
        "description": "Add a new row to a repeatable section.",
        "parameters": {
            "type": "object",
            "properties": {"section": {"type": "string"}},
            "required": ["section"],
        },
    },
    {
        "name": "delete_row",
        "description": "Remove a row from a repeatable section.",
        "parameters": {
            "type": "object",
            "properties": {
                "section": {"type": "string"},
                "row_index": {"type": "integer"},
            },
            "required": ["section"],
        },
    },
    {
        "name": "submit_step",
        "description": (
            "Submit the current step. Mobile checks every required field "
            "and cross-field rule. Returns {ok:true} or "
            "{ok:false, blockers:[{path,label,reason},...]}. "
            "On blockers, read the FIRST blocker's reason verbatim and ask "
            "the user to fix it."
        ),
        "parameters": {
            "type": "object",
            "properties": {"confirmation_transcript": {"type": "string"}},
            "required": ["confirmation_transcript"],
        },
    },
    {
        "name": "escalate_incident",
        "description": (
            "Flag abuse / self-harm / safety concerns. Continue calmly after."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {"type": "string"},
                "transcript_excerpt": {"type": "string"},
            },
            "required": ["reason", "transcript_excerpt"],
        },
    },
]


class ToolDispatcher:
    def __init__(
        self,
        *,
        bridge: _Bridge,
        on_incident: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        self._bridge = bridge
        self._on_incident = on_incident
        # Loop-exit flag — gemini_live.py polls this after each tool call to end
        # the WS session once the step is submitted. Set True when submit_step
        # returns {ok: True}.
        self.step_completed: bool = False
        self._turn_id: int = 0

    def set_turn_id(self, turn_id: int) -> None:
        self._turn_id = turn_id

    async def dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "escalate_incident":
            if self._on_incident is not None:
                self._on_incident(args)
            return {"ok": True}
        if name not in _KNOWN_TOOLS:
            log.warning("unknown_tool_called", tool=name)
            return {"ok": False, "reason": f"Unknown tool: {name}", "code": "unknown_tool"}
        result = await self._bridge.dispatch(name, args)
        if name == "submit_step" and result.get("ok") is True:
            self.step_completed = True
        return result
