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
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket

from onboarding.core.settings import settings
from onboarding.models.form_state import (
    EscalationRecord,
    FieldSource,
    FormState,
)
from onboarding.models.schema_spec import FieldSpec, SectionSpec, StepSchema
from onboarding.models.session_bootstrap import SessionBootstrap
from onboarding.repositories.state_repo import FormStateRepo
from onboarding.services import field_apply as _fa
from onboarding.services.coverage import is_repeatable_eligible
from onboarding.services.validators import validate_field as _validate_field
from onboarding.services.webhook import fire_webhook

log = logging.getLogger(__name__)


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
            "Call ONLY when every required field is filled and the user has confirmed "
            "they are done with this step. Finalizes the session and notifies the app."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "confirmation_transcript": {
                    "type": "string",
                    "description": "Exact words the user used to confirm they are done.",
                },
            },
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
    state.pending_validation_errors.append({
        "section_id": section_id,
        "field_id": field_id,
        "repeatable_index": repeatable_index,
        "code": rej.code,
        "reason_human": rej.reason_human,
    })


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

        if not section_id or not field_id:
            return {"ok": False, "error": "section and field are required"}
        if raw_value is None:
            return {
                "ok": False,
                "error": "either 'value' (scalar) or 'values' (array) is required",
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
                "see FLUTTER_VOICE_INTEGRATION_FIXES.md Issue 3.",
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

        if repeatable_index is not None and section.repeatable:
            if repeatable_index >= section.repeatable.max:
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

        # Cross-section guard — reject writes to sections other than the focused one
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
        rej = _validate_field(
            section_id, field_id, typed_value,
            repeatable_index=_ri,
            state=state,
        )
        if rej is not None:
            _upsert_validation_error(state, section_id, field_id, _ri, rej)
            await self._repo.save_state(state, ttl_sec=settings.session_max_sec)
            log.info(
                "validation_rejection section=%s field=%s code=%s session=%s",
                section_id, field_id, rej.code, self._session_id,
            )
            return {"ok": False, "rejection": rej.model_dump()}

        # Clear any prior error for this field — validation now passes
        _clear_validation_error(state, section_id, field_id, _ri)

        state.set_field(
            section_id=section_id,
            field_id=field_id,
            value=typed_value,
            source=FieldSource.voice,
            confidence=confidence,
            turn_id=self._turn_id,
            repeatable_index=repeatable_index if section.is_repeatable else None,
        )
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
        await self._emit({"type": "state", "state": state.model_dump(mode="json")})

        envelope = _fa.build_envelope(
            section_id,
            field_id,
            typed_value,
            row_index=repeatable_index if section.is_repeatable else None,
            confidence=confidence,
            schema=self._schema,
            enforced=settings.voice_coverage_enforced,
        )
        if envelope is not None:
            await self._emit(envelope)

        completion = state.completion
        return {
            "ok": True,
            "section": section_id,
            "field": field_id,
            "value": typed_value,
            "required_filled": completion.required_filled if completion else 0,
            "required_total": completion.required_total if completion else 0,
            "complete": bool(completion and completion.complete),
        }

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

        state.completed = True
        state.completed_at = datetime.now(timezone.utc)
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
        await self._repo.save_state(state, ttl_sec=settings.session_max_sec)

        await self._emit({
            "type": "row_added",
            "section_id": section_id,
            "new_index": new_index,
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
