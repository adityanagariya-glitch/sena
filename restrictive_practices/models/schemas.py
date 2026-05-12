from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator


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

    # Optional voice transcript — present only when voice capture was used
    transcript: str | None = None

    # Form header metadata
    shift_date: str | None = Field(None, description="e.g. '22 Nov 2025'")
    shift_time: str | None = Field(None, description="e.g. '5:00 PM - 1:00 AM'")
    worker_position: str | None = Field(None, description="e.g. 'Support Worker'")

    # Section 1 — Summary of Shift
    # Form sub-field: "Describe"
    describe: str | None = Field(
        None,
        description="What activities and community access opportunities did you and the participant engage in together?",
    )

    # Section 2 — Activities Completed & Skill-Building
    # Form sub-fields: Assisted | Practised skill | Participant's level of independence | Observations
    assisted: str | None = None
    practised_skill: str | None = None
    participants_level_of_independence: str | None = None
    observations: str | None = None

    # Section 3 — Well-being & Behaviour
    # Form sub-fields: Mood | Behavioural events | Any concerns (Yes/No)
    mood: str | None = None
    behavioural_events: str | None = None
    any_concerns: bool = False

    # Section 4 — Outcomes & Progress
    # Form sub-fields: What went well | What needs further support | Participant's comments
    what_went_well: str | None = None
    what_needs_further_support: str | None = None
    participant_comments: str | None = None

    # Section 5 — Safety / Health Monitoring
    # Form sub-fields: Medication reminders given | Safety hazards observed |
    #                  Any injuries | Text Box (injury description) | Image / Documents
    medication_reminders_given: bool = False
    safety_hazards_observed: bool = False
    any_injuries: bool = False
    injury_description: str | None = Field(None, description="Text Box — free-text injury description")
    uploaded_documents: list[str] | None = Field(
        None, description="Document IDs or URLs from the Image / Documents upload"
    )

    # Section 6 — Notes / Additional Comments
    # Form sub-fields: Carer feedback | Did Any Incident Occurred? (Yes/No)
    carer_feedback: str | None = None
    incident_occurred: bool = False

    @model_validator(mode="after")
    def _require_content(self) -> "CaseNoteInput":
        text_fields = [
            self.transcript, self.describe, self.behavioural_events,
            self.observations, self.carer_feedback, self.assisted, self.mood,
        ]
        if not any(text_fields):
            raise ValueError(
                "At least one text field must be provided "
                "(transcript, describe, behavioural_events, observations, "
                "carer_feedback, assisted, or mood)"
            )
        return self

    def to_text(self) -> str:
        """Flatten form fields to plain text for LLM consumption.

        Uses transcript directly if provided; otherwise builds a structured
        narrative from the form sections in the order they appear on screen.
        """
        if self.transcript:
            return self.transcript

        parts: list[str] = []

        if self.shift_date or self.shift_time:
            parts.append(f"Date/Time: {self.shift_date or ''} {self.shift_time or ''}".strip())
        if self.worker_position:
            parts.append(f"Worker Position: {self.worker_position}")

        # Section 1
        if self.describe:
            parts.append(f"Summary of Shift:\n{self.describe}")

        # Section 2
        activity_lines = []
        if self.assisted:
            activity_lines.append(f"Assisted: {self.assisted}")
        if self.practised_skill:
            activity_lines.append(f"Practised Skill: {self.practised_skill}")
        if self.participants_level_of_independence:
            activity_lines.append(f"Participant's Level of Independence: {self.participants_level_of_independence}")
        if self.observations:
            activity_lines.append(f"Observations: {self.observations}")
        if activity_lines:
            parts.append("Activities Completed & Skill-Building:\n" + "\n".join(activity_lines))

        # Section 3
        behaviour_lines = []
        if self.mood:
            behaviour_lines.append(f"Mood: {self.mood}")
        if self.behavioural_events:
            behaviour_lines.append(f"Behavioural Events: {self.behavioural_events}")
        if self.any_concerns:
            behaviour_lines.append("Any Concerns: Yes")
        if behaviour_lines:
            parts.append("Well-being & Behaviour:\n" + "\n".join(behaviour_lines))

        # Section 4
        outcome_lines = []
        if self.what_went_well:
            outcome_lines.append(f"What Went Well: {self.what_went_well}")
        if self.what_needs_further_support:
            outcome_lines.append(f"What Needs Further Support: {self.what_needs_further_support}")
        if self.participant_comments:
            outcome_lines.append(f"Participant's Comments: {self.participant_comments}")
        if outcome_lines:
            parts.append("Outcomes & Progress:\n" + "\n".join(outcome_lines))

        # Section 5
        safety_lines = [
            f"Medication Reminders Given: {'Yes' if self.medication_reminders_given else 'No'}",
            f"Safety Hazards Observed: {'Yes' if self.safety_hazards_observed else 'No'}",
            f"Any Injuries: {'Yes' if self.any_injuries else 'No'}",
        ]
        if self.any_injuries and self.injury_description:
            safety_lines.append(f"Injury Description: {self.injury_description}")
        parts.append("Safety / Health Monitoring:\n" + "\n".join(safety_lines))

        # Section 6
        notes_lines = []
        if self.carer_feedback:
            notes_lines.append(f"Carer Feedback: {self.carer_feedback}")
        notes_lines.append(f"Did Any Incident Occur: {'Yes' if self.incident_occurred else 'No'}")
        parts.append("Notes / Additional Comments:\n" + "\n".join(notes_lines))

        return "\n\n".join(parts)


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


# ── Case note drafting ────────────────────────────────────────────────────────

class DraftInput(BaseModel):
    """Input for POST /draft — voice transcript + shift metadata."""
    transcript: str = Field(..., description="Full voice transcript from the support worker's post-shift recording")
    worker_id: str
    client_id: str
    case_note_id: UUID = Field(default_factory=uuid4)
    shift_date: str | None = Field(None, description="e.g. '12 May 2025'; pass-through from caller")
    shift_time: str | None = Field(None, description="e.g. '9:00 AM - 1:00 PM'; pass-through from caller")
    worker_position: str | None = Field(None, description="e.g. 'Support Worker'")


class CaseDraftResponse(BaseModel):
    """Pre-filled case note form returned by POST /draft. All form fields are AI-extracted from the transcript.
    Worker reviews, edits, and approves before submission."""
    case_note_id: UUID
    client_id: str
    worker_id: str
    shift_date: str | None
    shift_time: str | None
    worker_position: str | None

    # Section 1 — Summary of Shift
    describe: str | None = None

    # Section 2 — Activities Completed & Skill-Building
    assisted: str | None = None
    practised_skill: str | None = None
    participants_level_of_independence: str | None = None
    observations: str | None = None

    # Section 3 — Well-being & Behaviour
    mood: str | None = None
    behavioural_events: str | None = None
    any_concerns: bool = False

    # Section 4 — Outcomes & Progress
    what_went_well: str | None = None
    what_needs_further_support: str | None = None
    participant_comments: str | None = None

    # Section 5 — Safety / Health Monitoring
    medication_reminders_given: bool = False
    safety_hazards_observed: bool = False
    any_injuries: bool = False
    injury_description: str | None = None

    # Section 6 — Notes / Additional Comments
    carer_feedback: str | None = None
    incident_occurred: bool = False

    # Draft metadata
    draft_note: str | None = Field(
        None,
        description="AI-generated note on extraction quality, gaps, or ambiguities the worker should review",
    )
