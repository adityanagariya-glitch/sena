"""Step — NDIS Incident Report Drafter.

Claude Sonnet reads the case note + any evaluator findings and produces a
structured draft incident report per NDIS Commission requirements. Only
called when incident_occurred=True OR an UNAUTHORISED restrictive practice
was detected.
"""

import asyncio
import json
import logging

import boto3
from pydantic import BaseModel

from config import settings
from models.schemas import (
    CaseNoteInput,
    EvaluatorOutput,
    IncidentDraftOutput,
)
from pipeline.style_examples import FEW_SHOT_INCIDENT, STYLE_GUIDE

logger = logging.getLogger(__name__)

_INCIDENT_DRAFT_PROMPT = """\
You are an NDIS compliance officer drafting an incident report for submission to the NDIS Quality \
and Safeguards Commission.

{style_guide}

{few_shot_incident}

NDIS REPORTABLE INCIDENT CATEGORIES (NDIS (Incident Management and Reportable Incidents) Rules 2016):
Category 1 (notify within 24 hours):
  - Death of a person with disability
  - Serious injury of a person with disability
  - Abuse or neglect of a person with disability
  - Unlawful sexual or physical contact with, or assault of, a person with disability
  - Sexual misconduct committed against, or in the presence of, a person with disability
Category 2 (notify within 5 business days):
  - Use of a restrictive practice not in accordance with an authorisation under a Behaviour Support Plan

CANONICAL INCIDENT CATEGORIES (use for the incident_categories array):
Behavioural incident | Medication issue | Restrictive practice | Injury | Absconding |
Allegation | Abuse or neglect | Property damage | Police involvement | Hospitalisation |
Environmental hazard | Staff misconduct

## Case Note
{case_note_text}

## Prior AI Compliance Findings
{evaluator_findings}

## Your Task
Produce a structured incident report draft for the above case note.

Use the NDIS reportable incident categories listed above as your authoritative reference when \
completing the "reportable" and "notification_timeframe" fields.
Write the incident_description in third-person clinical voice matching the style example above.

Respond with a single flat JSON object — no markdown, no extra text. Use exactly these keys:

incident_type (string — e.g. "Behaviour of Concern (No Injury)", "Unauthorised Restrictive Practice", \
"Environmental Restraint")
date_of_incident (string or null — extract from shift date if present in the case note)
time_of_incident (string or null — extract from shift time if present)
location (string or null — from shift location if mentioned)
staff_involved (array of strings — worker IDs or names mentioned)
incident_description (string — 2 to 4 sentences describing what occurred, third-person clinical voice)
immediate_actions_taken (array of strings — 3 to 6 bullet points describing immediate responses)
restrictive_practice_used (boolean)
restrictive_practice_category (string or null — one of: Chemical Restraint, Physical Restraint, \
Mechanical Restraint, Environmental Restraint, Seclusion; null if not applicable)
risk_assessment (string — e.g. "Immediate risk: Low", "Immediate risk: Medium", "Immediate risk: High")
contributing_factors (array of strings)
follow_up_actions (array of strings)
compliance_checks (array of objects, each with keys "label" (string) and "passed" (boolean); \
include at minimum: "Incident documented within required timeframe", \
"Language is descriptive and non-judgmental", \
"Restrictive practice authorisation verified")
reportable (boolean — true only if the incident falls into one of the NDIS reportable categories above)
notification_timeframe (string or null — "24 hours" for Category 1, "5 business days" for Category 2, \
null if not reportable)
notification_authority (string — always "NDIS Quality and Safeguards Commission")
severity (string — one of: "Low", "Medium", "High", "Critical" based on injury/risk/category)
incident_categories (array of strings — select all applicable from the CANONICAL INCIDENT CATEGORIES list)
ongoing_risk_present (boolean — true if an unresolved risk remains after the incident)
participant_currently_safe (boolean — true if participant was safe at end of shift/report)
staff_currently_safe (boolean — true if all staff were safe)
emergency_services_required (boolean — true if police, ambulance, or emergency services were involved)
"""


