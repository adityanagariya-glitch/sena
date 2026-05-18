"""
Tool dispatcher for the onboarding voice agent (Phase C).

Gemini Live calls one of four functions during a session:
  - update_field          Record a captured value into FormState
  - get_session_context   Return a condensed snapshot so the model can self-correct
  - advance_step          Step is done → fire webhook → close WS
  - escalate_incident     Abuse / self-harm / safety flag → log + continue

Integration points:
  - FUNCTION_DECLS is attached to LiveConnectConfig(tools=[...]) in gemini_live.py
  - The receive loop in gemini_live.py detects msg.tool_call, calls
    ToolDispatcher.dispatch(), then replies with session.send_tool_response(...)
  - Every mutation persists to Redis and emits a structured JSON event to the
    app WebSocket (field_updated / escalated / step_completed)

Design notes:
  - Pure async, no Gemini SDK imports here — keeps dispatch unit-testable
  - Handler return value = the dict sent back to the model as FunctionResponse
  - Side-effects (WS send, webhook) are awaited inside handlers so the model's
    next turn sees the updated state
"""
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

import structlog

from onboarding.core.settings import settings
from onboarding.models.form_state import (
    EscalationRecord,
    FieldSource,
    FormState,
)

if TYPE_CHECKING:
    from fastapi import WebSocket

    from onboarding.models.schema_spec import FieldSpec, SectionSpec, StepSchema
    from onboarding.models.session_bootstrap import SessionBootstrap
    from onboarding.repositories.state_repo import FormStateRepo

from onboarding.services import field_apply as _fa
from onboarding.services.coverage import is_repeatable_eligible
from onboarding.services.validators import validate_field as _validate_field
from onboarding.services.validators import validate_step_complete
from onboarding.services.validators.cross_field import (
    check_emergency_email_unique_and_differs_from_client as _ec_email_check,
)
from onboarding.services.validators.cross_field import (
    check_emergency_phone_unique_and_differs_from_client as _ec_phone_check,
)
from onboarding.services.validators.sequencing import (
    section_min_unmet as _section_min_unmet,
)
from onboarding.services.validators.sequencing import (
    validate_required_only as _validate_required_only,
)
from onboarding.services.webhook import fire_webhook

log = structlog.get_logger(__name__)


def _utcnow_iso() -> str:
    """ISO-8601 UTC timestamp for pending_confirmation.set_at."""
    return datetime.now(UTC).isoformat()


def _set_next_forced_field(
    state: FormState,
    schema: StepSchema,
    just_set_section: str,
    just_set_field: str,
    just_set_value: Any,
) -> None:
    """M5 — Conditional follow-up driver.

    After ``update_field`` commits a value, scan the schema for any field
    whose ``visible_if`` references the just-set field. When the unlock
    condition is satisfied AND the dependent field is still empty, write
    that dependent to ``state.next_forced_field`` so the prompt builder
    surfaces it as ``next_required_field`` on the next turn.

    Clears ``state.next_forced_field`` when the just-set field IS the
    previously-forced one (the directive is now satisfied).
    """
    # Clear if the forced field was the one just filled.
    forced = state.next_forced_field
    if (
        forced
        and forced.get("section") == just_set_section
        and forced.get("field") == just_set_field
    ):
        state.next_forced_field = None

    # Clear stale forced directive when the prerequisite reverts.
    # E.g. user said interpreter_required=true (we forced interpreter_language),
    # then changed their mind to interpreter_required=false. The forced
    # dependant is no longer visible — drop the directive so the agent
    # doesn't loop asking for a field that's now hidden.
    if state.next_forced_field is not None:
        forced_section = state.next_forced_field.get("section")
        forced_field = state.next_forced_field.get("field")
        if forced_section == just_set_section:
            for section in schema.sections:
                if section.id != forced_section:
                    continue
                is_rep = getattr(section, "is_repeatable", False)
                fields = (
                    section.item_fields if is_rep else (section.fields or [])
                )
                for f in fields:
                    if f.id != forced_field:
                        continue
                    vif = getattr(f, "visible_if", None)
                    if vif and just_set_field in vif:
                        expected = vif[just_set_field]
                        if not _matches_visible_if(expected, just_set_value):
                            state.next_forced_field = None
                break

    # Scan for dependants of the just-set field.
    for section in schema.sections:
        if section.id != just_set_section:
            # visible_if dependants live in the same section as their condition.
            continue
        is_rep = getattr(section, "is_repeatable", False)
        fields = section.item_fields if is_rep else (section.fields or [])
        for f in fields:
            vif = getattr(f, "visible_if", None)
            if not vif or just_set_field not in vif:
                continue
            # Does the just-set value satisfy the unlock condition?
            expected = vif[just_set_field]
            if _matches_visible_if(expected, just_set_value):
                # Is the dependent already filled?
                if _field_is_filled(state, section.id, f.id):
                    continue
                state.next_forced_field = {
                    "section": section.id,
                    "field": f.id,
                }
                return


def _matches_visible_if(expected: Any, actual: Any) -> bool:
    """Loose equality for visible_if conditions.

    Schemas express conditions as raw scalars (true/false, "string"). The
    stored value may be a coerced bool, a stringified bool, or the raw
    string. Normalise both sides before comparing.
    """
    def _norm(x: Any) -> Any:
        if isinstance(x, str) and x.lower() in ("true", "false"):
            return x.lower() == "true"
        return x
    return _norm(expected) == _norm(actual)


def _field_is_filled(state: FormState, section_id: str, field_id: str) -> bool:
    section_data = state.values.get(section_id)
    if isinstance(section_data, dict):
        fv = section_data.get(field_id)
        if isinstance(fv, dict):
            v = fv.get("value")
            return v not in (None, "", [], {})
    return False


# ── Function declarations sent to Gemini ─────────────────────────────────────

