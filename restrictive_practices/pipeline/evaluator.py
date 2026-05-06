"""Step 5 — Evaluator Agent.

Gemini Pro reads the case note + retrieved NDIS policy chunks and produces a
structured compliance verdict. Only called when triage flagged=True.
Uses RAG-grounded context to prevent hallucination of regulatory rules.
"""

import asyncio
import json
import logging

from google import genai
from google.genai import types
from pydantic import BaseModel

from config import settings
from models.schemas import (
    CaseNoteInput,
    EvaluatorOutput,
    PolicyChunk,
    PolicyViolationRisk,
    TriageResult,
)

logger = logging.getLogger(__name__)

_EVALUATOR_PROMPT = """\
You are a senior NDIS compliance officer reviewing a support worker case note.

## Relevant NDIS Policy Extracts
The following excerpts are from official NDIS regulated restrictive practices documentation.
Each extract is tagged with its document type (Regulatory Rule, Practice Standard, etc.).
Use them as your authoritative reference when making your determination.

{policy_context}

## Case Note Under Review
{transcript}

## Triage Summary
The preliminary screening identified the following potential concern:
{action_summary}

## Your Task
Analyse the case note against the NDIS policy extracts above and determine:
1. Whether a regulated restrictive practice was actually used
2. Which of the five categories applies (Chemical, Physical, Mechanical, Environmental, or Seclusion)
3. The risk level of the violation
4. A clear, evidence-based reasoning citing specific phrases from the case note
5. Whether mandatory reporting to the NDIS Commission is triggered

The five regulated restrictive practices under the NDIS are:
- Chemical Restraint: medication used to control behaviour (not for a diagnosed medical condition)
- Seclusion: involuntary confinement alone in a room or area the person cannot freely leave
- Physical Restraint: physical force to restrict free movement
- Mechanical Restraint: a device used to restrict free movement
- Environmental Restraint: restricting access to parts of the environment or liberty

Risk levels:
- Low: minor/ambiguous — could be legitimate practice, needs review
- Medium: likely restrictive practice, authorisation needs verification
- High: clear restrictive practice with no evident authorisation
- Critical: severe or repeated practice, immediate escalation required

## Reporting Obligations (NDIS Rules 2018)
Under the NDIS (Restrictive Practices and Behaviour Support) Rules 2018:
- Use of a regulated restrictive practice WITHOUT current authorisation in a Behaviour Support Plan
  is a REPORTABLE INCIDENT. Providers must notify the NDIS Commission within 5 business days.
- If the incident also involves serious injury or death of a person with disability,
  notification to the NDIS Commission is required within 24 hours.
- If no incident is detected, or the practice appears authorised, reporting is not required at this stage.

Determine:
- "reporting_required": true if incident_detected=true AND the practice appears to be used without
  authorisation (no mention of a behaviour support plan or approved protocol in the case note)
- "notification_timeframe": "5 business days" for unauthorised restrictive practice use;
  "24 hours" if serious injury or death is also described; null if no reporting required

Be precise and evidence-based. Quote specific phrases from the case note in your reasoning.
"""


class _EvaluatorResponse(BaseModel):
    incident_detected: bool
    practice_category: str
    action_summary: str
    policy_violation_risk: str
    reasoning: str
    reporting_required: bool = False
    notification_timeframe: str | None = None


def _make_client() -> genai.Client:
    if settings.use_vertex_ai:
        return genai.Client(
            vertexai=True,
            project=settings.gcp_project,
            location=settings.gcp_location,
        )
    return genai.Client(api_key=settings.gemini_api_key)


def _format_policy_context(chunks: list[PolicyChunk]) -> str:
    parts = []
    for i, chunk in enumerate(chunks, 1):
        parts.append(
            f"[{i}] [{chunk.document_type}] Category: {chunk.category} | Risk: {chunk.risk_level}\n"
            f"    Source: {chunk.document_source}\n"
            f"    {chunk.text.strip()}"
        )
    return "\n\n".join(parts)


def _run_evaluator(
    transcript: str,
    action_summary: str,
    policy_context: str,
) -> EvaluatorOutput:
    """Synchronous Gemini Pro call — offloaded to thread pool."""
    client = _make_client()

    prompt = _EVALUATOR_PROMPT.format(
        policy_context=policy_context,
        transcript=transcript,
        action_summary=action_summary,
    )

    response = client.models.generate_content(
        model=settings.evaluator_model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=_EvaluatorResponse,
            temperature=0.0,
            max_output_tokens=4096,
        ),
    )

    if not response.text:
        raise ValueError(
            f"Empty evaluator response. finish_reason="
            f"{response.candidates[0].finish_reason if response.candidates else 'NO_CANDIDATES'}"
        )

    try:
        data = json.loads(response.text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Evaluator response not valid JSON: {exc}. Raw: {response.text[:200]}") from exc
    parsed = _EvaluatorResponse(**data)

    try:
        risk = PolicyViolationRisk(parsed.policy_violation_risk)
    except ValueError:
        risk = PolicyViolationRisk.MEDIUM

    return EvaluatorOutput(
        incident_detected=parsed.incident_detected,
        practice_category=parsed.practice_category,
        action_summary=parsed.action_summary,
        policy_violation_risk=risk,
        reasoning=parsed.reasoning,
        reporting_required=parsed.reporting_required,
        notification_timeframe=parsed.notification_timeframe,
    )


async def run_evaluator(
    note: CaseNoteInput,
    triage: TriageResult,
    chunks: list[PolicyChunk],
) -> EvaluatorOutput:
    """Async entry point — embeds policy context and calls Gemini Pro."""
    logger.info("evaluator start case_note_id=%s chunks=%d", note.case_note_id, len(chunks))

    policy_context = _format_policy_context(chunks)
    action_summary = triage.action_summary or note.to_text()[:200]

    result = await asyncio.to_thread(
        _run_evaluator,
        note.to_text(),
        action_summary,
        policy_context,
    )

    logger.info(
        "evaluator done case_note_id=%s incident=%s category=%s risk=%s",
        note.case_note_id,
        result.incident_detected,
        result.practice_category,
        result.policy_violation_risk,
    )
    return result
