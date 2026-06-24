"""Tool dispatcher for the onboarding voice agent (v2).

Six tools. Mobile is authoritative. The dispatcher is a thin proxy that
hands every tool call to MobileBridge, except escalate_incident which is a
pure backend side-effect (audit + alert).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol

import structlog

log = structlog.get_logger(__name__)


class _Bridge(Protocol):
    async def dispatch(self, tool: str, args: dict[str, Any]) -> dict[str, Any]: ...


_KNOWN_TOOLS = frozenset(
    {
        "update_field",
        "clear_field",
        "add_row",
        "delete_row",
        "submit_step",
        "get_current_state",
        "confirm_dialog",
    }
)


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
                    "description": (
                        "Section id from visible_fields path before the "
                        "'.' (e.g. 'basics', 'home_address', "
                        "'emergency_contacts')."
                    ),
                },
                "field": {
                    "type": "string",
                    "description": (
                        "Field id from visible_fields path after the '.' "
                        "(e.g. 'date_of_birth', 'phone', 'relation'). Use "
                        "EXACT id, never invent variants."
                    ),
                },
                "value": {
                    "type": "string",
                    "description": (
                        "The captured value, ALWAYS encoded as a string. "
                        "Numbers (NDIS number '309362545', durations '8') → "
                        "decimal-digit string. Dates → 'YYYY-MM-DD'. Enums → "
                        "exact case-sensitive enum_values entry. Booleans → "
                        "'true'/'false'. Multi-enums → JSON array string "
                        "'[\"A\",\"B\"]'. NEVER emit a raw integer/boolean — "
                        "wrap in quotes. The mobile sink converts to the "
                        "target field type."
                    ),
                },
                "repeatable_index": {
                    "type": "integer",
                    "description": (
                        "0-based row index for repeatable sections "
                        "(emergency_contacts, etc). Omit for scalar fields."
                    ),
                },
            },
            "required": ["section", "field", "value"],
        },
    },
    {
        "name": "clear_field",
        "description": (
            "Blank out a previously-filled scalar field. Call this whenever the "
            "participant wants a single value REMOVED or RESET — phrased ANY way: "
            "'clear my email', 'remove the phone number', 'scrap that', 'delete "
            "what I said', 'wipe it', 'leave it blank', 'take that out', 'never "
            "mind that one'. To CHANGE a value to something new, use update_field "
            "instead — only use clear_field when nothing should replace it."
        ),
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
        "description": (
            "Add a new row to a repeatable section. Call this whenever the "
            "participant wants ANOTHER entry — phrased ANY way: 'add another "
            "contact', 'one more', 'I have a second emergency contact', 'put "
            "another one', 'there's also my sister', 'can I add more'. Creates "
            "an empty row; then use update_field with the new repeatable_index "
            "to fill it."
        ),
        "parameters": {
            "type": "object",
            "properties": {"section": {"type": "string"}},
            "required": ["section"],
        },
    },
    {
        "name": "delete_row",
        "description": (
            "Remove a row from a repeatable section. Call this whenever the "
            "participant wants a whole entry GONE — phrased ANY way: 'delete the "
            "second contact', 'pop that one off', 'get rid of the last one', "
            "'remove that entry', 'scrap the sibling one', 'take it off the "
            "list', 'drop that'. Use row_index for which row (0-based); if the "
            "participant says 'the last one' use the highest index."
        ),
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
            "Submit the current step and advance to the next. Mobile checks "
            "every required field + cross-field rule, returns {ok:true} or "
            "{ok:false, blockers:[{path,label,reason},...]}; on blockers read "
            "the FIRST blocker's reason verbatim and ask the user to fix it. "
            "Backward navigation by voice is TEMPORARILY DISABLED — if the "
            "participant asks to go back / previous step / previous page, "
            "say: 'Going back by voice is paused — please tap the back arrow "
            "on the screen.' Do NOT call submit_step with direction='back'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "confirmation_transcript": {"type": "string"},
                # `direction` retained in schema for forward-compat but only
                # "forward" is accepted while voice back-nav is paused.
                "direction": {
                    "type": "string",
                    "enum": ["forward"],
                    "description": "Only forward is supported right now.",
                },
            },
            "required": ["confirmation_transcript"],
        },
    },
    {
        "name": "get_current_state",
        "description": (
            "Re-read the participant's full current form state. Call this if "
            "your most recent function_response is more than 3 turns ago and "
            "you are about to assert any field value, OR if the participant "
            "says something that suggests the form has changed outside of "
            "voice (e.g. they say 'I just typed it in'). Mobile returns "
            "{ok: true, state: {...}} with the freshest snapshot — treat its "
            "`state` field as your new source of truth, superseding anything "
            "in the bootstrap state block."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "confirm_dialog",
        "description": (
            "Answer a yes/no confirmation dialog that is CURRENTLY shown on the "
            "screen — e.g. the 'Are you sure you want to continue?' popup raised "
            "after Continue on the consent sharing screen. decision='yes' taps "
            "the affirmative button and proceeds; decision='no' taps the negative "
            "button and dismisses the dialog, staying on the current screen. Only "
            "call this when such a dialog is actually visible — do NOT use it to "
            "advance a normal step (use submit_step for that). Mobile returns "
            "{ok:true} once the dialog is resolved, or {ok:false, reason} if no "
            "dialog was open."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "decision": {
                    "type": "string",
                    "enum": ["yes", "no"],
                    "description": "yes taps confirm/continue; no taps cancel/dismiss.",
                },
            },
            "required": ["decision"],
        },
    },
    {
        "name": "escalate_incident",
        "description": ("Flag abuse / self-harm / safety concerns. Continue calmly after."),
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
        known_tools: frozenset[str] = _KNOWN_TOOLS,
        submit_tool_name: str = "submit_step",
    ) -> None:
        self._bridge = bridge
        self._on_incident = on_incident
        # Injectable per flow (T4/T7): onboarding keeps the defaults; case_review
        # passes its own tool set + "finalize_note" as the submit/loop-exit tool.
        self._known_tools = known_tools
        self._submit_tool_name = submit_tool_name
        # Loop-exit flag — gemini_live.py polls this after each tool call to end
        # the WS session once the submit/finalize tool succeeds. Set True when the
        # tool named ``submit_tool_name`` returns {ok: True}.
        self.step_completed: bool = False
        self._turn_id: int = 0

    def set_turn_id(self, turn_id: int) -> None:
        self._turn_id = turn_id

    async def dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "escalate_incident":
            if self._on_incident is not None:
                self._on_incident(args)
            return {"ok": True}
        if name not in self._known_tools:
            log.warning("unknown_tool_called", tool=name)
            return {"ok": False, "reason": f"Unknown tool: {name}", "code": "unknown_tool"}

        # Pre-flight arg shape check. The Live API tool-runtime returns a
        # synthetic "(System Error: Please fix the argument type for `value`.)"
        # message when the model emits a malformed call — the model has been
        # observed reading that error aloud to the participant. Catching the
        # bad shape here and returning a clean {ok:false, reason} lets the
        # model recover via the normal rejection path without any meta-text
        # ever entering its context.
        validation_err = _preflight_validate(name, args)
        if validation_err is not None:
            log.info(
                "tool_arg_preflight_rejected", tool=name, reason=validation_err,
            )
            return {
                "ok": False,
                "reason": validation_err,
                "code": "arg_validation",
            }

        result = await self._bridge.dispatch(name, args)
        if name == self._submit_tool_name and result.get("ok") is True:
            self.step_completed = True
        return result


def _preflight_validate(name: str, args: dict[str, Any]) -> str | None:
    """Return a human-friendly reason if args are malformed, else None.

    Catches the common Gemini Live argument-shape mistakes BEFORE the call
    reaches the mobile bridge, so the runtime never emits its parenthetical
    error template into the model's context.
    """
    if name in ("update_field", "clear_field"):
        section = args.get("section")
        field = args.get("field")
        if not isinstance(section, str) or not section:
            return "section must be a non-empty string."
        if not isinstance(field, str) or not field:
            return "field must be a non-empty string."
        idx = args.get("repeatable_index")
        if idx is not None and not isinstance(idx, int):
            return "repeatable_index must be an integer."
    if name == "update_field":
        # `value` may be string / number / bool / list / null depending on the
        # field type — the only outright illegal shape is `dict` or a missing
        # arg. Mobile validates the semantic type per field. Tool schema asks
        # the model to send a string; if it sends a bare int/bool/float anyway
        # (observed: NDIS number sent as int → Gemini SDK emits "Argument
        # 'value' had unspecified type (model generated STRING)" and the model
        # then parrots that error to the user), coerce it here so the mobile
        # bridge always receives a string.
        if "value" not in args:
            return "value is required for update_field."
        v = args["value"]
        if isinstance(v, dict):
            return (
                "value must be a scalar (string, number, boolean) or an array "
                "for multi-enum fields. Pass the user-supplied value directly."
            )
        if isinstance(v, bool):
            args["value"] = "true" if v else "false"
        elif isinstance(v, (int, float)):
            # int(309362545) → "309362545"; float(8.0) → "8" not "8.0".
            args["value"] = (
                str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)
            )
        elif isinstance(v, str):
            # Multi-enum fields: the schema tells the model to send a JSON array
            # STRING ('["English"]'), but the mobile sink consumes a real List
            # (`raw is List`) — it does not jsonDecode. Parse the stringified
            # array into a real list here so the value crosses the bridge in the
            # shape mobile validates. Scoped to `[...]`-looking strings that
            # parse to a list; scalars (dates, NDIS numbers, phones, plain enums)
            # never match and are relayed untouched.
            stripped = v.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                try:
                    parsed = json.loads(stripped)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, list):
                    args["value"] = parsed
    if name == "add_row":
        if not isinstance(args.get("section"), str) or not args.get("section"):
            return "section must be a non-empty string for add_row."
    if name == "delete_row":
        if not isinstance(args.get("section"), str) or not args.get("section"):
            return "section must be a non-empty string for delete_row."
        idx = args.get("row_index")
        if idx is not None and not isinstance(idx, int):
            return "row_index must be an integer."
    if name == "submit_step":
        ct = args.get("confirmation_transcript")
        if not isinstance(ct, str) or not ct.strip():
            return (
                "confirmation_transcript must be the participant's exact words "
                "confirming submission."
            )
    if name == "confirm_dialog" and args.get("decision") not in ("yes", "no"):
        return "decision must be 'yes' or 'no'."
    return None