FUNCTION_DECLS: list[dict[str, Any]] = [
    {
        "name": "update_field",
        "description": (
            "Record a value the user provided for a specific field. "
            "Call this every time you capture a field value. "
            "Use confidence < 0.6 when the user was ambiguous or you had to guess. "
            "For multi-value fields (e.g. preferred_languages, "
            "communication_preferences) use the 'values' array parameter and "
            "include EVERY item the user mentioned in a SINGLE call — never "
            "split a multi-value answer across multiple update_field calls."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "description": "Section id from the schema (e.g. 'basics', 'home_address').",
                },
                "field": {
                    "type": "string",
                    "description": "Field id from the schema (e.g. 'full_name', 'email').",
                },
                "value": {
                    "type": "string",
                    "description": (
                        "Scalar captured value. Use for text/email/phone/date/"
                        "single-choice fields. Booleans use 'true'/'false'. "
                        "For multi-value fields use the 'values' array instead."
                    ),
                },
                "values": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Multi-value array. Use this for multi_enum fields "
                        "when the user mentions multiple items in a single "
                        "answer (e.g. 'verbal and phone' → "
                        "values=['verbal','phone']). Include EVERY item the "
                        "user said. Do not also provide 'value' for these "
                        "fields — the array supersedes it."
                    ),
                },
                "repeatable_index": {
                    "type": "integer",
                    "description": (
                        "Zero-based index for repeatable sections (e.g. emergency_contacts). "
                        "Omit for non-repeatable sections."
                    ),
                },
                "confidence": {
                    "type": "number",
                    "description": "Model confidence in the captured value, 0.0 to 1.0.",
                },
                "cross_section_intent": {
                    "type": "boolean",
                    "description": (
                        "Set true ONLY when intentionally updating a field outside the "
                        "currently focused section. Omit or false normally — the dispatcher "
                        "blocks cross-section writes without this flag."
                    ),
                },
            },
            "required": ["section", "field"],
        },
    },
    {
        "name": "get_session_context",
        "description": (
            "Fetch a condensed view of what has already been captured and what is still "
            "required. Call this if you are unsure which fields remain."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "advance_step",
        "description": (
            "Call ONLY after every required field is filled, validate_step_complete "
            "has zero rejections, and the user has spoken an explicit confirmation "
            "(e.g. 'yes I'm done', 'submit it'). Pass the user's exact confirmation "
            "words in confirmation_transcript — server rejects empty strings."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "confirmation_transcript": {
                    "type": "string",
                    "minLength": 3,
                    "description": (
                        "EXACT verbatim words the user spoke to confirm completion. "
                        "Required and non-empty. Do not paraphrase. Do not synthesise."
                    ),
                },
            },
            "required": ["confirmation_transcript"],
        },
    },
    {
        "name": "escalate_incident",
        "description": (
            "Call immediately if the user reports abuse, self-harm, or a safety concern. "
            "Does NOT end the session — continue the conversation calmly after calling."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "enum": ["abuse", "self_harm", "safety", "other"],
                },
                "transcript_excerpt": {
                    "type": "string",
                    "description": "Short quote from the user that triggered the escalation.",
                },
            },
            "required": ["reason"],
        },
    },
    {
        "name": "add_repeatable_row",
        "description": (
            "Add a new empty row to a repeatable section so the user can provide "
            "another entry (e.g. a new NDIS goal). Only call for voice-eligible "
            "repeatable sections."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "section_id": {
                    "type": "string",
                    "description": "Repeatable section id (e.g. 'ndis_goals').",
                },
            },
            "required": ["section_id"],
        },
    },
    {
        "name": "enter_repeatable_section",
        "description": (
            "Pin focus to a repeatable section before collecting values. "
            "MUST be called before any update_field in a repeatable section. "
            "intent='first' for the first row, intent='next' for each subsequent row."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "section_id": {
                    "type": "string",
                    "description": "Repeatable section id (e.g. 'emergency_contacts').",
                },
                "intent": {
                    "type": "string",
                    "enum": ["first", "next"],
                    "description": "'first' pins to row 0; 'next' pins to the next available row.",
                },
            },
            "required": ["section_id", "intent"],
        },
    },
    {
        "name": "exit_repeatable_section",
        "description": (
            "Release focus from the current repeatable section after all values "
            "for the current row are collected."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "request_unknown_section",
        "description": (
            "Call when the participant asks for a section or field that is not in the schema. "
            "Logs the request for the dev team. Do NOT attempt to fill fields in unknown sections."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "section_id": {
                    "type": "string",
                    "description": "The section id the participant asked for.",
                },
                "label": {
                    "type": "string",
                    "description": "Human-readable label the participant used.",
                },
            },
            "required": ["section_id", "label"],
        },
    },
]

# ── Policy block tool (grounding-off fallback) ───────────────────────────────
# Included only when grounding is DISABLED. Gives Gemini an explicit escape
# hatch instead of hallucinating answers to NDIS policy questions it can't
# search. Calling it raises PolicyBlockSignal → WS close 4011.

POLICY_BLOCK_DECL: dict[str, Any] = {
    "name": "policy_block",
    "description": (
        "Call this ONLY when the user asks a specific current NDIS policy, funding rule, "
        "or legislative question that requires up-to-date search data you do not have. "
        "Do NOT call for general NDIS knowledge you can answer from training. "
        "Calling this ends the session."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The exact policy question the user asked.",
            },
        },
        "required": ["question"],
    },
}


# ── Value coercion ───────────────────────────────────────────────────────────

def _coerce_value(raw: Any, field: FieldSpec) -> Any:
    """
    Gemini passes all tool-arg values as strings (per our schema). Convert into
    the type the field declares so the app backend gets a typed value.
    Return raw input on failure — we annotate low confidence elsewhere, and the
    app's review UI can flag it.
    """
    if raw is None:
        return None

    ftype = field.type.value if hasattr(field.type, "value") else str(field.type)
    s = str(raw).strip()

    try:
        if ftype == "boolean":
            return s.lower() in ("true", "yes", "y", "1")
        if ftype == "number":
            return float(s) if "." in s else int(s)
        if ftype == "currency":
            return float(s.replace("$", "").replace(",", ""))
        if ftype == "multi_enum":
            if isinstance(raw, list):
                return raw
            return [x.strip() for x in s.split(",") if x.strip()]
        if ftype == "enum" and field.options:
            # Normalise model output (e.g. "SELF_MANAGED", "self managed", "self-managed")
            # to the canonical schema option string (e.g. "Self Managed").
            # Strategy: case-insensitive comparison after collapsing [-_\s] to space.
            import re as _re
            def _normalise(v: str) -> str:
                return _re.sub(r"[-_\s]+", " ", v).strip().lower()
            s_norm = _normalise(s)
            for opt in field.options:
                if _normalise(opt) == s_norm:
                    return opt  # return canonical casing from schema
            # No exact (normalised) match — return raw so downstream validator
            # can emit a human-readable rejection rather than silently accepting
            # an invalid value.
    except (ValueError, TypeError):
        return raw
    return s


# ── Validation error helpers ─────────────────────────────────────────────────

def _upsert_validation_error(
    state: FormState,
    section_id: str,
    field_id: str,
    repeatable_index: int | None,
    rej: Any,
) -> None:
    """Upsert a validation error into state.pending_validation_errors (dedup by key)."""
    key = (section_id, field_id, repeatable_index)
    state.pending_validation_errors = [
        e for e in state.pending_validation_errors
        if (e.get("section_id"), e.get("field_id"), e.get("repeatable_index")) != key
    ]
    entry: dict = {
        "section_id": section_id,
        "field_id": field_id,
        "repeatable_index": repeatable_index,
        "code": rej.code,
        "reason_human": rej.reason_human,
    }
    if getattr(rej, "allowed_values", None) is not None:
        entry["allowed_values"] = rej.allowed_values
    state.pending_validation_errors.append(entry)


def _clear_validation_error(
    state: FormState,
    section_id: str,
    field_id: str,
    repeatable_index: int | None,
) -> None:
    """Remove any pending validation error for this (section, field, index) tuple."""
    key = (section_id, field_id, repeatable_index)
    state.pending_validation_errors = [
        e for e in state.pending_validation_errors
        if (e.get("section_id"), e.get("field_id"), e.get("repeatable_index")) != key
    ]


def _build_dry_run_values(
    state: FormState,
    section_id: str,
    field_id: str,
    typed_value: Any,
    row_index: int | None,
) -> dict[str, Any]:
    """Return a shallow-copied state.values with the proposed write applied.

    Used by the per-write cross-field check so the dry-run sees the about-
    to-commit value in place. Does NOT mutate the live state.
    """
    snapshot = dict(state.values)
    rows = snapshot.get(section_id)
    if isinstance(rows, list):
        new_rows = [dict(r) if isinstance(r, dict) else r for r in rows]
        idx = row_index if row_index is not None else 0
        while len(new_rows) <= idx:
            new_rows.append({})
        existing = new_rows[idx] if isinstance(new_rows[idx], dict) else {}
        existing = dict(existing)
        existing[field_id] = {"value": typed_value}
        new_rows[idx] = existing
        snapshot[section_id] = new_rows
    return snapshot


# ── Section-copy mirroring (schema `copy_from_if_flagged`) ───────────────────

