from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


# ── Verdict outcome labels ────────────────────────────────────────────────────

class VerdictOutcome(str, Enum):
    CLEAR = "CLEAR"
    NO_INCIDENT = "NO INCIDENT DETECTED"
    AUTHORISED_USE = "AUTHORISED USE — REVIEW RECOMMENDED"
    UNAUTHORISED = "UNAUTHORISED RESTRICTIVE PRACTICE DETECTED"


class PolicyViolationRisk(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"


class AuthorisationStatus(str, Enum):
    UNAUTHORISED = "Unauthorised Restrictive Practice"
    AUTHORISED_REVIEW = "Authorised Use (Review Required)"
    NO_INCIDENT = "No Incident Detected"


# ── BSP management ───────────────────────────────────────────────────────────

class BSPCreate(BaseModel):
    client_id: str = Field(..., description="Platform client/participant ID")
    practice_type: str = Field(
        ...,
        description=(
            "One of: Physical Restraint, Chemical Restraint, Mechanical Restraint, "
            "Seclusion, Environmental Restraint"
        ),
    )
    status: str = Field("Active", description="Active | Expired | Revoked")
    approved_dosage: str | None = Field(None, description="For chemical restraint — medication + dose")
    approved_conditions: str | None = Field(
        None, description="Conditions under which this practice is authorised"
    )
    authorised_by: str | None = Field(None, description="Name of authorising behaviour support practitioner")
    valid_from: datetime | None = Field(None, description="Start of authorisation window (null = unbounded)")
    valid_until: datetime | None = Field(None, description="Expiry of authorisation (null = no expiry)")


class BSPResponse(BaseModel):
    id: str
    client_id: str
    practice_type: str
    status: str
    approved_dosage: str | None
    approved_conditions: str | None
    authorised_by: str | None
    valid_from: datetime | None
    valid_until: datetime | None
    created_at: datetime


class BSPUpdateStatus(BaseModel):
    status: str = Field(..., description="Active | Expired | Revoked")


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


# ── Final pipeline output (internal — used by graph, DB audit, webhook) ───────

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


# ── API response models (human-readable, returned by POST /evaluate) ──────────

class _VerdictSection(BaseModel):
    outcome: VerdictOutcome
    risk_level: str = Field(description="Low | Medium | High | Critical | N/A")
    alert_required: bool
    action_required: str = Field(description="What must be done next, in plain English")


class _DetectedPracticeSection(BaseModel):
    category: str
    what_happened: str = Field(description="One-sentence description of the practice used")
    reasoning: str = Field(description="Evidence-based analysis citing the case note")


class _BehaviourSupportPlan(BaseModel):
    on_file: bool
    details: str


class _AuthorisationSection(BaseModel):
    status: str
    behaviour_support_plan: _BehaviourSupportPlan


class _ReportingSection(BaseModel):
    must_report: bool
    notify_within: str | None = Field(None, description="e.g. '5 business days' or '24 hours'")
    notify_authority: str = "NDIS Quality and Safeguards Commission"
    guidance: str | None = None


class _SubmissionSection(BaseModel):
    case_note_id: str
    client_id: str
    worker_id: str
    screening_result: str = Field(description="'Flagged for detailed review' or 'Passed initial screening'")
    screening_summary: str | None = None


class EvaluateResponse(BaseModel):
    """Human-readable API response returned by POST /v1/restrictive-practices/evaluate."""
    verdict: _VerdictSection
    detected_practice: _DetectedPracticeSection | None = Field(
        None, description="Present only when a restrictive practice was detected"
    )
    authorisation: _AuthorisationSection | None = Field(
        None, description="Present only when a practice was detected"
    )
    reporting_obligations: _ReportingSection
    submission: _SubmissionSection
    privacy: str
