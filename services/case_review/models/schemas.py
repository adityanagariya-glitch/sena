from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator


# ── Shared ────────────────────────────────────────────────────────────────────

class AuthContext(BaseModel):
    """Extracted from dev-header or JWT middleware."""
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    roles: list[str] = Field(default_factory=list)


class TokenUsage(BaseModel):
    """LLM token usage metrics (input, output, total)."""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


# ── Case note (from other engineer's API / stub) ──────────────────────────────

class CaseNoteDTO(BaseModel):
    """
    Normalised case note consumed by the summarizer.

    Sourced either from fixtures (stub) or the SENA org backend
    (GET /organization/case-note/{id}). The org backend has no raw voice
    transcript — only the structured/drafted note — so `transcript` is
    optional and `drafted_note` carries the composed note body.
    """
    note_id: str
    date: str
    staff_id: str
    client_id: str
    transcript: str = ""
    drafted_note: str = ""


# ── POST /v1/case-review/context ──────────────────────────────────────────────

class ContextRequest(BaseModel):
    staff_id: uuid.UUID = Field(
        default=uuid.UUID("cccccccc-0000-0000-0000-000000000003"),
        description="Staff/worker UUID — maps to the org backend's memberId / organizationMemberId.",
    )
    client_id: uuid.UUID = Field(
        default=uuid.UUID("dddddddd-0000-0000-0000-000000000004"),
        description="Client/participant UUID — maps to the org backend's clientId.",
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Max case notes to fetch (newest first). Hard-capped server-side by case_note_fetch_limit (default 10).",
    )


class ContextResponse(BaseModel):
    summary_text: str
    metadata: dict
    notes_included: int
    rolling_summary_id: uuid.UUID
    token_usage: TokenUsage = Field(default_factory=TokenUsage)


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
    token_usage: TokenUsage = Field(default_factory=TokenUsage)


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


# ── RP Pipeline schemas (ported from restrictive_practices/models/schemas.py) ─

class VerdictOutcome(str, Enum):
    CLEAR = "CLEAR"
    NO_INCIDENT = "NO INCIDENT DETECTED"
    AUTHORISED_USE = "AUTHORISED USE — REVIEW RECOMMENDED"
    POSSIBLE = "POSSIBLE RESTRICTIVE PRACTICE — ADMINISTRATIVE REVIEW"
    ADMINISTRATIVE_REVIEW = "ADMINISTRATIVE REVIEW REQUIRED — BSP reference but no DB match"
    UNAUTHORISED = "UNAUTHORISED RESTRICTIVE PRACTICE DETECTED"


