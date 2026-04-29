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


# ── Evaluator ─────────────────────────────────────────────────────────────────

class EvaluatorOutput(BaseModel):
    incident_detected: bool
    practice_category: str
    action_summary: str
    policy_violation_risk: PolicyViolationRisk
    reasoning: str


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
