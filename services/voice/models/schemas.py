from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field, field_validator


class TokenUsage(BaseModel):
    """LLM token usage metrics including cache metrics for Claude."""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


class StartSessionRequest(BaseModel):
    objective: Literal["CASE_NOTE"]
    participant_id: UUID
    staff_id: UUID
    shift_id: UUID
    language: str = "en-AU"
    metadata: dict = Field(default_factory=dict)


class StartSessionResponse(BaseModel):
    session_id: UUID
    status: str
    objective: str
    lock_acquired: bool
    livekit: dict
    token_usage: TokenUsage = Field(default_factory=TokenUsage)


class TurnRequest(BaseModel):
    session_id: UUID
    transcript: str = Field(min_length=1)
    transcript_confidence: float = Field(ge=0.0, le=1.0)
    audio_duration_ms: int = Field(gt=0)
    sequence_number: int = Field(gt=0)
    timestamp: datetime


class TurnResponse(BaseModel):
    session_id: UUID
    sequence_number: int
    agent_reply: str
    draft_preview: str
    completeness_score: float
    missing_topics: list[str]
    model: str
    latency_ms: int
    token_usage: TokenUsage = Field(default_factory=TokenUsage)


class EndSessionRequest(BaseModel):
    session_id: UUID
    ended_at: datetime
    client_timezone: str = "Australia/Sydney"


class EndSessionResponse(BaseModel):
    session_id: UUID
    draft_id: UUID
    approval_item_id: UUID
    event_id: UUID
    status: str
    case_note: dict
    token_usage: TokenUsage = Field(default_factory=TokenUsage)


class ApprovalDecisionRequest(BaseModel):
    approval_item_id: UUID
    decision: Literal["APPROVED", "REJECTED"]
    reviewer_id: UUID
    review_notes: str = ""

    @field_validator("review_notes")
    @classmethod
    def reject_requires_reason(cls, value: str, info):
        decision = info.data.get("decision")
        if decision == "REJECTED" and not value.strip():
            raise ValueError("review_notes is required when decision is REJECTED")
        return value


class ApprovalDecisionResponse(BaseModel):
    approval_item_id: UUID
    decision: str
    status: str
    shared_case_note_id: UUID | None = None
    delivered_at: datetime | None = None
    token_usage: TokenUsage = Field(default_factory=TokenUsage)


class SessionStatusResponse(BaseModel):
    session_id: UUID
    status: str
    objective: str
    turn_count: int
    completeness_score: float
    missing_topics: list[str]
    token_usage: TokenUsage = Field(default_factory=TokenUsage)


class StartPersonalDetailsRequest(BaseModel):
    participant_id: UUID
    staff_id: UUID
    shift_id: UUID
    language: str = "en-AU"


class StartPersonalDetailsResponse(BaseModel):
    session_id: UUID
    status: str
    objective: str
    lock_acquired: bool
    livekit: dict
    token_usage: TokenUsage = Field(default_factory=TokenUsage)


class PersonalDetailsTurnRequest(BaseModel):
    session_id: UUID
    transcript: str = Field(min_length=1)
    transcript_confidence: float = Field(ge=0.0, le=1.0)
    audio_duration_ms: int = Field(gt=0)
    sequence_number: int = Field(gt=0)
    timestamp: datetime


class PersonalDetailsTurnResponse(BaseModel):
    session_id: UUID
    sequence_number: int
    agent_reply: str
    fields: dict
    missing_fields: list[str]
    completeness_score: float
    model: str
    latency_ms: int
    token_usage: TokenUsage = Field(default_factory=TokenUsage)


class EndPersonalDetailsRequest(BaseModel):
    session_id: UUID
    ended_at: datetime


class EndPersonalDetailsResponse(BaseModel):
    session_id: UUID
    draft_id: UUID
    fields: dict
    completeness_score: float
    missing_fields: list[str]
    status: str
    token_usage: TokenUsage = Field(default_factory=TokenUsage)


class ErrorResponse(BaseModel):
    error: str
    details: list[str] | None = None
    retry_after: int | None = None
    fallback_used: bool | None = None
    retryable: bool | None = None
