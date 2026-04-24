from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


# ── Shared ────────────────────────────────────────────────────────────────────

class AuthContext(BaseModel):
    """Extracted from dev-header or JWT middleware."""
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    roles: list[str] = Field(default_factory=list)


# ── Case note (from other engineer's API / stub) ──────────────────────────────

class CaseNoteDTO(BaseModel):
    """Shape returned by the other engineer's GET /case-notes API."""
    note_id: str
    date: str
    staff_id: str
    client_id: str
    transcript: str
    drafted_note: str


# ── POST /v1/case-review/context ──────────────────────────────────────────────

class ContextRequest(BaseModel):
    staff_id: uuid.UUID = uuid.UUID("cccccccc-0000-0000-0000-000000000003")
    client_id: uuid.UUID = uuid.UUID("dddddddd-0000-0000-0000-000000000004")
    limit: int = Field(default=10, ge=1, le=50)


class ContextResponse(BaseModel):
    summary_text: str
    metadata: dict
    notes_included: int
    rolling_summary_id: uuid.UUID


# ── POST /v1/case-review/classify ─────────────────────────────────────────────

class ClassifyRequest(BaseModel):
    staff_id: uuid.UUID
    client_id: uuid.UUID
    raw_paragraph: str
    drafted_case_note_id: str | None = None
    review_session_id: uuid.UUID | None = Field(default=None, description="Pass to re-classify an existing session. Omit to create a new one.")


class ReaskPrompt(BaseModel):
    field_id: str
    label: str
    reason: str
    suggested_question: str


class ClassifyResponse(BaseModel):
    review_session_id: uuid.UUID
    classified_fields: dict
    missing_fields: list[dict]
    reask_prompts: list[ReaskPrompt]
    status: str


# ── POST /v1/case-review/review ───────────────────────────────────────────────

class ReviewRequest(BaseModel):
    review_session_id: uuid.UUID


class FlagItem(BaseModel):
    category: str
    description: str
    severity: str  # low | medium | high | critical
    ndis_reference: str | None = None


class ReviewResponse(BaseModel):
    review_session_id: uuid.UUID
    risks: list[FlagItem]
    restrictive_practices: list[FlagItem]
    anomalies: list[FlagItem]
    improvements: list[FlagItem]
    status: str


# ── POST /v1/case-review/incident/detect ──────────────────────────────────────

class IncidentDetectRequest(BaseModel):
    review_session_id: uuid.UUID


class IncidentDetectResponse(BaseModel):
    review_session_id: uuid.UUID
    incident_detected: bool
    incident_draft_id: uuid.UUID | None = None
    markers: list[str]  # extracted evidence phrases


# ── POST /v1/case-review/incident/draft ───────────────────────────────────────

class IncidentDraftRequest(BaseModel):
    review_session_id: uuid.UUID


class IncidentDraftResponse(BaseModel):
    incident_draft_id: uuid.UUID
    draft_fields: dict
    autofill_source: dict
    status: str


# ── PATCH /v1/case-review/incident/{id}/confirm ───────────────────────────────

class IncidentConfirmResponse(BaseModel):
    incident_draft_id: uuid.UUID
    status: str
    staff_confirmed: bool


# ── POST /v1/case-review/submit ───────────────────────────────────────────────

class SubmitRequest(BaseModel):
    review_session_id: uuid.UUID
    actor_user_id: uuid.UUID


class SubmitResponse(BaseModel):
    review_session_id: uuid.UUID
    status: str
    submitted_at: datetime


# ── Health ────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    service: str = "case-review"
    version: str