def _apply_copy_mirroring(
    state: FormState, schema: StepSchema, turn_id: int
) -> list[tuple[str, str, Any]]:
    """Materialise schema-declared section-copy shortcuts.

    For every section that declares `copy_from_if_flagged: <source_section>`
    plus a `flag_field`, this helper checks whether the flag currently
    evaluates to True in `state`. When it does, every matching field id from
    the source section is mirrored into the target section. The mirrored
    values are tagged `FieldSource.app` so the UI can distinguish them from
    the user's voice captures.

    Idempotent — re-running with no source-side changes is a no-op (we skip
    writes when target value already equals source value). Returns the list
    of `(section_id, field_id, value)` tuples that were written so callers
    can emit per-field events for the Flutter UI.

    Used to satisfy the "service address same as home → auto-fill the four
    address fields" requirement declared by the personal-information schema
    on `service_address` (`copy_from_if_flagged: "home_address"`).
    """
    written: list[tuple[str, str, Any]] = []
    for section in schema.sections:
        if not section.copy_from_if_flagged or not section.flag_field:
            continue

        # Read flag — fall back to declared default when the target section
        # has not been touched yet. This is the common case for
        # service_address: the flag defaults to True, the user never explicitly
        # confirms it, and we still need to mirror as soon as home_address is
        # filled.
        flag_id = section.flag_field.id
        section_values = state.values.get(section.id)
        flag_fv = (
            section_values.get(flag_id)
            if isinstance(section_values, dict) else None
        )
        if isinstance(flag_fv, dict):
            flag_on = bool(flag_fv.get("value"))
        else:
            flag_on = bool(section.flag_field.default)
        if not flag_on:
            continue

        source_values = state.values.get(section.copy_from_if_flagged)
        if not isinstance(source_values, dict):
            continue

        target_field_ids = {f.id for f in (section.fields or [])}
        for src_id, src_fv in source_values.items():
            if src_id not in target_field_ids or not isinstance(src_fv, dict):
                continue
            src_value = src_fv.get("value")
            if src_value is None:
                continue

            current_target = state.values.get(section.id)
            tgt_fv = (
                current_target.get(src_id)
                if isinstance(current_target, dict) else None
            )
            tgt_value = tgt_fv.get("value") if isinstance(tgt_fv, dict) else None
            if tgt_value == src_value:
                continue

            # set_field initializes the target section dict if missing.
            state.set_field(
                section_id=section.id,
                field_id=src_id,
                value=src_value,
                source=FieldSource.app,
                confidence=1.0,
                turn_id=turn_id,
                repeatable_index=None,
            )
            written.append((section.id, src_id, src_value))
    return written


# ── Policy block signal ──────────────────────────────────────────────────────

class PolicyBlockSignal(BaseException):
    """Derives from BaseException so it escapes the except-Exception catch in
    dispatch() and propagates to _handle_tool_call in gemini_live.py, which
    closes the WS with code 4011 before send_tool_response fires."""

    def __init__(self, question: str = "") -> None:
        self.question = question
        super().__init__(question)


# ── Dispatcher ───────────────────────────────────────────────────────────────

EmitFn = Callable[[dict[str, Any]], Awaitable[None]]


