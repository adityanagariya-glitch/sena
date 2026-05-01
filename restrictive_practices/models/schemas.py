from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class PolicyViolationRisk(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"


class AuthorisationStatus(str, Enum):
    UNAUTHORISED = "Unauthorised Restrictive Practice"
    AUTHORISED_REVIEW = "Authorised Use (Review Required)"
    NO_INCIDENT = "No Incident Detected"


# ── Pipeline input ────────────────────────────────────────────────────────────

class CaseNoteInput(BaseModel):
    case_note_id: UUID
    client_id: str
    worker_id: str
    transcript: str = Field(..., min_length=10)


# ── Triage ────────────────────────────────────────────────────────────────────

class TriageResult(BaseModel):
    flagged: bool
    action_summary: str | None = None  # 1-sentence extraction when flagged=True


# ── RAG ──────────────────────────────────────────────────────────────────────

class PolicyChunk(BaseModel):
    chunk_id: str
    text: str
    category: str
    document_source: str
    risk_level: str
    document_type: str = "Regulatory"


# ── Evaluator ─────────────────────────────────────────────────────────────────

class EvaluatorOutput(BaseModel):
    incident_detected: bool
    practice_category: str
    action_summary: str
    policy_violation_risk: PolicyViolationRisk
    reasoning: str
    reporting_required: bool = False
    notification_timeframe: str | None = None  # "5 business days" | "24 hours" | None


# ── Cross-check ───────────────────────────────────────────────────────────────

class CrossCheckResult(BaseModel):
    authorisation_status: AuthorisationStatus
    bsp_id: str | None = None
    conditions_met: bool = False
    notes: str = ""


# ── Final pipeline output ─────────────────────────────────────────────────────

class PipelineResult(BaseModel):
    case_note_id: UUID
    client_id: str
    triage: TriageResult
    evaluator: EvaluatorOutput | None = None
    cross_check: CrossCheckResult | None = None
    alert_required: bool = False
    privacy_notice: str = (
        "Processed under APP 3 (Privacy Act 1988) as sensitive health information. "
        "Used solely for NDIS compliance monitoring. No personal data retained beyond this response."
    )
