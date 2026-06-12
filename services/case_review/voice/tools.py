"""
Tool dispatcher for the case-note voice assistant.

Five tools are exposed to Gemini Live:
  - update_field          Record a captured value into CaseNoteVoiceState
  - clear_field           Blank a previously-filled field
  - get_session_context   Return a condensed snapshot of filled vs missing
  - finish_session        All required fields done → emit session_complete
  - escalate_incident     Abuse / self-harm / injury / safety flag → log + continue

Design: pure async, no Gemini SDK imports — keeps dispatch unit-testable.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from config import settings
from voice.state import CaseNoteVoiceState, EscalationRecord, FieldSource

if TYPE_CHECKING:
    from fastapi import WebSocket

    from voice.schema_spec import FieldSpec, StepSchema
    from voice.session_bootstrap import SessionBootstrap
    from voice.state_repo import VoiceStateRepo

from voice.validators.sequencing import validate_step_complete

log = structlog.get_logger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _matches_visible_if(expected: Any, actual: Any) -> bool:
    def _norm(x: Any) -> Any:
        if isinstance(x, str) and x.lower() in ("true", "false"):
            return x.lower() == "true"
        return x
    return _norm(expected) == _norm(actual)


def _field_is_filled(state: CaseNoteVoiceState, section_id: str, field_id: str) -> bool:
    section_data = state.values.get(section_id)
    if isinstance(section_data, dict):
        fv = section_data.get(field_id)
        if isinstance(fv, dict):
            v = fv.get("value")
            return v not in (None, "", [], {})
    return False


def _set_next_forced_field(
    state: CaseNoteVoiceState,
    schema: "StepSchema",
    just_set_section: str,
    just_set_field: str,
    just_set_value: Any,
) -> None:
    """M5 — After update_field, scan for visible_if dependants that just unlocked."""
    forced = state.next_forced_field
    if forced and forced.get("section") == just_set_section and forced.get("field") == just_set_field:
        state.next_forced_field = None

    if state.next_forced_field is not None:
        forced_section = state.next_forced_field.get("section")
        forced_field = state.next_forced_field.get("field")
        if forced_section == just_set_section:
            for section in schema.sections:
                if section.id != forced_section:
                    continue
                for f in (section.fields or []):
                    if f.id != forced_field:
                        continue
                    vif = getattr(f, "visible_if", None)
                    if vif and just_set_field in vif:
                        expected = vif[just_set_field]
                        if not _matches_visible_if(expected, just_set_value):
                            state.next_forced_field = None
                break

    for section in schema.sections:
        if section.id != just_set_section:
            continue
        for f in (section.fields or []):
            vif = getattr(f, "visible_if", None)
            if not vif or just_set_field not in vif:
                continue
            expected = vif[just_set_field]
            if _matches_visible_if(expected, just_set_value) and not _field_is_filled(
                state, section.id, f.id
            ):
                state.next_forced_field = {"section": section.id, "field": f.id}
                return


def _coerce_value(raw: Any, field: "FieldSpec") -> Any:
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
            return raw if isinstance(raw, list) else [x.strip() for x in s.split(",") if x.strip()]
        if ftype == "enum" and field.options:
            import re as _re
            def _normalise(v: str) -> str:
                return _re.sub(r"[-_\s]+", " ", v).strip().lower()
            s_norm = _normalise(s)
            for opt in field.options:
                if _normalise(opt) == s_norm:
                    return opt
    except (ValueError, TypeError):
        return raw
    return s


def _upsert_validation_error(
    state: CaseNoteVoiceState,
    section_id: str,
    field_id: str,
    rej: Any,
) -> None:
    key = (section_id, field_id, None)
    state.pending_validation_errors = [
        e for e in state.pending_validation_errors
        if (e.get("section_id"), e.get("field_id"), e.get("repeatable_index")) != key
    ]
    entry: dict = {
        "section_id": section_id,
        "field_id": field_id,
        "repeatable_index": None,
        "code": rej.code,
        "reason_human": rej.reason_human,
    }
    if getattr(rej, "allowed_values", None) is not None:
        entry["allowed_values"] = rej.allowed_values
    state.pending_validation_errors.append(entry)


def _clear_validation_error(
    state: CaseNoteVoiceState,
    section_id: str,
    field_id: str,
) -> None:
    key = (section_id, field_id, None)
    state.pending_validation_errors = [
        e for e in state.pending_validation_errors
        if (e.get("section_id"), e.get("field_id"), e.get("repeatable_index")) != key
    ]


# ── FUNCTION_DECLS sent to Gemini ─────────────────────────────────────────────

FUNCTION_DECLS: list[dict[str, Any]] = [
    {
        "name": "update_field",
        "description": (
            "Record a value the support worker provided for a specific case-note field. "
            "Call immediately when a field value is captured — BEFORE acknowledging verbally. "
            "Use confidence < 0.6 when the worker was ambiguous or you had to guess."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "description": (
                        "Section id from the schema. One of: shift, summary, activities, "
                        "wellbeing, outcomes, safety, incidents."
                    ),
                },
                "field": {
                    "type": "string",
                    "description": "Field id from the schema (e.g. 'mood', 'assisted', 'shift_date').",
                },
                "value": {
                    "type": "string",
                    "description": (
                        "Captured value as a string. Booleans use 'true'/'false'."
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
        "name": "clear_field",
        "description": (
            "Clear a previously-filled field when the worker says 'remove that', "
            "'clear that', 'delete that', or 'start over'. "
            "Call BEFORE acknowledging removal. Server rejects on readonly fields."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "description": "Section id (e.g. 'safety', 'activities').",
                },
                "field": {
                    "type": "string",
                    "description": "Field id within the section.",
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
        "name": "finish_session",
        "description": (
            "Call ONLY after every required field is filled AND the worker has spoken "
            "an explicit confirmation (e.g. 'yes I'm done', 'that's everything', 'submit it'). "
            "Pass the worker's exact confirmation words in confirmation_transcript."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "confirmation_transcript": {
                    "type": "string",
                    "minLength": 3,
                    "description": (
                        "EXACT verbatim words the worker spoke to confirm completion. "
                        "Required and non-empty. Do not paraphrase."
                    ),
                },
            },
            "required": ["confirmation_transcript"],
        },
    },
    {
        "name": "escalate_incident",
        "description": (
            "Call immediately if the worker describes abuse, self-harm, a serious injury, "
            "or an unsafe situation. Does NOT end the session — continue calmly after calling."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "enum": ["abuse", "self_harm", "serious_injury", "unsafe_situation"],
                },
                "transcript_excerpt": {
                    "type": "string",
                    "description": "Short quote from the worker that triggered the escalation.",
                },
            },
            "required": ["reason"],
        },
    },
]

# ── Policy block tool (grounding-off fallback) ───────────────────────────────

POLICY_BLOCK_DECL: dict[str, Any] = {
    "name": "policy_block",
    "description": (
        "Call this ONLY when the worker asks a specific current NDIS policy or legislative "
        "question requiring up-to-date search data you do not have. "
        "Calling this ends the session."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The exact policy question the worker asked.",
            },
        },
        "required": ["question"],
    },
}


# ── PolicyBlockSignal ─────────────────────────────────────────────────────────

class PolicyBlockSignal(BaseException):
    def __init__(self, question: str) -> None:
        self.question = question
        super().__init__(question)


# ── ToolDispatcher ────────────────────────────────────────────────────────────

class ToolDispatcher:
    def __init__(
        self,
        websocket: "WebSocket",
        session_id: str,
        repo: "VoiceStateRepo",
        schema: "StepSchema",
        *,
        emit: Callable[..., Any] | None = None,
    ) -> None:
        self._ws = websocket
        self._session_id = session_id
        self._repo = repo
        self._schema = schema
        self._emit = emit
        self._turn_id = 0
        self.step_completed = False

    def set_turn_id(self, turn_id: int) -> None:
        self._turn_id = turn_id

    async def _send(self, payload: dict) -> None:
        await self._ws.send_text(json.dumps(payload, default=str))

    async def dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        handlers: dict[str, Any] = {
            "update_field": self._update_field,
            "clear_field": self._clear_field,
            "get_session_context": self._get_session_context,
            "finish_session": self._finish_session,
            "escalate_incident": self._escalate_incident,
            "policy_block": self._policy_block,
        }
        handler = handlers.get(name)
        if handler is None:
            log.warning("unknown_tool name=%s session=%s", name, self._session_id)
            return {"ok": False, "error": "unknown_tool", "tool": name}
        return await handler(**args)

    # ── update_field ─────────────────────────────────────────────────────────

    async def _update_field(
        self,
        section: str,
        field: str,
        value: Any = None,
        confidence: float = 1.0,
        **_: Any,
    ) -> dict[str, Any]:
        state = await self._repo.get_state(self._session_id)
        if state is None:
            return {"ok": False, "error": "session_not_found"}

        # Readonly check
        bootstrap = await self._repo.get_bootstrap(self._session_id)
        readonly_paths = bootstrap.readonly_paths if bootstrap else []
        if f"{section}.{field}" in readonly_paths:
            return {"ok": False, "error": "readonly_field", "section": section, "field": field}

        # Section + field existence
        section_spec = self._schema.get_section(section)
        if section_spec is None:
            return {"ok": False, "error": "unknown_section", "section": section}
        field_spec = self._schema.get_field_spec(section, field)
        if field_spec is None:
            return {"ok": False, "error": "unknown_field", "section": section, "field": field}

        # Pending confirmation lock (M1)
        pc = state.pending_confirmation
        if pc and (pc.get("section") != section or pc.get("field") != field):
            # Defer to batch if a different field is locked
            state.pending_batch.append({
                "section": section,
                "field": field,
                "value": value,
                "confidence": confidence,
            })
            await self._repo.save_state(state, ttl_sec=settings.voice_session_max_sec)
            return {"ok": True, "deferred": True, "reason": "pending_confirmation_lock"}

        # Coerce value
        typed_value = _coerce_value(value, field_spec)

        # Advisory validation
        from voice.validators.field_rules import validate_field
        rej = validate_field(section, field, typed_value, repeatable_index=None, state=state, field_spec=field_spec)
        if rej and settings.voice_validation_advisory:
            _upsert_validation_error(state, section, field, rej)
            await self._repo.save_state(state, ttl_sec=settings.voice_session_max_sec)
            await self._send({
                "type": "validation_rejection",
                "section_id": section,
                "field_id": field,
                "code": rej.code,
                "reason_human": rej.reason_human,
            })
            return {"ok": False, "rejections": [rej.model_dump()]}

        # Confidence lock — M1 pending_confirmation
        if confidence < 0.6:
            state.pending_confirmation = {
                "section": section,
                "field": field,
                "heard_value": typed_value,
                "set_at": _utcnow_iso(),
            }
            state.set_field(
                section, field, typed_value,
                source=FieldSource.voice,
                confidence=confidence,
                turn_id=self._turn_id,
                input_method="voice",
            )
            state.recompute_completion(self._schema)
            _clear_validation_error(state, section, field)
            await self._repo.save_state(state, ttl_sec=settings.voice_session_max_sec)
            await self._send({
                "type": "field_updated",
                "section_id": section,
                "field_id": field,
                "value": typed_value,
                "confidence": confidence,
                "pending_confirmation": True,
            })
            return {
                "ok": True,
                "pending_confirmation": True,
                "heard_value": typed_value,
                "instruction": (
                    f"Low confidence ({confidence:.0%}). "
                    f"Read back the captured value and ask the worker to confirm: "
                    f"\"I heard {typed_value} — is that right?\""
                ),
            }

        # Clear any M1 lock if this is the locked field being confirmed
        if pc and pc.get("section") == section and pc.get("field") == field:
            state.pending_confirmation = None
            # Drain deferred batch
            batch = state.pending_batch[:]
            state.pending_batch = []
            for deferred in batch:
                state.set_field(
                    deferred["section"], deferred["field"], deferred["value"],
                    source=FieldSource.voice,
                    confidence=deferred.get("confidence", 1.0),
                    turn_id=self._turn_id,
                    input_method="voice",
                )

        # Commit value
        state.set_field(
            section, field, typed_value,
            source=FieldSource.voice,
            confidence=confidence,
            turn_id=self._turn_id,
            input_method="voice",
            confirmed_in_session=True,
        )
        _clear_validation_error(state, section, field)
        _set_next_forced_field(state, self._schema, section, field, typed_value)
        state.recompute_completion(self._schema)
        await self._repo.save_state(state, ttl_sec=settings.voice_session_max_sec)

        await self._send({
            "type": "field_updated",
            "section_id": section,
            "field_id": field,
            "value": typed_value,
            "confidence": confidence,
        })
        await self._send({
            "type": "state",
            "completion": state.completion.model_dump() if state.completion else None,
        })

        return {"ok": True, "section": section, "field": field, "value": typed_value}

    # ── clear_field ───────────────────────────────────────────────────────────

    async def _clear_field(self, section: str, field: str, **_: Any) -> dict[str, Any]:
        state = await self._repo.get_state(self._session_id)
        if state is None:
            return {"ok": False, "error": "session_not_found"}

        bootstrap = await self._repo.get_bootstrap(self._session_id)
        readonly_paths = bootstrap.readonly_paths if bootstrap else []
        if f"{section}.{field}" in readonly_paths:
            return {"ok": False, "error": "readonly_field", "section": section, "field": field}

        # Set to None
        state.set_field(section, field, None, source=FieldSource.voice, turn_id=self._turn_id)
        _clear_validation_error(state, section, field)
        state.recompute_completion(self._schema)
        await self._repo.save_state(state, ttl_sec=settings.voice_session_max_sec)

        await self._send({
            "type": "field_updated",
            "section_id": section,
            "field_id": field,
            "value": None,
        })
        await self._send({
            "type": "state",
            "completion": state.completion.model_dump() if state.completion else None,
        })
        return {"ok": True, "section": section, "field": field, "cleared": True}

    # ── get_session_context ───────────────────────────────────────────────────

    async def _get_session_context(self, **_: Any) -> dict[str, Any]:
        state = await self._repo.get_state(self._session_id)
        if state is None:
            return {"ok": False, "error": "session_not_found"}

        from voice.validators.sequencing import next_required_field
        next_req = next_required_field(self._schema, state)
        missing_required: list[str] = []
        if next_req:
            # Collect all missing required fields
            for section in self._schema.sections:
                row = state.values.get(section.id) or {}
                row = row if isinstance(row, dict) else {}
                for f in (section.fields or []):
                    if not f.required:
                        continue
                    if f.visible_if:
                        cond_f, cond_v = next(iter(f.visible_if.items()))
                        actual_raw = row.get(cond_f)
                        actual = actual_raw.get("value") if isinstance(actual_raw, dict) else actual_raw
                        if actual != cond_v:
                            continue
                    raw = row.get(f.id)
                    v = raw.get("value") if isinstance(raw, dict) else raw
                    if v is None or (isinstance(v, str) and not v.strip()):
                        missing_required.append(f"{section.id}.{f.id}")

        filled_count = sum(
            1
            for section in self._schema.sections
            for f in (section.fields or [])
            for raw in [
                (state.values.get(section.id) or {}).get(f.id)
                if isinstance(state.values.get(section.id), dict)
                else None
            ]
            if raw and isinstance(raw, dict) and raw.get("value") is not None
        )
        return {
            "ok": True,
            "missing_required": missing_required,
            "filled_count": filled_count,
            "completion": state.completion.model_dump() if state.completion else None,
        }

    # ── finish_session ────────────────────────────────────────────────────────

    async def _finish_session(
        self, confirmation_transcript: str = "", **_: Any
    ) -> dict[str, Any]:
        if not confirmation_transcript or len(confirmation_transcript.strip()) < 3:
            return {
                "ok": False,
                "error": "confirmation_transcript_too_short",
                "instruction": (
                    "Pass the worker's exact confirmation words. "
                    "Ask them to confirm explicitly (e.g. 'Yes, that's everything')."
                ),
            }

        state = await self._repo.get_state(self._session_id)
        if state is None:
            return {"ok": False, "error": "session_not_found"}

        rejections = validate_step_complete(self._schema, state)
        if rejections:
            missing = [r.suggested_fix or r.reason_human for r in rejections[:5]]
            return {
                "ok": False,
                "rejections": [r.model_dump() for r in rejections],
                "missing_required": missing,
                "instruction": f"Required fields still empty: {', '.join(missing)}",
            }

        state.completed = True
        state.completed_at = datetime.now(UTC)
        await self._repo.save_state(state, ttl_sec=settings.voice_session_max_sec)

        payload = state.to_case_note_payload()
        await self._send({
            "type": "session_complete",
            "session_id": self._session_id,
            "case_note_id": state.case_note_id,
            "payload": payload,
            "completion": state.completion.model_dump() if state.completion else None,
        })

        self.step_completed = True
        log.info(
            "session_complete session=%s case_note_id=%s",
            self._session_id,
            state.case_note_id,
        )
        return {"ok": True, "session_id": self._session_id, "missing_required": []}

    # ── escalate_incident ─────────────────────────────────────────────────────

    async def _escalate_incident(
        self,
        reason: str,
        transcript_excerpt: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        state = await self._repo.get_state(self._session_id)
        if state is None:
            return {"ok": False, "error": "session_not_found"}

        record = EscalationRecord(reason=reason, transcript_excerpt=transcript_excerpt)
        state.escalations.append(record)
        await self._repo.save_state(state, ttl_sec=settings.voice_session_max_sec)

        await self._send({
            "type": "escalated",
            "reason": reason,
            "transcript_excerpt": transcript_excerpt,
            "session_id": self._session_id,
        })
        log.info(
            "incident_escalated session=%s reason=%s",
            self._session_id,
            reason,
        )
        return {"ok": True, "escalated": True, "reason": reason}

    # ── policy_block ──────────────────────────────────────────────────────────

    async def _policy_block(self, question: str = "", **_: Any) -> dict[str, Any]:
        raise PolicyBlockSignal(question)