class _IncidentDraftResponse(BaseModel):
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
    # Phase 1 priority fields
    severity: str = "Low"
    incident_categories: list[str] = []
    ongoing_risk_present: bool = False
    participant_currently_safe: bool = True
    staff_currently_safe: bool = True
    emergency_services_required: bool = False


def _extract_json(text: str) -> dict:
    start = text.find("{")
    if start == -1:
        raise json.JSONDecodeError("No JSON object found", text, 0)
    obj, _ = json.JSONDecoder().raw_decode(text, start)
    return obj


def _make_client():
    kwargs: dict = {"region_name": settings.aws_region}
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    return boto3.client("bedrock-runtime", **kwargs)


def _validate_compliance_checks(raw: object) -> list[dict]:
    """Return only well-formed compliance check objects; discard any malformed entries."""
    safe: list[dict] = []
    try:
        if not isinstance(raw, list):
            return safe
        for item in raw:
            if (
                isinstance(item, dict)
                and isinstance(item.get("label"), str)
                and isinstance(item.get("passed"), bool)
            ):
                safe.append({"label": item["label"], "passed": item["passed"]})
    except Exception:
        safe = []
    return safe


def _run_incident_draft(
    case_note_text: str,
    evaluator_findings: str,
) -> IncidentDraftOutput:
    """Synchronous Bedrock call — offloaded to thread pool."""
    client = _make_client()

    prompt = _INCIDENT_DRAFT_PROMPT.format(
        style_guide=STYLE_GUIDE,
        few_shot_incident=FEW_SHOT_INCIDENT,
        case_note_text=case_note_text,
        evaluator_findings=evaluator_findings,
    )

    response = client.converse(
        modelId=settings.evaluator_model,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 4096, "temperature": 0.0},
    )

    text = response["output"]["message"]["content"][0]["text"]
    if not text:
        raise ValueError(
            f"Empty incident draft response. stopReason={response.get('stopReason', 'NO_CANDIDATES')}"
        )

    try:
        data = _extract_json(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Incident draft response not valid JSON: {exc}. Raw: {text[:200]}"
        ) from exc

    parsed = _IncidentDraftResponse(**data)

    safe_checks = _validate_compliance_checks(parsed.compliance_checks)

    return IncidentDraftOutput(
        incident_type=parsed.incident_type,
        date_of_incident=parsed.date_of_incident,
        time_of_incident=parsed.time_of_incident,
        location=parsed.location,
        staff_involved=parsed.staff_involved,
        incident_description=parsed.incident_description,
        immediate_actions_taken=parsed.immediate_actions_taken,
        restrictive_practice_used=parsed.restrictive_practice_used,
        restrictive_practice_category=parsed.restrictive_practice_category,
        risk_assessment=parsed.risk_assessment,
        contributing_factors=parsed.contributing_factors,
        follow_up_actions=parsed.follow_up_actions,
        compliance_checks=safe_checks,
        reportable=parsed.reportable,
        notification_timeframe=parsed.notification_timeframe,
        notification_authority=parsed.notification_authority,
        severity=parsed.severity,
        incident_categories=parsed.incident_categories,
        ongoing_risk_present=parsed.ongoing_risk_present,
        participant_currently_safe=parsed.participant_currently_safe,
        staff_currently_safe=parsed.staff_currently_safe,
        emergency_services_required=parsed.emergency_services_required,
    )


async def run_incident_draft(
    note: CaseNoteInput,
    evaluator: EvaluatorOutput | None,
) -> IncidentDraftOutput:
    """Async entry point — offloads blocking Bedrock call to a thread pool."""
    logger.info("incident_draft start case_note_id=%s", note.case_note_id)

    if evaluator is not None:
        evaluator_findings = (
            f"Practice category: {evaluator.practice_category}\n"
            f"Summary: {evaluator.action_summary}\n"
            f"Confidence: {evaluator.confidence.value}\n"
            f"Reporting required: {evaluator.reporting_required}"
        )
    else:
        evaluator_findings = "No prior AI findings."

    result = await asyncio.to_thread(
        _run_incident_draft,
        note.to_text(),
        evaluator_findings,
    )

    logger.info(
        "incident_draft done case_note_id=%s incident_type=%s reportable=%s",
        note.case_note_id,
        result.incident_type,
        result.reportable,
    )
    return result