class PolicyViolationRisk(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"


class ConfidenceLevel(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"


class AuthorisationStatus(str, Enum):
    UNAUTHORISED = "Unauthorised Restrictive Practice"
    AUTHORISED_REVIEW = "Authorised Use (Review Required)"
    NO_INCIDENT = "No Incident Detected"


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


class CaseNoteInput(BaseModel):
    case_note_id: UUID
    client_id: str
    worker_id: str

    transcript: str | None = None

    shift_date: str | None = Field(None, description="e.g. '22 Nov 2025'")
    shift_time: str | None = Field(None, description="e.g. '5:00 PM - 1:00 AM'")
    worker_position: str | None = Field(None, description="e.g. 'Support Worker'")

    describe: str | None = Field(
        None,
        description="What activities and community access opportunities did you and the participant engage in together?",
    )

    assisted: str | None = None
    practised_skill: str | None = None
    participants_level_of_independence: str | None = None
    observations: str | None = None

    mood: str | None = None
    behavioural_events: str | None = None
    any_concerns: bool = False

    what_went_well: str | None = None
    what_needs_further_support: str | None = None
    participant_comments: str | None = None

    medication_reminders_given: bool = False
    safety_hazards_observed: bool = False
    any_injuries: bool = False
    injury_description: str | None = Field(None, description="Text Box — free-text injury description")
    uploaded_documents: list[str] | None = Field(
        None, description="Document IDs or URLs from the Image / Documents upload"
    )

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
        if self.transcript:
            return self.transcript

        parts: list[str] = []

        if self.shift_date or self.shift_time:
            parts.append(f"Date/Time: {self.shift_date or ''} {self.shift_time or ''}".strip())
        if self.worker_position:
            parts.append(f"Worker Position: {self.worker_position}")

        if self.describe:
            parts.append(f"Summary of Shift:\n{self.describe}")

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

        behaviour_lines = []
        if self.mood:
            behaviour_lines.append(f"Mood: {self.mood}")
        if self.behavioural_events:
            behaviour_lines.append(f"Behavioural Events: {self.behavioural_events}")
        if self.any_concerns:
            behaviour_lines.append("Any Concerns: Yes")
        if behaviour_lines:
            parts.append("Well-being & Behaviour:\n" + "\n".join(behaviour_lines))

        outcome_lines = []
        if self.what_went_well:
            outcome_lines.append(f"What Went Well: {self.what_went_well}")
        if self.what_needs_further_support:
            outcome_lines.append(f"What Needs Further Support: {self.what_needs_further_support}")
        if self.participant_comments:
            outcome_lines.append(f"Participant's Comments: {self.participant_comments}")
        if outcome_lines:
            parts.append("Outcomes & Progress:\n" + "\n".join(outcome_lines))

        safety_lines = [
            f"Medication Reminders Given: {'Yes' if self.medication_reminders_given else 'No'}",
            f"Safety Hazards Observed: {'Yes' if self.safety_hazards_observed else 'No'}",
            f"Any Injuries: {'Yes' if self.any_injuries else 'No'}",
        ]
        if self.any_injuries and self.injury_description:
            safety_lines.append(f"Injury Description: {self.injury_description}")
        parts.append("Safety / Health Monitoring:\n" + "\n".join(safety_lines))

        notes_lines = []
        if self.carer_feedback:
            notes_lines.append(f"Carer Feedback: {self.carer_feedback}")
        notes_lines.append(f"Did Any Incident Occur: {'Yes' if self.incident_occurred else 'No'}")
        parts.append("Notes / Additional Comments:\n" + "\n".join(notes_lines))

        return "\n\n".join(parts)


class TriageResult(BaseModel):
    flagged: bool
    action_summary: str | None = None
    triage_confidence: float = 0.5  # 0.0–1.0; drives Haiku vs Sonnet routing


class PolicyChunk(BaseModel):
    chunk_id: str
    text: str
    category: str
    document_source: str
    risk_level: str
    document_type: str = "Regulatory"


class EvaluatorOutput(BaseModel):
    incident_detected: bool
    practice_category: str
    action_summary: str
    policy_violation_risk: PolicyViolationRisk
    confidence: ConfidenceLevel = ConfidenceLevel.HIGH
    reasoning: str
    trigger_phrases: list[str] = []
    suppression_factors: list[str] = []
    bsp_mentioned_in_note: bool = False
    bsp_mention_excerpt: str | None = None
    reporting_required: bool = False
    notification_timeframe: str | None = None


class CrossCheckResult(BaseModel):
    authorisation_status: AuthorisationStatus
    bsp_id: str | None = None
    conditions_met: bool = False
    notes: str = ""


class SummaryOutput(BaseModel):
    ai_confidence: float = Field(0.0, ge=0.0, le=1.0)
    progress_identified: list[str] = []
    potential_risks: list[str] = []
    patterns_detected: list[str] = []
    flagged_highlights: list[str] = []
    note_quality_score: float = Field(0.0, ge=0.0, le=1.0)
    note_quality_label: str = "Average"
    quality_gaps: list[str] = []


class IncidentDraftOutput(BaseModel):
    incident_type: str
    date_of_incident: str | None = None
    time_of_incident: str | None = None
    location: str | None = None
    staff_involved: list[str] = []
    incident_description: str
    immediate_actions_taken: list[str] = []
    restrictive_practice_used: bool = False
    restrictive_practice_category: str | None = None
    risk_assessment: str = "Immediate risk: Low"
    contributing_factors: list[str] = []
    follow_up_actions: list[str] = []
    compliance_checks: list[dict] = []
    reportable: bool = False
    notification_timeframe: str | None = None
    notification_authority: str = "NDIS Quality and Safeguards Commission"
    severity: str = "Low"
    incident_categories: list[str] = []
    ongoing_risk_present: bool = False
    participant_currently_safe: bool = True
    staff_currently_safe: bool = True
    emergency_services_required: bool = False


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
    summary: SummaryOutput | None = None
    incident_draft: IncidentDraftOutput | None = None
    token_usage: TokenUsage = Field(default_factory=TokenUsage)


class _VerdictSection(BaseModel):
    outcome: VerdictOutcome
    risk_level: str = Field(description="Low | Medium | High | Critical | N/A")
    alert_required: bool
    action_required: str = Field(description="What must be done next, in plain English")
    next_steps: list[str] = Field(default=[], description="Ordered checklist of recommended investigation/response steps")


class _DetectedPracticeSection(BaseModel):
    category: str
    what_happened: str = Field(description="One-sentence description of the practice used")
    reasoning: str = Field(description="Evidence-based analysis citing the case note")
    trigger_phrases: list[str] = Field(default=[], description="Exact phrases from the note that indicate restrictive practice")
    suppression_factors: list[str] = Field(default=[], description="Phrases that argue against or mitigate escalation")


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


class _SummarySection(BaseModel):
    ai_confidence: float = Field(description="AI confidence score 0.0–1.0")
    confidence_label: str = Field(description="e.g. 'High', 'Medium', 'Low'")
    progress_identified: list[str] = Field(default=[], description="Positive observations from the shift")
    potential_risks: list[str] = Field(default=[], description="Risk indicators noted")
    patterns_detected: list[str] = Field(default=[], description="Behavioural or situational patterns")
    flagged_highlights: list[str] = Field(
        default=[], description="Verbatim excerpts from the case note that warranted attention"
    )
    note_quality_score: float = Field(0.0, description="Heuristic quality score 0.0–1.0")
    note_quality_label: str = Field("Average", description="'Premium' | 'Average' | 'Poor'")
    quality_gaps: list[str] = Field(default=[], description="Actionable suggestions for improving the note")


class _IncidentReportSection(BaseModel):
    incident_type: str
    date_of_incident: str | None = None
    time_of_incident: str | None = None
    location: str | None = None
    staff_involved: list[str] = []
    incident_description: str
    immediate_actions_taken: list[str] = []
    restrictive_practice_used: bool = False
    restrictive_practice_category: str | None = None
    risk_assessment: str
    contributing_factors: list[str] = []
    follow_up_actions: list[str] = []
    compliance_checks: list[dict] = Field(default=[], description="[{label: str, passed: bool}]")
    reportable: bool
    notification_timeframe: str | None = None
    notification_authority: str = "NDIS Quality and Safeguards Commission"
    severity: str = "Low"
    incident_categories: list[str] = []
    ongoing_risk_present: bool = False
    participant_currently_safe: bool = True
    staff_currently_safe: bool = True
    emergency_services_required: bool = False


class EvaluateResponse(BaseModel):
    verdict: _VerdictSection
    detected_practice: _DetectedPracticeSection | None = Field(
        None, description="Present only when a restrictive practice was detected"
    )
    authorisation: _AuthorisationSection | None = Field(
        None, description="Present only when a practice was detected"
    )
    reporting_obligations: _ReportingSection
    submission: _SubmissionSection
    summary: _SummarySection
    incident_report: _IncidentReportSection | None = Field(
        None,
        description=(
            "Present when incident_occurred=True or an UNAUTHORISED restrictive practice was detected"
        ),
    )
    privacy: str
    token_usage: TokenUsage = Field(default_factory=TokenUsage)


class DraftInput(BaseModel):
    transcript: str = Field(..., description="Full voice transcript from the support worker's post-shift recording")
    worker_id: str
    client_id: str
    case_note_id: UUID = Field(default_factory=uuid4)
    shift_date: str | None = Field(None, description="e.g. '12 May 2025'; pass-through from caller")
    shift_time: str | None = Field(None, description="e.g. '9:00 AM - 1:00 PM'; pass-through from caller")
    worker_position: str | None = Field(None, description="e.g. 'Support Worker'")


class CaseDraftResponse(BaseModel):
    case_note_id: UUID
    client_id: str
    worker_id: str
    shift_date: str | None
    shift_time: str | None
    worker_position: str | None

    describe: str | None = None
    assisted: str | None = None
    practised_skill: str | None = None
    participants_level_of_independence: str | None = None
    observations: str | None = None

    mood: str | None = None
    behavioural_events: str | None = None
    any_concerns: bool = False

    what_went_well: str | None = None
    what_needs_further_support: str | None = None
    participant_comments: str | None = None

    medication_reminders_given: bool = False
    safety_hazards_observed: bool = False
    any_injuries: bool = False
    injury_description: str | None = None

    carer_feedback: str | None = None
    incident_occurred: bool = False

    transcript: str | None = None
    uploaded_documents: list[str] | None = None

    draft_note: str | None = Field(
        None,
        description="AI-generated note on extraction quality, gaps, or ambiguities the worker should review",
    )

    note_quality_score: float = Field(0.0, ge=0.0, le=1.0)
    note_quality_label: str = "Average"
    quality_gaps: list[str] = []

    token_usage: TokenUsage = Field(default_factory=TokenUsage)


# ── POST /v1/restrictive-practices/incidents/analyze (Unified 3-view Analysis) ─
#
# One call → the three mobile screens (AI Summary / Risk Summary / Incident Draft).
# Built by reusing the SAME pipeline + _build_response() as /evaluate, then
# regrouping. Reuses the tested section schemas:
#   * AI Summary screen     → _SummarySection         (always present)
#   * Incident Draft screen → _IncidentReportSection  (present only when an incident is drafted)
# Only the Risk Summary screen needs a new shape (derived from verdict + detected practice).


class RiskSummaryView(BaseModel):
    """Risk Summary screen — derived from the evaluator verdict + detected practice.

    Present only when the note was flagged by triage (i.e. an evaluator verdict
    exists). For a clean note this is null — there is no risk to summarise.
    """
    risk_category: str = Field(description="Practice category, or 'No Restrictive Practice Detected'")
    why_flagged: list[str] = Field(default=[], description="Trigger phrases + reasoning behind the flag")
    current_risk_level: str = Field(description="Low | Medium | High | Critical | N/A")
    suggested_attention: list[str] = Field(default=[], description="Recommended next steps (from the verdict)")


class UnifiedIncidentResponse(BaseModel):
    """Single response feeding all three mobile screens.

    Field availability mirrors the pipeline:
      * ``verdict`` + ``ai_summary`` — always present
      * ``risk_summary``            — null unless triage flagged the note
      * ``incident_draft``          — null unless an incident report was generated
    """
    case_note_id: UUID
    client_id: str
    shift_id: str | None = None
    incident_detected: bool = Field(description="True when the evaluator detected a restrictive-practice incident")

    verdict: _VerdictSection
    ai_summary: _SummarySection
    risk_summary: RiskSummaryView | None = None
    incident_draft: _IncidentReportSection | None = None

    token_usage: TokenUsage = Field(default_factory=TokenUsage)


class ComplianceNote(BaseModel):
    """One AI-Check row in the Incident Report compliance panel."""
    label: str = Field(description="The compliance statement checked")
    passed: bool = Field(description="True when the note satisfies this check")
    engine: str = Field(description="Which engine produced it: 'AI' | 'AI+RAG' | 'Python'")


class ShiftAISummary(BaseModel):
    """Section 1 — AI Summary / Overall Progress Snapshot."""
    reviewed_period: str | None = Field(None, description="shift date range (frontend fills if absent)")
    ai_confidence: float = Field(ge=0.0, le=1.0, description="random 0.80–0.95")
    confidence_label: str = Field(description="High | Medium | Low, from ai_confidence")
    progress_rating: str = Field(description=" On Track | Monitoring | Needs Attention")
    progress_identified: list[str] = Field(default=[], description="AI — positive observations")
    goal_progress: list[str] = Field(default=[], description="AI — progress toward NDIS goals")
    potential_risks: list[str] = Field(default=[], description="AI+RAG — risks vs NDIS policy")
    patterns_detected: list[str] = Field(default=[], description="AI — behavioural patterns")
    flagged_highlights: list[str] = Field(default=[], description="AI — verbatim excerpts")
    restrictive_practice_used: bool = Field(description="AI+RAG — evaluator + NDIS taxonomy")
    note_quality_score: float = Field(ge=0.0, le=1.0, description="heuristic quality score")
    note_quality_label: str = Field(description="Premium | Average | Poor")


class ShiftRiskSummary(BaseModel):
    """Section 2 — Risk Summary. Null when triage did not flag the note."""
    risk_category: str = Field(description="AI+RAG — practice category vs NDIS taxonomy")
    why_flagged: list[str] = Field(default=[], description="AI — trigger phrases")
    current_risk_level: str = Field(description="AI+RAG — Low | Medium | High | Critical")
    suggested_attention: list[str] = Field(default=[], description=" hybrid — rule base + AI action")


class ShiftIncidentReport(BaseModel):
    """Section 3 — Incident Report (AI-fillable fields only).

    Null unless an incident is detected. Human-only fields (date/time, location,
    individuals, witnesses, reported-to, additional notes) are excluded by design.
    """
    participant_name: str | None = Field(None, description="frontend maps from clientId")
    support_worker_name: str | None = Field(None, description="frontend maps from worker id")
    incident_type: str = Field(description="🤖 AI — classified incident type")
    incident_description: str = Field(description="🤖 AI — generated narrative")
    injuries_or_damages: list[str] = Field(default=[], description="🤖+🐍 — form injury detail + AI")
    immediate_actions_taken: list[str] = Field(default=[], description="🤖 AI")
    contributing_factors: list[str] = Field(default=[], description="🤖 AI")
    follow_up_required: list[str] = Field(default=[], description="🤖 AI")
    restrictive_practice_used: bool = Field(default=False, description="🤖+📚 AI+RAG")
    restrictive_practice_category: str | None = Field(None, description="🤖+📚 AI+RAG")
    risk_assessment: str = Field(default="Immediate risk: Low", description="🤖 AI")
    compliance_notes: list[ComplianceNote] = Field(default=[], description="AI + AI+RAG + Python checks")


class ShiftAnalysisResponse(BaseModel):
    """Single response feeding the AI Summary, Risk Summary, and Incident Report screens."""
    client_id: str
    shift_id: str
    incident_detected: bool = Field(description="True when an incident was detected or declared on the form")
    ai_summary: ShiftAISummary
    risk_summary: ShiftRiskSummary | None = None
    incident_report: ShiftIncidentReport | None = None
    token_usage: TokenUsage = Field(default_factory=TokenUsage)


# ── Unified analysis INPUT — SENA case note form (+ optional voice transcript) ─
#
# The mobile app feeds the structured shift case-note form, optionally with the
# raw voice dictation. We map it onto the pipeline's CaseNoteInput so the SAME
# RAG (pgvector NDIS policies) + Bedrock Claude evaluator generate the 3 views.
#
# Field names are camelCase to match the platform's case-note form payload.


class _ReportMedia(BaseModel):
    id: str | None = None
    fileName: str
    fileSize: int | None = None
    url: str


class _ActivitiesAndSkill(BaseModel):
    assisted: str | None = None
    practisedSkill: str | None = None
    participantsLevelOfIndependence: str | None = None
    observation: str | None = None


class _WellbeingAndBehaviour(BaseModel):
    mood: str | None = None
    behaviouralEvents: str | None = None
    anyConcerns: bool = False


class _OutcomesAndProgress(BaseModel):
    whatWentWell: str | None = None
    furtherSupport: str | None = None
    participantsComments: str | None = None


class _SafetyAndHealth(BaseModel):
    medicationReminderGiven: bool = False
    safetyHazardObserved: bool = False
    anyInjuries: bool = False
    injuryDetails: str | None = None
    reportMedia: list[_ReportMedia] = Field(default_factory=list)


class CaseNoteForm(BaseModel):
    """The SENA shift case-note form (camelCase, mirrors the platform payload)."""
    clientId: str
    shiftId: str
    summaryOfShift: str
    activitiesAndSkill: _ActivitiesAndSkill = Field(default_factory=_ActivitiesAndSkill)
    wellbeingAndBehaviour: _WellbeingAndBehaviour = Field(default_factory=_WellbeingAndBehaviour)
    outcomesAndProgress: _OutcomesAndProgress = Field(default_factory=_OutcomesAndProgress)
    safetyAndHealth: _SafetyAndHealth = Field(default_factory=_SafetyAndHealth)
    careFeedback: str | None = None
    anyIncident: bool = False
    handoverNote: str | None = None
    reviewNotes: str | None = None


class UnifiedIncidentRequest(BaseModel):
    """Request for POST /incidents/analyze — structured form + optional voice transcript."""
    case_note_form: CaseNoteForm
    voice_transcript: str | None = Field(
        None,
        description="Raw voice dictation. Merged with the structured form so the LLM sees both.",
    )

    def to_case_note_input(self, worker_id: str) -> "CaseNoteInput":
        """Map the form (+ voice transcript) onto the pipeline's CaseNoteInput.

        The structured fields are set individually (so the graph can read
        ``incident_occurred`` / ``any_injuries`` directly), then the composed
        narrative + handover/review notes + voice transcript are folded into
        ``transcript`` so ``to_text()`` surfaces everything to the LLM.
        """
        f = self.case_note_form
        a, w, o, s = (
            f.activitiesAndSkill,
            f.wellbeingAndBehaviour,
            f.outcomesAndProgress,
            f.safetyAndHealth,
        )
        media_refs = [m.url or m.fileName for m in s.reportMedia] or None

        cni = CaseNoteInput(
            case_note_id=uuid4(),
            client_id=f.clientId,
            worker_id=worker_id,
            transcript=None,  # compose from structured fields first
            describe=f.summaryOfShift,
            assisted=a.assisted,
            practised_skill=a.practisedSkill,
            participants_level_of_independence=a.participantsLevelOfIndependence,
            observations=a.observation,
            mood=w.mood,
            behavioural_events=w.behaviouralEvents,
            any_concerns=w.anyConcerns,
            what_went_well=o.whatWentWell,
            what_needs_further_support=o.furtherSupport,
            participant_comments=o.participantsComments,
            medication_reminders_given=s.medicationReminderGiven,
            safety_hazards_observed=s.safetyHazardObserved,
            any_injuries=s.anyInjuries,
            injury_description=s.injuryDetails,
            uploaded_documents=media_refs,
            carer_feedback=f.careFeedback,
            incident_occurred=f.anyIncident,
        )

        parts = [cni.to_text()]
        if f.handoverNote:
            parts.append(f"Handover Note:\n{f.handoverNote}")
        if f.reviewNotes:
            parts.append(f"Review Notes:\n{f.reviewNotes}")
        if self.voice_transcript:
            parts.append(f"Raw Voice Transcript:\n{self.voice_transcript}")
        combined = "\n\n".join(p for p in parts if p)

        # Re-emit with transcript=combined: to_text() now returns the full merged
        # text, while the boolean flags above stay intact for the graph logic.
        return cni.model_copy(update={"transcript": combined})

    token_usage: TokenUsage = Field(default_factory=TokenUsage)
