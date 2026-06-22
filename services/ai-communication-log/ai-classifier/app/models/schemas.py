from pydantic import BaseModel, Field
from typing import Literal, Optional
from datetime import datetime


# ── Enums ──────────────────────────────────────────────────────────────────────

Role = Literal["support_worker", "client"]

SentimentLabel = Literal[
    "positive_satisfied",
    "neutral",
    "frustrated_dissatisfied",
    "distressed_upset",
    "confused_uncertain",
    "engaged",
    "disengaged",
]

RiskLevel = Literal["low", "medium", "high", "critical"]
OutcomeStatus = Literal["resolved", "unresolved", "pending"]


# ── Request Models ─────────────────────────────────────────────────────────────

class Message(BaseModel):
    role: Role = Field(..., description="Who sent this message")
    text: str = Field(..., min_length=1, description="Message content")
    timestamp: datetime = Field(..., description="UTC timestamp of the message")


# ── Response Sub-models ────────────────────────────────────────────────────────

class SentimentResult(BaseModel):
    label: SentimentLabel = Field(..., description="Participant wellbeing/engagement category")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score 0.0–1.0")
    reason: str = Field(..., description="One sentence citing specific participant language or behaviour")


class RiskAssessment(BaseModel):
    level: RiskLevel = Field(..., description="Risk severity: low / medium / high / critical")
    indicators: list[str] = Field(default=[], description="Specific risk indicators detected")
    reason: str = Field(..., description="Risk assessment summary")


class BreakdownAssessment(BaseModel):
    detected: bool = Field(..., description="True if communication breakdown was detected")
    reasons: list[str] = Field(
        default=[],
        description="Breakdown criteria matched — empty when detected=false"
    )


# ── Sentiment Batch ────────────────────────────────────────────────────────────

class MessageAnalysis(BaseModel):
    """Full analysis for a single message in the batch — all fields match existing schema types."""
    role: Role
    text: str
    timestamp: datetime
    sentiment: SentimentResult
    risk: RiskAssessment
    breakdown: BreakdownAssessment
    outcome: OutcomeStatus
    recommended_action: Optional[str] = None


class SentimentBatchRequest(BaseModel):
    conversation_id: str = Field(..., description="Unique ID for this conversation thread")
    provider_id: str = Field(..., description="Service provider org ID — used for data isolation")
    messages: list[Message] = Field(
        ...,
        min_length=1,
        description="Ordered (oldest → newest) batch of messages to analyse",
    )
    metadata: Optional[dict] = Field(default=None, description="Optional extra context")


class TokenUsage(BaseModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int


class SentimentBatchResponse(BaseModel):
    conversation_id: str
    provider_id: str

    # Full analysis per message — one entry per input message, same order
    messages: list[MessageAnalysis]

    # Metadata
    messages_analysed: int
    period_start: datetime = Field(..., description="Timestamp of the earliest message in the batch")
    period_end: datetime = Field(..., description="Timestamp of the latest message in the batch")
    analysed_at: datetime = Field(default_factory=datetime.utcnow)
    token_usage: Optional[TokenUsage] = None


# ── Health Check ───────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    version: str
    model: str
