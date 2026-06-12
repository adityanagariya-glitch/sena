"""Session state for the case-note voice assistant."""
from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

from voice.schema_spec import StepSchema


def _utcnow() -> datetime:
    return datetime.now(UTC)


class FieldSource(str, Enum):
    voice = "voice"
    app = "app"
    system = "system"
    prefill = "prefill"


class FieldValue(BaseModel):
    value: Any
    source: FieldSource = FieldSource.voice
    input_method: Literal["typed", "voice"] | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    turn_id: int | None = None
    updated_at: datetime = Field(default_factory=_utcnow)
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


class CaseNoteVoiceState(BaseModel):
    session_id: str
    case_note_id: str
    client_id: str
    worker_id: str
    tenant_id: str | None = None
    started_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    # section_id → {field_id: FieldValue dump}
    values: dict[str, Any] = Field(default_factory=dict)

    completion: CompletionStats | None = None
    transcript_count: int = 0
    escalations: list[EscalationRecord] = Field(default_factory=list)

    completed: bool = False
    completed_at: datetime | None = None

    # Sequencing / validation state
    pending_validation_errors: list[dict] = Field(default_factory=list)

    # M1 — pending confirmation lock
    pending_confirmation: dict | None = None

    # M5 — conditional follow-up driver
    next_forced_field: dict | None = None

    # C2 — deferred batch buffer
    pending_batch: list[dict] = Field(default_factory=list)

    def touch(self) -> None:
        self.updated_at = _utcnow()

    def recompute_completion(self, schema: StepSchema) -> None:
        req_total = req_filled = opt_total = opt_filled = 0
        for section in schema.sections:
            fields = section.fields or []
            sec_vals = self.values.get(section.id) or {}
            row = sec_vals if isinstance(sec_vals, dict) else {}
            for f in fields:
                if f.visible_if:
                    cond_field, cond_val = next(iter(f.visible_if.items()))
                    row_val = row.get(cond_field) or {}
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
        if section_id not in self.values or isinstance(self.values[section_id], list):
            self.values[section_id] = {}
        self.values[section_id][field_id] = fv.model_dump(mode="json")
        self.touch()

    def to_case_note_payload(self) -> dict[str, Any]:
        """Flatten voice state back to the CaseNoteInput field shape.

        Used by session_complete event so Flutter can mirror the final form state.
        Values extracted from FieldValue dicts; None when not yet filled.
        """
        def _get(section: str, field: str) -> Any:
            sec = self.values.get(section) or {}
            fv = sec.get(field) if isinstance(sec, dict) else None
            if isinstance(fv, dict):
                return fv.get("value")
            return None

        return {
            "case_note_id": self.case_note_id,
            "client_id": self.client_id,
            "worker_id": self.worker_id,
            # shift
            "shift_date": _get("shift", "shift_date"),
            "shift_time": _get("shift", "shift_time"),
            "worker_position": _get("shift", "worker_position"),
            # summary
            "describe": _get("summary", "describe"),
            # activities
            "assisted": _get("activities", "assisted"),
            "practised_skill": _get("activities", "practised_skill"),
            "participants_level_of_independence": _get("activities", "participants_level_of_independence"),
            "observations": _get("activities", "observations"),
            # wellbeing
            "mood": _get("wellbeing", "mood"),
            "behavioural_events": _get("wellbeing", "behavioural_events"),
            "any_concerns": _get("wellbeing", "any_concerns"),
            # outcomes
            "what_went_well": _get("outcomes", "what_went_well"),
            "what_needs_further_support": _get("outcomes", "what_needs_further_support"),
            "participant_comments": _get("outcomes", "participant_comments"),
            # safety
            "medication_reminders_given": _get("safety", "medication_reminders_given"),
            "safety_hazards_observed": _get("safety", "safety_hazards_observed"),
            "any_injuries": _get("safety", "any_injuries"),
            "injury_description": _get("safety", "injury_description"),
            "uploaded_documents": _get("safety", "uploaded_documents"),
            # incidents
            "carer_feedback": _get("incidents", "carer_feedback"),
            "incident_occurred": _get("incidents", "incident_occurred"),
        }
