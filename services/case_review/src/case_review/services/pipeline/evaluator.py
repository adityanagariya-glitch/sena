"""Step 5 — Evaluator Agent.

Claude Sonnet reads the case note + retrieved NDIS policy chunks and produces a
structured compliance verdict. Only called when triage flagged=True.
Uses RAG-grounded context to prevent hallucination of regulatory rules.
"""

import asyncio
import json
import logging

import boto3
from pydantic import BaseModel

from case_review.core.settings import settings
from case_review.models.schemas import (
    CaseNoteInput,
    ConfidenceLevel,
    EvaluatorOutput,
    PolicyChunk,
    PolicyViolationRisk,
    TriageResult,
)
from case_review.services.pipeline.style_examples import FEW_SHOT_EVAL_REASONING, STYLE_GUIDE

logger = logging.getLogger(__name__)

_EVALUATOR_PROMPT = """\
You are a senior NDIS compliance officer reviewing a support worker case note.

{style_guide}

{few_shot_eval_reasoning}

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

6. Your confidence in the restrictive practice determination:
   - "High": explicit restriction language used (e.g. "locked the door", "held him down",
     "administered medication to control behaviour", "placed in his room and held the door")
   - "Medium": restriction is implied or context-dependent (e.g. staff positioned near exit,
     redirection used, guiding someone away without explicit force)
   - "Low": wording is ambiguous and could reasonably describe non-restrictive support
     (e.g. general supervision, prompting, accompanying, standby assistance)

7. For "trigger_phrases": list exact short phrases (3–10 words) from the case note that indicate
   a restrictive practice was used.

8. For "suppression_factors": list exact short phrases (3–10 words) from the case note that argue
   against escalation — e.g. participant agency, reference to a BSP or approved protocol,
   medical/emergency context, voluntary nature of the activity, or staff following prescribed care.
   Empty list if there are none.

9. For "bsp_mentioned_in_note": check whether the case note explicitly references a Behaviour
   Support Plan, PBSP, practitioner approval, authorisation, or BSP-aligned strategy.
   Set to true and populate "bsp_mention_excerpt" with the exact phrase if found.

Be precise and evidence-based. Quote specific phrases from the case note in your reasoning.

Respond with a single flat JSON object — no nested objects, no markdown, no extra text. Use exactly these top-level keys:
incident_detected, practice_category, action_summary, policy_violation_risk, confidence, reasoning,
trigger_phrases, suppression_factors, bsp_mentioned_in_note, bsp_mention_excerpt, reporting_required, notification_timeframe.
"""


class _EvaluatorResponse(BaseModel):
    incident_detected: bool
    practice_category: str
    action_summary: str
    policy_violation_risk: str
    confidence: str = "High"
    reasoning: str
    trigger_phrases: list[str] = []
    suppression_factors: list[str] = []
    bsp_mentioned_in_note: bool = False
    bsp_mention_excerpt: str | None = None
    reporting_required: bool = False
    notification_timeframe: str | None = None


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
    """Synchronous Bedrock call — offloaded to thread pool."""
    client = _make_client()

    prompt = _EVALUATOR_PROMPT.format(
        style_guide=STYLE_GUIDE,
        few_shot_eval_reasoning=FEW_SHOT_EVAL_REASONING,
        policy_context=policy_context,
        transcript=transcript,
        action_summary=action_summary,
    )

    response = client.converse(
        modelId=settings.evaluator_model,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 8192, "temperature": 0.0},
    )

    text = response["output"]["message"]["content"][0]["text"]
    if not text:
        raise ValueError(
            f"Empty evaluator response. stopReason={response.get('stopReason', 'NO_CANDIDATES')}"
        )

    try:
        data = _extract_json(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Evaluator response not valid JSON: {exc}. Raw: {text[:200]}") from exc
    parsed = _EvaluatorResponse(**data)

    try:
        risk = PolicyViolationRisk(parsed.policy_violation_risk)
    except ValueError:
        risk = PolicyViolationRisk.MEDIUM

    try:
        confidence = ConfidenceLevel(parsed.confidence)
    except ValueError:
        confidence = ConfidenceLevel.HIGH

    return EvaluatorOutput(
        incident_detected=parsed.incident_detected,
        practice_category=parsed.practice_category,
        action_summary=parsed.action_summary,
        policy_violation_risk=risk,
        confidence=confidence,
        reasoning=parsed.reasoning,
        trigger_phrases=parsed.trigger_phrases,
        suppression_factors=parsed.suppression_factors,
        bsp_mentioned_in_note=parsed.bsp_mentioned_in_note,
        bsp_mention_excerpt=parsed.bsp_mention_excerpt,
        reporting_required=parsed.reporting_required,
        notification_timeframe=parsed.notification_timeframe,
    )


async def run_evaluator(
    note: CaseNoteInput,
    triage: TriageResult,
    chunks: list[PolicyChunk],
) -> EvaluatorOutput:
    """Async entry point — offloads blocking Bedrock call to a thread pool."""
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
