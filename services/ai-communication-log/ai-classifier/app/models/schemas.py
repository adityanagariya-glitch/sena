from pydantic import BaseModel, Field
from typing import Literal, Optional
from datetime import datetime


# ── Enums ──────────────────────────────────────────────────────────────────────

Role = Literal["support_worker", "client"]
Label = Literal["emergency", "inappropriate", "normal"]

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


class ClassificationRequest(BaseModel):
    conversation_id: str = Field(..., description="Unique ID for this conversation thread")
    provider_id: str = Field(..., description="Service provider org ID — used for data isolation")
    current_message: Message = Field(..., description="The message that triggered this classification call")
    history: list[Message] = Field(
        default=[],
        description="Last N messages before the current one (ordered oldest → newest)"
    )
    metadata: Optional[dict] = Field(
        default=None,
        description="Optional extra context: shift_id, client_id, worker_id etc."
    )

    class Config:
        json_schema_extra = {
            "example": {
                "conversation_id": "conv_20250601_001",
                "provider_id": "org_abc_123",
                "current_message": {
                    "role": "support_worker",
                    "text": "I don't want to deal with you anymore, just do what I say.",
                    "timestamp": "2025-06-01T10:05:00Z"
                },
                "history": [
                    {
                        "role": "client",
                        "text": "I need help getting to the bathroom.",
                        "timestamp": "2025-06-01T10:03:00Z"
                    },
                    {
                        "role": "support_worker",
                        "text": "Wait, I'm busy.",
                        "timestamp": "2025-06-01T10:04:00Z"
                    }
                ],
                "metadata": {
                    "shift_id": "shift_789",
                    "client_id": "client_456",
                    "worker_id": "worker_321"
                }
            }
        }


# ── Response Sub-models ────────────────────────────────────────────────────────

class ClassificationResult(BaseModel):
    label: Label = Field(..., description="NDIS compliance label")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score 0.0–1.0")
    reason: str = Field(..., description="Short explanation citing specific message content")


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


# ── Main Response ──────────────────────────────────────────────────────────────

class ClassificationResponse(BaseModel):
    conversation_id: str
    provider_id: str

    # NDIS compliance labels (emergency / inappropriate / normal)
    is_uncertain: bool = Field(
        ...,
        description="True if all classification confidence scores fall below the configured threshold"
    )
    classifications: list[ClassificationResult] = Field(
        ...,
        description="Multi-label NDIS compliance result — emergency, inappropriate, or normal"
    )

    # Wellbeing & communication analysis (SCOPE items 1–3)
    sentiment: SentimentResult = Field(
        ...,
        description="Participant wellbeing and engagement sentiment"
    )
    risk: RiskAssessment = Field(
        ...,
        description="Risk level assessment with NDIS safeguarding indicators"
    )
    breakdown: BreakdownAssessment = Field(
        ...,
        description="Communication breakdown detection"
    )
    outcome: OutcomeStatus = Field(
        ...,
        description="Conversation outcome: resolved / unresolved / pending"
    )
    recommended_action: Optional[str] = Field(
        default=None,
        description="Actionable instruction for coordinator — set for high/critical risk or breakdown"
    )

    # Metadata
    messages_analysed: int = Field(..., description="Total messages used in analysis (current + history)")
    analysed_at: datetime = Field(default_factory=datetime.utcnow)


# ── Health Check ───────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    version: str
    model: str