class ToolDispatcher:
    """
    Routes Gemini function calls to handlers that mutate FormState and emit
    events to the app WebSocket.

    Callers construct one per live session. The dispatch() method is called
    once per tool_call in the Gemini receive loop.
    """

    def __init__(
        self,
        websocket: WebSocket,
        session_id: str,
        repo: FormStateRepo,
        schema: StepSchema,
        emit: EmitFn | None = None,
        bootstrap: SessionBootstrap | None = None,
    ) -> None:
        self._ws = websocket
        self._session_id = session_id
        self._repo = repo
        self._schema = schema
        # Allow tests to inject a capture function; default sends over WS
        self._emit: EmitFn = emit or self._default_emit
        self._turn_id = 0
        # Set True once advance_step fires successfully — the WS loop checks
        # this to close the connection cleanly
        self.step_completed: bool = False
        # Rule 3 — readonly enforcement. Paths in this set are rejected by
        # _update_field with a structured error so Gemini relays the rejection
        # to the user and stops trying to edit them.
        self._readonly_paths: set[str] = set(
            (bootstrap.readonly_paths if bootstrap else []) or []
        )

    def set_turn_id(self, turn_id: int) -> None:
        """Called by the gemini_live bridge before dispatching so that
        update_field stamps the correct turn on each FieldValue."""
        self._turn_id = turn_id

    # ── Entry point ──────────────────────────────────────────────────────────

    async def dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Route a single function call. Return value becomes the
        FunctionResponse payload the model sees on its next turn."""
        log.info(
            "tool_call session=%s name=%s args=%s",
            self._session_id,
            name,
            json.dumps(args, default=str),
        )
        handler = {
            "update_field": self._update_field,
            "get_session_context": self._get_session_context,
            "advance_step": self._advance_step,
            "escalate_incident": self._escalate_incident,
            "add_repeatable_row": self._add_repeatable_row,
            "enter_repeatable_section": self._enter_repeatable_section,
            "exit_repeatable_section": self._exit_repeatable_section,
            "request_unknown_section": self._request_unknown_section,
            "policy_block": self._policy_block,
        }.get(name)

        if handler is None:
            return {"ok": False, "error": f"unknown tool: {name}"}

        try:
            return await handler(args)
        except Exception as exc:
            log.exception("tool_handler_error session=%s name=%s", self._session_id, name)
            return {"ok": False, "error": str(exc)}

    # ── Handler: update_field ────────────────────────────────────────────────

    async def _update_field(self, args: dict[str, Any]) -> dict[str, Any]:
        section_id = args.get("section")
        field_id = args.get("field")

        # Defensive: __section_min__ is a prompt-renderer sentinel, not a real field.
        # If Gemini echoes it back as a field_id, reject cleanly rather than touching state.
        if field_id == "__section_min__":
            log.info(
                "sentinel_field_rejected section=%s session=%s",
                section_id,
                self._session_id,
            )
            return {
                "ok": False,
                "error": "sentinel_field_id",
                "message": (
                    "__section_min__ is not a real field — call add_repeatable_row "
                    "to add a row to this section, then fill its fields."
                ),
            }
        # Rule 4 — multi-value capture. 'values' (array) takes precedence over
        # 'value' (scalar) so a single tool call can record an answer like
        # "verbal and phone" without splitting into two calls.
        raw_values = args.get("values")
        raw_value: Any
        if isinstance(raw_values, list) and raw_values:
            raw_value = list(raw_values)
            log.info(
                "multi_value applied field=%s.%s count=%d session=%s",
                section_id,
                field_id,
                len(raw_values),
                self._session_id,
            )
        else:
            raw_value = args.get("value")
        repeatable_index = args.get("repeatable_index")
        confidence = float(args.get("confidence", 1.0))
        cross_section_intent = bool(args.get("cross_section_intent", False))
        # Gemini tool dispatch is voice-originated by definition. Allow
        # callers (tests, future internal callers) to override; default to
        # "voice" so envelopes emitted to Flutter carry the marker without
        # the dispatcher needing to know the channel.
        _input_method_raw = args.get("input_method", "voice")
        input_method: Literal["typed", "voice"] | None = (
            _input_method_raw
            if _input_method_raw in ("typed", "voice")
            else None
        )

        if not section_id or not field_id:
            return {"ok": False, "error": "section and field are required"}
        if (
            raw_value is None
            or (isinstance(raw_value, str) and not raw_value.strip())
            or (isinstance(raw_value, list) and not raw_value)
        ):
            return {
                "ok": False,
                "error": "either 'value' (scalar) or 'values' (array) is required",
            }

        # M1 — PENDING_CONFIRMATION lock with C1 same-row tolerance.
        # While a low-confidence capture awaits user confirmation, reject
        # update_field calls that target a DIFFERENT row or DIFFERENT section.
        # ALLOW same-row sibling fields — when the user dictates a whole row
        # in one breath ("Azithromycin 500mg 3x daily for allergies"), the
        # other field updates in that same row are part of the same logical
        # action and should commit normally. The lock only blocks cross-row
        # or cross-section bleeds where the model races ahead.
        state_for_lock = await self._repo.get_state(self._session_id)
        if state_for_lock and state_for_lock.pending_confirmation:
            pc = state_for_lock.pending_confirmation
            same_target = (
                pc.get("section") == section_id
                and pc.get("field") == field_id
                and pc.get("repeatable_index") == repeatable_index
            )
            # C1 — same (section, row), different field is a sibling of the
            # locked field. Allow it through for REPEATABLE sections only.
            # For non-repeatable sections repeatable_index is always None on
            # both sides, so the equality test alone would incorrectly let any
            # same-section field through. Requiring repeatable_index is not None
            # ensures C1 only fires when a concrete row index is in play.
            same_row_sibling = (
                pc.get("repeatable_index") is not None
                and pc.get("section") == section_id
                and pc.get("repeatable_index") == repeatable_index
                and pc.get("field") != field_id
            )
            if not (same_target or same_row_sibling):
                # C2 — Buffer the call onto pending_batch; the lock-clear
                # path will drain it. The model receives code: DEFERRED
                # so it knows the call is queued, not lost or wrong.
                _max_pending_batch = 32
                if len(state_for_lock.pending_batch) >= _max_pending_batch:
                    log.warning(
                        "update_field BUFFER_FULL queue_size=%d attempted=%s.%s "
                        "blocking=%s.%s session=%s",
                        len(state_for_lock.pending_batch),
                        section_id, field_id,
                        pc.get("section"), pc.get("field"),
                        self._session_id,
                    )
                    return {
                        "ok": False,
                        "rejection": {
                            "code": "BUFFER_FULL",
                            "reason_human": (
                                "Too many pending updates queued — please "
                                "confirm the previous answer before continuing."
                            ),
                        },
                    }
                state_for_lock.pending_batch.append({
                    "section": section_id,
                    "field": field_id,
                    "value": raw_value if not isinstance(raw_value, list) else None,
                    "values": list(raw_value) if isinstance(raw_value, list) else None,
                    "confidence": confidence,
                    "repeatable_index": repeatable_index,
                })
                await self._repo.save_state(state_for_lock, ttl_sec=settings.session_max_sec)
                log.info(
                    "update_field DEFERRED buffered=%s.%s queue_size=%d "
                    "blocking=%s.%s session=%s",
                    section_id, field_id,
                    len(state_for_lock.pending_batch),
                    pc.get("section"), pc.get("field"),
                    self._session_id,
                )
                return {
                    "ok": False,
                    "rejection": {
                        "code": "DEFERRED",
                        "section": section_id,
                        "field": field_id,
                        "blocking_section": pc.get("section"),
                        "blocking_field": pc.get("field"),
                        "reason_human": (
                            "I'll save that one in a moment — let me confirm "
                            "the previous answer first."
                        ),
                    },
                }

        # Rule 3 — readonly enforcement. Reject before schema lookup so paths
        # like 'basics.email' that may be legal schema fields still get blocked
        # when the bootstrap declared them read-only.
        path = f"{section_id}.{field_id}"
        if path in self._readonly_paths:
            log.warning(
                "update_field REJECTED readonly path=%s session=%s "
                "(declared readonly_paths: %s). Rule 3 — agent should not have "
                "tried to edit this; reinforce the read-only response in the "
                "next turn.",
                path,
                self._session_id,
                sorted(self._readonly_paths),
            )
            return {
                "ok": False,
                "error": (
                    f"field '{path}' is read-only — tell the user it can only "
                    "be changed in account settings, then move on"
                ),
                "readonly": True,
            }

        # Validate against schema
        section: SectionSpec | None = self._schema.get_section(section_id)
        if section is None:
            log.warning(
                "update_field REJECTED — unknown section '%s' (schema sections: %s) "
                "session=%s. Likely cause: client schema does not declare this section.",
                section_id,
                [s.id for s in self._schema.sections],
                self._session_id,
            )
            await self._emit({
                "type": "schema_drift_detected",
                "kind": "unknown_section",
                "attempted_section": section_id,
                "attempted_field": field_id,
            })
            return {"ok": False, "error": f"unknown section: {section_id}"}

        field: FieldSpec | None = next(
            (f for f in section.all_fields() if f.id == field_id), None
        )
        if field is None:
            log.info(
                "unknown_field_attempt session=%s attempted_section=%s "
                "attempted_field=%s attempted_value_shape=%s",
                self._session_id,
                section_id,
                field_id,
                type(raw_value).__name__,
            )
            await self._emit({
                "type": "schema_drift_detected",
                "kind": "unknown_field",
                "attempted_section": section_id,
                "attempted_field": field_id,
            })
            log.warning(
                "update_field REJECTED — field '%s' not in section '%s' "
                "(declared fields: %s) session=%s. "
                "Likely cause: client schema is missing this field — "
                "see FLUTTER_DEV_HANDOFF.md Issue #3.",
                field_id,
                section_id,
                [f.id for f in section.all_fields()],
                self._session_id,
            )
            return {
                "ok": False,
                "error": f"field '{field_id}' not in section '{section_id}'",
            }

        # Repeatable sanity: index only meaningful for repeatable sections
        if section.is_repeatable and repeatable_index is None:
            repeatable_index = 0

        if (
            repeatable_index is not None
            and section.repeatable
            and repeatable_index >= section.repeatable.max
        ):
            return {
                "ok": False,
                "error": f"repeatable_index {repeatable_index} exceeds max "
                         f"{section.repeatable.max}",
            }

        typed_value = _coerce_value(raw_value, field)

        # Load → mutate → save FormState
        state = await self._repo.get_state(self._session_id)
        if state is None:
            return {"ok": False, "error": "session state not found"}

        # Implicit-enter for repeatable sections. The agent often writes
        # `update_field("emergency_contacts", "name", ...)` without first
        # calling `enter_repeatable_section`. Treat that write as the implicit
        # enter — auto-pin focus to the new section + row index — instead of
        # rejecting with `cross_section_blocked` and forcing a retry. Mirrors
        # the auto-pin behaviour already in `_add_repeatable_row` so the two
        # paths agree on what "focus" means.
        if section.is_repeatable and state.focused_section != section_id:
            prior_focus = state.focused_section
            state.focused_section = section_id
            state.focused_repeatable_index = (
                repeatable_index if repeatable_index is not None else 0
            )
            log.info(
                "auto_pin_repeatable session=%s prior_focus=%s new_focus=%s row=%s",
                self._session_id, prior_focus, section_id,
                state.focused_repeatable_index,
            )
            await self._emit({
                "type": "repeatable_section_entered",
                "section_id": section_id,
                "intent": "implicit",
                "row_index": state.focused_repeatable_index,
            })

        # Cross-section guard — reject writes to OTHER non-repeatable sections
        # without explicit intent. The repeatable case was handled above by
        # auto-pin so the guard never fires for it.
        if (
            state.focused_section
            and section_id != state.focused_section
            and not cross_section_intent
        ):
            return {
                "ok": False,
                "rejection": {
                    "code": "cross_section_blocked",
                    "reason_human": (
                        f"I'm still collecting information for '{state.focused_section}' — "
                        f"please finish that before moving to '{section_id}'."
                    ),
                    "suggested_fix": (
                        f"Finish '{state.focused_section}' first, or set "
                        "cross_section_intent=true if this is intentional."
                    ),
                },
            }

        # Server-side validation — authoritative; runs before any FormState write
        _ri = repeatable_index if section.is_repeatable else None
        # Resolve schema FieldSpec so the validator can check enum options (V3 fix)
        _field_spec = self._schema.get_field_spec(section_id, field_id) if self._schema else None
        rej = _validate_field(
            section_id, field_id, typed_value,
            repeatable_index=_ri,
            state=state,
            field_spec=_field_spec,
        )
        _advisory_rej = None
        if rej is not None:
            _upsert_validation_error(state, section_id, field_id, _ri, rej)
            if settings.onboarding_voice_validation_advisory:
                # Advisory path — persist value anyway, emit warning, fall through
                _advisory_rej = rej
                log.info(
                    "field_advisory_warning section=%s field=%s code=%s session=%s",
                    section_id, field_id, rej.code, self._session_id,
                )
                _adv_event: dict[str, Any] = {
                    "type": "field_advisory_warning",
                    "section_id": section_id,
                    "field_id": field_id,
                    "repeatable_index": _ri,
                    "code": rej.code,
                    "reason_human": rej.reason_human,
                    "severity": "advisory",
                }
                if rej.suggested_fix is not None:
                    _adv_event["suggested_fix"] = rej.suggested_fix
                if rej.allowed_values is not None:
                    _adv_event["allowed_values"] = rej.allowed_values
                await self._emit(_adv_event)
                # Fall through to state.set_field below
            else:
                # Strict path — original blocking behaviour
                await self._repo.save_state(state, ttl_sec=settings.session_max_sec)
                log.info(
                    "validation_rejection section=%s field=%s code=%s session=%s",
                    section_id, field_id, rej.code, self._session_id,
                )
                event: dict = {
                    "type": "validation_rejection",
                    "section_id": section_id,
                    "field_id": field_id,
                    "repeatable_index": _ri,
                    "code": rej.code,
                    "reason_human": rej.reason_human,
                }
                if rej.suggested_fix is not None:
                    event["suggested_fix"] = rej.suggested_fix
                if rej.allowed_values is not None:
                    event["allowed_values"] = rej.allowed_values
                await self._emit(event)
                return {"ok": False, "rejection": rej.model_dump()}

        # Clear any prior error for this field — validation now passes (or advisory)
        _clear_validation_error(state, section_id, field_id, _ri)

        # C4 — Per-write cross-field pass for cross-row invariants involving
        # the just-mutated field (phone/email uniqueness + ≠ client).
        # Policy (non-obvious): the per-field write itself is INDIVIDUALLY
        # valid (we already passed validate_field above), so it WILL commit
        # to FormState below. But if the new value collides with an OTHER
        # row's phone/email, that OTHER row is now invalid — we emit a
        # validation_rejection for the OTHER row(s) so the client sees the
        # conflict surface immediately without waiting for /complete.
        #
        # We intentionally do NOT emit the rejection against the just-
        # written (section_id, field_id) — that field's value is valid on
        # its own; the conflict is structural across rows.
        if (
            section.is_repeatable
            and section_id == "emergency_contacts"
            and field_id in ("email", "phone")
        ):
            # Build a dry-run state snapshot reflecting the about-to-commit
            # value so the cross-field checks see the new value in place.
            dry_values = _build_dry_run_values(
                state, section_id, field_id, typed_value, _ri,
            )
            check_fn = _ec_email_check if field_id == "email" else _ec_phone_check
            conflicts = check_fn(dry_values)
            rows = dry_values.get(section_id) or []
            # For each conflict, find the OTHER row(s) that now collide
            # with the just-written value and emit a validation_rejection
            # against them. The just-written row's own validation already
            # passed; we surface only structural collisions.
            for conflict in conflicts:
                for other_idx, other_row in enumerate(rows):
                    if other_idx == _ri or not isinstance(other_row, dict):
                        continue
                    other_fv = other_row.get(field_id)
                    other_val = (
                        other_fv.get("value")
                        if isinstance(other_fv, dict) else other_fv
                    )
                    if not other_val:
                        continue
                    # Normalise compare (phone strip non-digits; email lower)
                    if field_id == "email":
                        match = str(other_val).strip().lower() == str(
                            typed_value
                        ).strip().lower()
                    else:
                        import re as _re
                        _strip = _re.compile(r"\D")
                        match = _strip.sub("", str(other_val)) == _strip.sub(
                            "", str(typed_value),
                        )
                    if not match:
                        continue
                    cross_event: dict = {
                        "type": "validation_rejection",
                        "section_id": section_id,
                        "field_id": field_id,
                        "repeatable_index": other_idx,
                        "code": conflict.code,
                        "reason_human": conflict.reason_human,
                    }
                    if conflict.suggested_fix is not None:
                        cross_event["suggested_fix"] = conflict.suggested_fix
                    await self._emit(cross_event)

        # B5 — Low-confidence gate: pause before committing uncertain captures.
        # Threshold: anything below 0.90 requires explicit user confirmation.
        # The model is instructed by Rule 10 to ask "Is that right?" — this
        # code gate enforces it even if the model skips the prompt.
        _low_conf_threshold = 0.90
        if confidence < _low_conf_threshold:
            log.info(
                "low_confidence_gate section=%s field=%s confidence=%.2f session=%s — "
                "returning CONFIRM_REQUIRED, value NOT committed",
                section_id, field_id, confidence, self._session_id,
            )
            # M1 — Set the PENDING_CONFIRMATION lock so subsequent update_field
            # calls for OTHER fields are rejected until the user confirms.
            state.pending_confirmation = {
                "section": section_id,
                "field": field_id,
                "heard_value": typed_value,
                "repeatable_index": (
                    repeatable_index if section.is_repeatable else None
                ),
                "set_at": _utcnow_iso(),
            }
            await self._repo.save_state(state, ttl_sec=settings.session_max_sec)
            return {
                "ok": False,
                "rejection": {
                    "code": "CONFIRM_REQUIRED",
                    "section": section_id,
                    "field": field_id,
                    "heard_value": typed_value,
                    "confidence": confidence,
                    "reason_human": (
                        f"I wasn't fully sure I caught that correctly — "
                        f"did you say {typed_value}?"
                    ),
                },
            }

        # M6 — Name-anchor guard. If the agent tries to record an
        # emergency_contact.name that exactly matches the participant's own
        # full_name, log a warning. Don't reject (the user may legitimately
        # have that as a contact name) but flag the suspicious overlap so
        # post-hoc analysis catches the hallucination pattern.
        if (
            section_id == "emergency_contacts"
            and field_id == "name"
            and isinstance(typed_value, str)
        ):
            participant_name_fv = (state.values.get("basics") or {}).get("full_name")
            participant_name = (
                participant_name_fv.get("value")
                if isinstance(participant_name_fv, dict)
                else None
            )
            if (
                isinstance(participant_name, str)
                and participant_name.lower() == typed_value.lower()
            ):
                import hashlib
                value_sha8 = hashlib.sha256(typed_value.encode("utf-8")).hexdigest()[:8]
                log.warning(
                    "emergency_contact_name_equals_participant section=%s field=%s "
                    "value_sha8=%s session=%s — agent may be mis-routing the participant's "
                    "own name into the emergency-contacts section",
                    section_id, field_id, value_sha8, self._session_id,
                )

        # Capture prior committed value + confirmed flag for field_confirmed emission.
        # Must be read BEFORE set_field so we compare against the pre-write state.
        _sec_vals_pre = state.values.get(section_id)
        if _ri is not None and isinstance(_sec_vals_pre, list) and _ri < len(_sec_vals_pre):
            _prior_fv_raw: Any = (
                _sec_vals_pre[_ri].get(field_id) if isinstance(_sec_vals_pre[_ri], dict) else None
            )
        elif isinstance(_sec_vals_pre, dict):
            _prior_fv_raw = _sec_vals_pre.get(field_id)
        else:
            _prior_fv_raw = None
        _prior_value: Any = (
            _prior_fv_raw.get("value")
            if isinstance(_prior_fv_raw, dict)
            else None
        )
        _prior_confirmed: bool = (
            bool(_prior_fv_raw.get("confirmed_in_session"))
            if isinstance(_prior_fv_raw, dict)
            else False
        )

        # Compute same-value BEFORE set_field so we can persist confirmed_in_session correctly.
        # confirmed_in_session = True when value is unchanged (field stays confirmed across
        # subsequent writes); False when value changes (confirmation resets for the new value).
        if isinstance(typed_value, list):
            _is_same_value = (
                set(str(x) for x in typed_value)
                == set(str(x) for x in (_prior_value if isinstance(_prior_value, list) else []))
            )
        else:
            _is_same_value = (typed_value == _prior_value)

        state.set_field(
            section_id=section_id,
            field_id=field_id,
            value=typed_value,
            source=FieldSource.voice,
            confidence=confidence,
            turn_id=self._turn_id,
            repeatable_index=repeatable_index if section.is_repeatable else None,
            input_method=input_method,
            confirmed_in_session=_is_same_value,
        )

        # M1 — Clear the PENDING_CONFIRMATION lock if this commit satisfied
        # it (same section/field/row as the lock target).
        if state.pending_confirmation:
            pc = state.pending_confirmation
            if (
                pc.get("section") == section_id
                and pc.get("field") == field_id
                and pc.get("repeatable_index") == (
                    repeatable_index if section.is_repeatable else None
                )
            ):
                state.pending_confirmation = None

        # Emit field_confirmed on the first re-statement of an already-committed value.
        # confirmed_in_session is now persisted via set_field so no dict mutation needed.
        if _is_same_value and not _prior_confirmed:
            await self._emit({
                "type": "field_confirmed",
                "section_id": section_id,
                "field_id": field_id,
                "repeatable_index": _ri,
                "value": typed_value,
                "confirmation_source": "voice",
                "turn_id": self._turn_id,
            })

        # M5 — Conditional follow-up driver. After committing a value, scan
        # the schema for any field whose `visible_if` references the field we
        # just set. If the just-set value satisfies the unlock condition AND
        # the dependent field is still empty, write it to next_forced_field
        # so the prompt forces the model to ask it next.
        _set_next_forced_field(state, self._schema, section_id, field_id, typed_value)

        # Materialise schema-declared section-copy shortcuts (e.g. service
        # address ← home address when service_same_as_home is true). Runs
        # after every write so updating either the flag OR a source-side
        # field keeps the mirrored target in sync. Idempotent.
        mirrored = _apply_copy_mirroring(state, self._schema, self._turn_id)

        # C2 — If the lock just cleared and we have buffered calls, drain
        # them iteratively. Each iteration completes before the next starts so
        # no recursive coroutine frames pile up (depth bounded by Patch 1 cap).
        # Clear the buffer BEFORE the loop so a replay that re-triggers the
        # lock re-buffers into a fresh pending_batch rather than double-buffering.
        deferred_applied: list[dict] = []
        if state.pending_confirmation is None and state.pending_batch:
            batch = state.pending_batch
            state.pending_batch = []
            await self._repo.save_state(state, ttl_sec=settings.session_max_sec)
            for entry in batch:
                replay_args: dict[str, Any] = {
                    "section": entry["section"],
                    "field": entry["field"],
                    "confidence": entry.get("confidence", 1.0),
                }
                if entry.get("values"):
                    replay_args["values"] = entry["values"]
                elif entry.get("value") is not None:
                    replay_args["value"] = entry["value"]
                if entry.get("repeatable_index") is not None:
                    replay_args["repeatable_index"] = entry["repeatable_index"]
                # CRITICAL — refresh state before each replay so the inner
                # call sees the up-to-date pending_confirmation/pending_batch.
                # If a replay triggers a new low-conf lock, subsequent
                # entries get re-buffered instead of forcing a deep recurse.
                replay_result = await self._update_field(replay_args)
                deferred_applied.append({
                    "section": entry["section"],
                    "field": entry["field"],
                    "ok": replay_result.get("ok", False),
                    "result_code": (
                        replay_result.get("rejection", {}).get("code")
                        if not replay_result.get("ok")
                        else "applied"
                    ),
                })
                # If the replay re-engaged the lock, stop draining; the rest
                # of batch is already discarded (we cleared pending_batch
                # before the loop), so re-buffer the unprocessed tail here.
                fresh = await self._repo.get_state(self._session_id)
                if fresh and fresh.pending_confirmation is not None:
                    unprocessed = batch[batch.index(entry) + 1:]
                    if unprocessed:
                        fresh.pending_batch.extend(unprocessed)
                        await self._repo.save_state(fresh, ttl_sec=settings.session_max_sec)
                    break
            # Re-load state — replay calls mutated it.
            state = await self._repo.get_state(self._session_id)

        state.recompute_completion(self._schema)
        await self._repo.save_state(state, ttl_sec=settings.session_max_sec)

        # Emit events to app
        await self._emit({
            "type": "field_updated",
            "section": section_id,
            "field": field_id,
            "value": typed_value,
            "repeatable_index": repeatable_index if section.is_repeatable else None,
            "confidence": confidence,
            "turn_id": self._turn_id,
        })
        # Surface each auto-mirrored field as its own field_updated event so
        # the Flutter UI can re-render them inline without waiting for the
        # next state snapshot.
        for m_section, m_field, m_value in mirrored:
            await self._emit({
                "type": "field_updated",
                "section": m_section,
                "field": m_field,
                "value": m_value,
                "repeatable_index": None,
                "confidence": 1.0,
                "turn_id": self._turn_id,
                "source": "app",
                "auto_copied_from": next(
                    (s.copy_from_if_flagged for s in self._schema.sections
                     if s.id == m_section),
                    None,
                ),
            })
        await self._emit({"type": "state", "state": state.model_dump(mode="json")})

        envelope = _fa.build_envelope(
            section_id,
            field_id,
            typed_value,
            row_index=repeatable_index if section.is_repeatable else None,
            confidence=confidence,
            schema=self._schema,
            enforced=settings.voice_coverage_enforced,
            input_method=input_method,
        )
        if envelope is not None:
            await self._emit(envelope)

        completion = state.completion
        result: dict[str, Any] = {
            "ok": True,
            "section": section_id,
            "field": field_id,
            "value": typed_value,
            "required_filled": completion.required_filled if completion else 0,
            "required_total": completion.required_total if completion else 0,
            "complete": bool(completion and completion.complete),
        }
        if _advisory_rej is not None:
            result["warning"] = _advisory_rej.model_dump()
        if deferred_applied:
            result["deferred_applied"] = deferred_applied
        return result

    # ── Handler: get_session_context ─────────────────────────────────────────

    async def _get_session_context(self, _args: dict[str, Any]) -> dict[str, Any]:
        state = await self._repo.get_state(self._session_id)
        if state is None:
            return {"ok": False, "error": "session state not found"}

        # Flatten captured values into {section.field: value} for compact context
        filled: dict[str, Any] = {}
        missing_required: list[str] = []

        for section in self._schema.sections:
            section_values = state.values.get(section.id)
            fields = section.all_fields()

            if section.is_repeatable:
                rows = section_values if isinstance(section_values, list) else []
                for idx, row in enumerate(rows):
                    for f in fields:
                        fv = (row or {}).get(f.id)
                        v = fv.get("value") if isinstance(fv, dict) else None
                        if v is not None:
                            filled[f"{section.id}[{idx}].{f.id}"] = v
                        elif f.required and f.visible_if is None:
                            missing_required.append(f"{section.id}[{idx}].{f.id}")
            else:
                row = section_values if isinstance(section_values, dict) else {}
                for f in fields:
                    fv = row.get(f.id)
                    v = fv.get("value") if isinstance(fv, dict) else None
                    if v is not None:
                        filled[f"{section.id}.{f.id}"] = v
                    elif f.required and f.visible_if is None:
                        missing_required.append(f"{section.id}.{f.id}")

        completion = state.completion
        return {
            "ok": True,
            "step_id": state.step_id,
            "filled": filled,
            "missing_required": missing_required,
            "required_filled": completion.required_filled if completion else 0,
            "required_total": completion.required_total if completion else 0,
            "complete": bool(completion and completion.complete),
        }

    # ── Handler: advance_step ────────────────────────────────────────────────

    async def _advance_step(self, args: dict[str, Any]) -> dict[str, Any]:
        state = await self._repo.get_state(self._session_id)
        if state is None:
            return {"ok": False, "error": "session state not found"}

        # AP-4 fix: validate confirmation_transcript is genuinely user-spoken.
        # Without this Gemini can call with zero args when the user's prior
        # utterance happened to end with "okay" — that is not consent.
        confirmation = (args.get("confirmation_transcript") or "").strip()
        if len(confirmation) < 3:
            return {
                "ok": False,
                "rejection": {
                    "code": "missing_confirmation",
                    "reason_human": (
                        "I need a clear yes from you before I save and move on — "
                        "could you confirm you're happy with everything you've shared?"
                    ),
                },
            }

        # Require at least one affirmative token — prevents "no thanks" or a
        # random sentence fragment from being treated as consent.
        _affirmative = frozenset({
            "yes", "yeah", "yep", "yup", "correct", "confirmed", "confirm",
            "right", "ok", "okay", "proceed", "go", "done", "sure",
            "absolutely", "good", "perfect", "sounds good", "that's right",
            "thats right", "all good",
        })
        confirmation_words = set(confirmation.lower().split())
        # Also check for multi-word phrases in the raw string
        confirmation_lower = confirmation.lower()
        has_affirmative = bool(confirmation_words & _affirmative) or any(
            phrase in confirmation_lower
            for phrase in (
                "that's right", "thats right", "sounds good", "all good",
                "that's all", "thats all", "that's everything", "all done",
                "i'm done", "im done", "we're done", "that's correct",
            )
        )
        if not has_affirmative:
            return {
                "ok": False,
                "rejection": {
                    "code": "missing_confirmation",
                    "reason_human": (
                        "I need a clear yes or confirmation before I can save and "
                        "move on — could you say yes or confirmed to proceed?"
                    ),
                },
            }

        # Idempotency guard — prevent double webhook fire across resume-then-advance
        if state.completed:
            return {"ok": True, "webhook_delivered": False, "already_completed": True}

        # Reject if any required field still has a pending validation error
        if state.pending_validation_errors:
            return {
                "ok": False,
                "error": (
                    f"{len(state.pending_validation_errors)} field(s) have unresolved "
                    "validation errors — re-ask them before advancing"
                ),
                "pending_errors": state.pending_validation_errors,
            }

        # V4 — Section-min gate: repeatable sections with min > 0 must have
        # enough rows before we allow the step to advance.  Runs BEFORE
        # recompute_completion because row-count is a structural prerequisite —
        # you cannot meaningfully evaluate per-field completeness inside a
        # repeatable section until the section exists.  Placing it here also
        # gives the agent a precise, actionable error ("add a morning routine
        # entry") rather than the generic "required fields unfilled" message
        # that recompute_completion would produce for the same condition.
        unmet_sections = [
            s for s in self._schema.sections
            if _section_min_unmet(s, state.values.get(s.id))
        ]
        if unmet_sections:
            section_min_missing: list[dict] = [
                {
                    "section_id": s.id,
                    "field_id": "__section_min__",
                    "label": (
                        f"At least {s.repeatable.min} "
                        f"{s.label or s.id} "
                        f"entr{'y' if s.repeatable.min == 1 else 'ies'} required"
                    ),
                }
                for s in unmet_sections
            ]
            await self._emit({
                "type": "field_skipped_warning",
                "missing_count": len(section_min_missing),
                "required_filled": 0,
                "required_total": len(section_min_missing),
                "missing_fields": section_min_missing,
            })
            return {
                "ok": False,
                "error": "section_min_unmet",
                "sections": [s.id for s in unmet_sections],
                "message": (
                    "Please add at least one entry to: "
                    + ", ".join(s.label or s.id for s in unmet_sections)
                ),
            }

        # Re-validate completion before firing webhook — model may be optimistic
        state.recompute_completion(self._schema)
        if state.completion and not state.completion.complete:
            missing = state.completion.required_total - state.completion.required_filled
            # Enumerate exactly which required fields are still empty so Flutter
            # can highlight them and the Gemini prompt injection is precise.
            missing_fields: list[dict] = []
            for sec in self._schema.sections:
                sec_vals = state.values.get(sec.id)
                if sec.is_repeatable:
                    rows = sec_vals if isinstance(sec_vals, list) else []
                    for idx, row in enumerate(rows):
                        for f in sec.all_fields():
                            if not f.required or f.visible_if is not None:
                                continue
                            fv = (row or {}).get(f.id)
                            if (fv.get("value") if isinstance(fv, dict) else None) is None:
                                missing_fields.append({
                                    "section_id": sec.id,
                                    "field_id": f.id,
                                    "repeatable_index": idx,
                                })
                else:
                    row = sec_vals if isinstance(sec_vals, dict) else {}
                    for f in sec.all_fields():
                        if not f.required or f.visible_if is not None:
                            continue
                        fv = row.get(f.id)
                        if (fv.get("value") if isinstance(fv, dict) else None) is None:
                            missing_fields.append({
                                "section_id": sec.id,
                                "field_id": f.id,
                            })
            await self._emit({
                "type": "field_skipped_warning",
                "missing_count": missing,
                "required_filled": state.completion.required_filled,
                "required_total": state.completion.required_total,
                "missing_fields": missing_fields,
            })
            return {
                "ok": False,
                "error": f"{missing} required field(s) still unfilled — "
                         f"do not call advance_step yet",
                "required_filled": state.completion.required_filled,
                "required_total": state.completion.required_total,
            }

        # N-2 fix: cross-field invariant gate (NDIS compliance).
        # In advisory mode all cross-field violations are emitted as warnings and
        # advance proceeds — Flutter submit-button is the sole blocking gate.
        # validate_required_only (not validate_step_complete) is used here so that
        # cross-field rules are skipped — all 5 are intentionally advisory on voice.
        # In strict mode (advisory=False) the original blocking behaviour is preserved.
        if settings.onboarding_voice_validation_advisory:
            cross_rejections = _validate_required_only(self._schema, state)
            for rej in cross_rejections:
                await self._emit({
                    "type": "field_advisory_warning",
                    "section_id": "_aggregate",
                    "field_id": "_aggregate",
                    "code": rej.code,
                    "reason_human": rej.reason_human,
                    "severity": "advisory",
                })
            # Do NOT return — advisory violations do not block advance
        else:
            cross_rejections = validate_step_complete(self._schema, state)
            if cross_rejections:
                for rej in cross_rejections:
                    await self._emit({
                        "type": "validation_rejection",
                        "section_id": "_aggregate",
                        "field_id": "_aggregate",
                        "rejection": rej.model_dump(),
                    })
                return {
                    "ok": False,
                    "rejection": {
                        "code": "cross_field_invariants_failed",
                        "reason_human": cross_rejections[0].reason_human,
                        "all_rejections": [r.model_dump() for r in cross_rejections],
                    },
                }

        state.completed = True
        state.completed_at = datetime.now(UTC)
        await self._repo.save_state(state, ttl_sec=settings.session_max_sec)

        transcript = await self._repo.get_transcript(self._session_id)
        payload = {
            "event": "onboarding.session.completed",
            "session_id": self._session_id,
            "participant_id": state.participant_id,
            "tenant_id": state.tenant_id,
            "step": state.step_id,
            "state": state.model_dump(mode="json"),
            "transcript": transcript,
            "confirmation_transcript": args.get("confirmation_transcript"),
            "started_at": state.started_at.isoformat(),
            "completed_at": state.completed_at.isoformat(),
        }

        delivered = await fire_webhook(
            url=settings.app_webhook_url,
            event="onboarding.session.completed",
            payload=payload,
            secret=settings.app_webhook_secret,
            max_retries=settings.onboarding_webhook_max_retries,
        )

        await self._emit({
            "type": "step_completed",
            "state": state.model_dump(mode="json"),
            "webhook_delivered": delivered,
        })

        # Flag WS loop to close cleanly after the model sends its farewell
        self.step_completed = True

        return {"ok": True, "webhook_delivered": delivered}

    # ── Handler: escalate_incident ───────────────────────────────────────────

    async def _escalate_incident(self, args: dict[str, Any]) -> dict[str, Any]:
        reason = args.get("reason", "other")
        excerpt = args.get("transcript_excerpt")

        state = await self._repo.get_state(self._session_id)
        if state is None:
            return {"ok": False, "error": "session state not found"}

        state.escalations.append(
            EscalationRecord(reason=reason, transcript_excerpt=excerpt)
        )
        state.touch()
        await self._repo.save_state(state, ttl_sec=settings.session_max_sec)

        log.warning(
            "escalation session=%s reason=%s excerpt=%r",
            self._session_id, reason, excerpt,
        )

        await self._emit({
            "type": "escalated",
            "reason": reason,
            "transcript_excerpt": excerpt,
        })

        return {"ok": True, "logged": True}

    # ── Handler: add_repeatable_row ──────────────────────────────────────────

    async def _add_repeatable_row(self, args: dict[str, Any]) -> dict[str, Any]:
        section_id = args.get("section_id", "").strip()
        if not section_id:
            return {"ok": False, "error": "section_id required"}

        section = self._schema.get_section(section_id)
        if section is None:
            return {"ok": False, "error": f"unknown section: {section_id}"}
        if not section.is_repeatable:
            return {"ok": False, "error": f"not repeatable: {section_id}"}
        if not is_repeatable_eligible(section_id, self._schema):
            return {"ok": False, "error": f"section not voice-eligible: {section_id}"}

        state = await self._repo.get_state(self._session_id)
        if state is None:
            return {"ok": False, "error": "session state not found"}

        if section.repeatable and len(state.values.get(section_id) or []) >= section.repeatable.max:
            return {
                "ok": False,
                "error": f"max rows ({section.repeatable.max}) reached for {section_id}",
            }

        new_index = state.increment_repeatable_row(section_id)
        # Auto-pin focus to the new row so any immediate update_field call
        # doesn't hit cross_section_blocked — agent doesn't need a separate
        # enter_repeatable_section after add_repeatable_row.
        state.focused_section = section_id
        state.focused_repeatable_index = new_index
        state.touch()
        await self._repo.save_state(state, ttl_sec=settings.session_max_sec)

        await self._emit({
            "type": "row_added",
            "section_id": section_id,
            "new_index": new_index,
        })
        await self._emit({
            "type": "repeatable_section_entered",
            "section_id": section_id,
            "intent": "next",
            "row_index": new_index,
        })

        return {"ok": True, "section_id": section_id, "new_index": new_index}

    # ── Handler: policy_block ────────────────────────────────────────────────

    async def _policy_block(self, args: dict[str, Any]) -> dict[str, Any]:
        raise PolicyBlockSignal(args.get("question", ""))

    # ── Handler: enter_repeatable_section ────────────────────────────────────

    async def _enter_repeatable_section(self, args: dict[str, Any]) -> dict[str, Any]:
        section_id = args.get("section_id", "").strip()
        intent = args.get("intent", "first")

        if not section_id:
            return {"ok": False, "error": "section_id required"}

        section = self._schema.get_section(section_id)
        if section is None:
            return {"ok": False, "error": f"unknown section: {section_id}"}
        if not section.is_repeatable:
            return {"ok": False, "error": f"not repeatable: {section_id}"}

        state = await self._repo.get_state(self._session_id)
        if state is None:
            return {"ok": False, "error": "session state not found"}

        current_rows = state.values.get(section_id)
        existing_count = len(current_rows) if isinstance(current_rows, list) else 0

        if intent == "first":
            row_index = 0
            if existing_count == 0:
                state.values[section_id] = [{}]
        else:
            row_index = existing_count if existing_count > 0 else 0

        state.focused_section = section_id
        state.focused_repeatable_index = row_index
        state.touch()
        await self._repo.save_state(state, ttl_sec=settings.session_max_sec)

        await self._emit({
            "type": "repeatable_section_entered",
            "section_id": section_id,
            "row_index": row_index,
            "intent": intent,
        })

        return {"ok": True, "section_id": section_id, "row_index": row_index, "intent": intent}

    # ── Handler: exit_repeatable_section ─────────────────────────────────────

    async def _exit_repeatable_section(self, _args: dict[str, Any]) -> dict[str, Any]:
        state = await self._repo.get_state(self._session_id)
        if state is None:
            return {"ok": False, "error": "session state not found"}

        exited = state.focused_section
        state.focused_section = None
        state.focused_repeatable_index = None
        state.touch()
        await self._repo.save_state(state, ttl_sec=settings.session_max_sec)

        await self._emit({
            "type": "repeatable_section_exited",
            "section_id": exited,
        })

        return {"ok": True, "exited_section": exited}

    # ── Handler: request_unknown_section ─────────────────────────────────────

    async def _request_unknown_section(self, args: dict[str, Any]) -> dict[str, Any]:
        section_id = args.get("section_id", "")
        label = args.get("label", section_id)

        log.info(
            "unknown_section_request session=%s attempted_section=%s label=%r",
            self._session_id,
            section_id,
            label,
        )
        await self._emit({
            "type": "schema_drift_detected",
            "kind": "unknown_section",
            "attempted_section": section_id,
            "label": label,
        })

        return {
            "ok": True,
            "message": (
                f"Noted — '{label}' isn't part of this form, but we've logged "
                "the request for the team. Let's keep going with what we have."
            ),
        }

    # ── Default emit: send over WS ───────────────────────────────────────────

    async def _default_emit(self, event: dict[str, Any]) -> None:
        try:
            await self._ws.send_text(json.dumps(event, default=str))
        except Exception:
            log.exception("emit_failed session=%s event=%s",
                          self._session_id, event.get("type"))
