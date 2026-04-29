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

Be precise and evidence-based. Quote specific phrases from the case note in your reasoning.
"""


class _EvaluatorResponse(BaseModel):
    incident_detected: bool
    practice_category: str
    action_summary: str
    policy_violation_risk: str
    reasoning: str


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
            f"[{i}] Category: {chunk.category} | Risk: {chunk.risk_level}\n"
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

    data = json.loads(response.text)
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
    )


async def run_evaluator(
    note: CaseNoteInput,
    triage: TriageResult,
    chunks: list[PolicyChunk],
) -> EvaluatorOutput:
    """Async entry point — embeds policy context and calls Gemini Pro."""
    logger.info("evaluator start case_note_id=%s chunks=%d", note.case_note_id, len(chunks))

    policy_context = _format_policy_context(chunks)
    action_summary = triage.action_summary or note.transcript[:200]

    result = await asyncio.to_thread(
        _run_evaluator,
        note.transcript,
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
