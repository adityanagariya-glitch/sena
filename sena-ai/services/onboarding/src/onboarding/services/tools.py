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
from onboarding.repositories.state_repo import FormStateRepo
from onboarding.services import field_apply as _fa
from onboarding.services.coverage import is_repeatable_eligible
from onboarding.services.webhook import fire_webhook

log = logging.getLogger(__name__)


# ── Function declarations sent to Gemini ─────────────────────────────────────

FUNCTION_DECLS: list[dict[str, Any]] = [
    {
        "name": "update_field",
        "description": (
            "Record a value the user provided for a specific field. "
            "Call this every time you capture a field value. "
            "Use confidence < 0.6 when the user was ambiguous or you had to guess."
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
                    "description": "The captured value as a string; booleans use 'true'/'false'.",
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
            },
            "required": ["section", "field", "value"],
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
        raw_value = args.get("value")
        repeatable_index = args.get("repeatable_index")
        confidence = float(args.get("confidence", 1.0))

        if not section_id or not field_id:
            return {"ok": False, "error": "section and field are required"}

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
            return {"ok": False, "error": f"unknown section: {section_id}"}

        field: FieldSpec | None = next(
            (f for f in section.all_fields() if f.id == field_id), None
        )
        if field is None:
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

        # Re-validate completion before firing webhook — model may be optimistic
        state.recompute_completion(self._schema)
        if state.completion and not state.completion.complete:
            missing = state.completion.required_total - state.completion.required_filled
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

    # ── Default emit: send over WS ───────────────────────────────────────────

    async def _default_emit(self, event: dict[str, Any]) -> None:
        try:
            await self._ws.send_text(json.dumps(event, default=str))
        except Exception:
            log.exception("emit_failed session=%s event=%s",
                          self._session_id, event.get("type"))
