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
    "update_field", "clear_field", "add_row", "delete_row", "submit_step",
})


FUNCTION_DECLS: list[dict[str, Any]] = [
    {
        "name": "update_field",
        "description": (
            "REQUIRED whenever the participant provides ANY value to save or change "
            "(name, date, phone, email, address, gender, language, relation, etc). "
            "Call this BEFORE speaking any confirmation. Do not apologise for save "
            "failures unless this function returned {ok:false}. "
            "Examples: user says '1st December 1999' → call update_field("
            "section='basics', field='date_of_birth', value='1999-12-01'). "
            "User says 'Sibling' for a contact relation → call update_field("
            "section='emergency_contacts', field='relation', repeatable_index=N, "
            "value='Sibling'). User says 'change my first name to Devi' → call "
            "update_field(section='basics', field='full_name', value='Devi'). "
            "Mobile validates and returns {ok:true} on success or "
            "{ok:false, reason} on failure — speak reason verbatim on rejection."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "description": "Section id from visible_fields path before the '.' (e.g. 'basics', 'home_address', 'emergency_contacts').",
                },
                "field": {
                    "type": "string",
                    "description": "Field id from visible_fields path after the '.' (e.g. 'date_of_birth', 'phone', 'relation'). Use EXACT id, never invent variants.",
                },
                "value": {
                    "description": "The captured value. Dates as YYYY-MM-DD. Enums must match enum_values exactly (case-sensitive). Multi-enums as array.",
                },
                "repeatable_index": {
                    "type": "integer",
                    "description": "0-based row index for repeatable sections (emergency_contacts, etc). Omit for scalar fields.",
                },
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
