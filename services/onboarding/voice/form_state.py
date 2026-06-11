from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

from schema_spec import StepSchema


def _utcnow() -> datetime:
    return datetime.now(UTC)


class FieldSource(str, Enum):
    voice = "voice"
    app = "app"
    system = "system"


class FieldValue(BaseModel):
    value: Any
    source: FieldSource = FieldSource.voice
    # User-intent marker. Optional (None) when the writer is the system / a
    # server-stamped handler with no human input — e.g. auto-copy mirroring.
    # Set to "voice" by the Gemini tool dispatcher and to "typed" by future
    # app-driven flows that distinguish keyboard from voice authoring.
    # Kept optional so existing serialised FormState payloads still deserialise.
    input_method: Literal["typed", "voice"] | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    turn_id: int | None = None
    updated_at: datetime = Field(default_factory=_utcnow)
    # True when the agent has verbally confirmed this field value with the
    # participant during the current WS session. Defaults False so existing
    # Redis-serialised payloads deserialise without error.
    confirmed_in_session: bool = False


class EscalationRecord(BaseModel):
    reason: str
    transcript_excerpt: str | None = None
    timestamp: datetime = Field(default_factory=_utcnow)


class CompletionStats(BaseModel):
    required_total: int
    required_filled: int
    optional_total: int
    optional_filled: int

    @property
    def complete(self) -> bool:
        return self.required_filled >= self.required_total

    @property
    def percent(self) -> int:
        if self.required_total == 0:
            return 100
        return int((self.required_filled / self.required_total) * 100)


class TranscriptEntry(BaseModel):
    speaker: str  # "user" | "agent"
    text: str
    turn_id: int
    timestamp: datetime = Field(default_factory=_utcnow)


class FormState(BaseModel):
    session_id: str
    step_id: str
    participant_id: str
    tenant_id: str | None = None
    locale: str = "en-AU"
    started_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    # section_id → {field_id: FieldValue | None}
    # For repeatable sections: section_id → list[{field_id: FieldValue | None}]
    values: dict[str, Any] = Field(default_factory=dict)

    completion: CompletionStats | None = None
    transcript_count: int = 0
    escalations: list[EscalationRecord] = Field(default_factory=list)

    # Set True when a WS connection holds the write lock
    ws_active: bool = False
    # Set True when advance_step fires
    completed: bool = False
    completed_at: datetime | None = None
    repeatable_rows: dict[str, int] = Field(default_factory=dict)

    # Sequencing / validation state (PRD-validation-sequencing-discovery)
    focused_section: str | None = None
    focused_repeatable_index: int | None = None
    # Deduped by (section_id, field_id, repeatable_index). Each entry:
    # {section_id, field_id, repeatable_index, code, reason_human}
    pending_validation_errors: list[dict] = Field(default_factory=list)

    # M1 — PENDING_CONFIRMATION lock. While set, update_field for ANY field
    # other than the locked one is rejected with code PENDING_CONFIRMATION_LOCKED.
    # Cleared when the user explicitly confirms (or restates the value).
    # Shape: {"section": str, "field": str, "heard_value": Any,
    #         "repeatable_index": int | None, "set_at": iso8601}
    pending_confirmation: dict | None = None

    # M5 — Conditional follow-up driver. After update_field commits a value
    # that unlocks a `visible_if` dependant, the dispatcher writes that
    # dependant here. The prompt renderer then surfaces it as
    # next_required_field so the model has no choice but to ask it next.
    # Shape: {"section": str, "field": str}
    next_forced_field: dict | None = None

    # C2 — Deferred batch buffer. While pending_confirmation is set,
    # cross-row / cross-section update_field calls are appended here
    # instead of being rejected. Drained automatically when the lock
    # clears (target field successfully commits).
    # Each entry shape: {"section": str, "field": str,
    #                    "value": Any, "values": list|None,
    #                    "confidence": float, "repeatable_index": int|None}
    pending_batch: list[dict] = Field(default_factory=list)

    def touch(self) -> None:
        self.updated_at = _utcnow()

    def increment_repeatable_row(self, section_id: str) -> int:
        current = self.repeatable_rows.get(section_id, 0)
        self.repeatable_rows[section_id] = current + 1
        self.touch()
        return current

    def recompute_completion(self, schema: StepSchema) -> None:
        req_total = req_filled = opt_total = opt_filled = 0
        for section in schema.sections:
            fields = section.item_fields if section.is_repeatable else (section.fields or [])
            items = self.values.get(section.id)
            row_list = items if isinstance(items, list) else [items or {}]
            for row in row_list:
                for f in fields:
                    if f.visible_if:
                        # Check condition against current row values
                        cond_field, cond_val = next(iter(f.visible_if.items()))
                        row_val = (row.get(cond_field) or {})
                        actual = row_val.get("value") if isinstance(row_val, dict) else None
                        if actual != cond_val:
                            continue
                    if f.required:
                        req_total += 1
                        if row and row.get(f.id) and row[f.id].get("value") is not None:
                            req_filled += 1
                    else:
                        opt_total += 1
                        if row and row.get(f.id) and row[f.id].get("value") is not None:
                            opt_filled += 1
        self.completion = CompletionStats(
            required_total=req_total,
            required_filled=req_filled,
            optional_total=opt_total,
            optional_filled=opt_filled,
        )

    def set_field(
        self,
        section_id: str,
        field_id: str,
        value: Any,
        source: FieldSource = FieldSource.voice,
        confidence: float = 1.0,
        turn_id: int | None = None,
        repeatable_index: int | None = None,
        input_method: Literal["typed", "voice"] | None = None,
        confirmed_in_session: bool = False,
    ) -> None:
        fv = FieldValue(
            value=value,
            source=source,
            confidence=confidence,
            turn_id=turn_id,
            input_method=input_method,
            confirmed_in_session=confirmed_in_session,
        )
        if repeatable_index is not None:
            if section_id not in self.values or not isinstance(self.values[section_id], list):
                self.values[section_id] = []
            while len(self.values[section_id]) <= repeatable_index:
                self.values[section_id].append({})
            self.values[section_id][repeatable_index][field_id] = fv.model_dump(mode="json")
        else:
            if section_id not in self.values or isinstance(self.values[section_id], list):
                self.values[section_id] = {}
            self.values[section_id][field_id] = fv.model_dump(mode="json")
        self.touch()
