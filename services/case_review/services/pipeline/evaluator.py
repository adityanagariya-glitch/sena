"""Step 5 — Evaluator Agent.

Claude Sonnet reads the case note + retrieved NDIS policy chunks and produces a
structured compliance verdict. Only called when triage flagged=True.
Uses RAG-grounded context to prevent hallucination of regulatory rules.

Structured output: Bedrock tool use (same pattern as classifier and summarizer).
No JSON parsing or regex repair — the model must call the compliance_verdict tool
with all fields populated before the response is accepted.
"""

import asyncio
import logging

import boto3
from pydantic import BaseModel
from langfuse import observe, get_client

from core.settings import settings
from case_review.models.schemas import (
    CaseNoteInput,
    ConfidenceLevel,
    EvaluatorOutput,
    PolicyChunk,
    PolicyViolationRisk,
    TriageResult,
)
from case_review.services.pipeline.style_examples import FEW_SHOT_EVAL_REASONING, STYLE_GUIDE
from case_review.services.usage import record_and_print_converse

logger = logging.getLogger(__name__)
langfuse = get_client()
_SERVICE = "case_review_evaluator"

# ── Tool schema — replaces "Respond with JSON" prompt instruction ─────────────
# Claude must call this tool with all required fields before the response ends.
# No JSON parsing bugs, no temperature sensitivity, no regex repair.

_EVAL_TOOL = {
    "toolSpec": {
        "name": "compliance_verdict",
        "description": (
            "Record the NDIS compliance evaluation verdict. "
            "Call this tool with all fields populated to complete the evaluation."
        ),
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "incident_detected": {
                        "type": "boolean",
                        "description": "True if a regulated restrictive practice was used",
                    },
                    "practice_category": {
                        "type": "string",
                        "description": "One of: Chemical Restraint, Physical Restraint, Mechanical Restraint, Environmental Restraint, Seclusion, None",
                    },
                    "action_summary": {
                        "type": "string",
                        "description": "One-sentence description of what happened",
                    },
                    "policy_violation_risk": {
                        "type": "string",
                        "enum": ["Low", "Medium", "High", "Critical"],
                    },
                    "confidence": {
                        "type": "string",
                        "enum": ["High", "Medium", "Low"],
                        "description": "Confidence in the restrictive practice determination",
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "Evidence-based reasoning citing specific phrases from the case note",
                    },
                    "trigger_phrases": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Exact short phrases (3-10 words) indicating a restrictive practice",
                    },
                    "suppression_factors": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Exact phrases arguing against escalation (BSP reference, participant agency, medical context). Empty array if none.",
                    },
                    "bsp_mentioned_in_note": {
                        "type": "boolean",
                        "description": "True if the case note explicitly references a Behaviour Support Plan or authorisation",
                    },
                    "bsp_mention_excerpt": {
                        "type": ["string", "null"],
                        "description": "Exact phrase from the note referencing BSP/authorisation, or null",
                    },
                    "reporting_required": {
                        "type": "boolean",
                        "description": "True if mandatory NDIS Commission reporting is triggered",
                    },
                    "notification_timeframe": {
                        "type": ["string", "null"],
                        "description": "'5 business days', '24 hours', or null if no reporting required",
                    },
                },
                "required": [
                    "incident_detected",
                    "practice_category",
                    "action_summary",
                    "policy_violation_risk",
                    "confidence",
                    "reasoning",
                    "trigger_phrases",
                    "suppression_factors",
                    "bsp_mentioned_in_note",
                    "bsp_mention_excerpt",
                    "reporting_required",
                    "notification_timeframe",
                ],
            }
        },
    }
}

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

7. For "trigger_phrases": list exact short phrases (3-10 words) from the case note that indicate
   a restrictive practice was used.

8. For "suppression_factors": list exact short phrases (3-10 words) from the case note that argue
   against escalation — e.g. participant agency, reference to a BSP or approved protocol,
   medical/emergency context, voluntary nature of the activity, or staff following prescribed care.
   Empty list if there are none.

9. For "bsp_mentioned_in_note": check whether the case note explicitly references a Behaviour
   Support Plan, PBSP, practitioner approval, authorisation, or BSP-aligned strategy.
   Set to true and populate "bsp_mention_excerpt" with the exact phrase if found.

Be precise and evidence-based. Quote specific phrases from the case note in your reasoning.
Call the compliance_verdict tool with your complete analysis.
"""


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


@observe(as_type="generation", name="case-review-evaluator", capture_input=False, capture_output=False)
def _run_evaluator(
    transcript: str,
    action_summary: str,
    policy_context: str,
) -> EvaluatorOutput:
    """Synchronous Bedrock call — offloaded to thread pool."""
    client = _make_client()

    # Prompt caching: cache ONLY the truly-static prefix (style guide + few-shot).
    # The cache point splits at {policy_context} — NOT {transcript} — because the
    # retrieved policy chunks vary per case note. If they sat before the cachePoint
    # the ~25k-token prefix would be a unique cache WRITE (1.25x) almost every call
    # and never get re-read. Splitting earlier means the static style-guide+few-shot
    # block caches once and is re-read at 0.1x on every subsequent request, while the
    # variable policy chunks + transcript + action_summary are billed at full rate
    # after the cachePoint.
    prefix_tmpl, suffix_tmpl = _EVALUATOR_PROMPT.split("{policy_context}", 1)
    static_prefix = prefix_tmpl.format(
        style_guide=STYLE_GUIDE,
        few_shot_eval_reasoning=FEW_SHOT_EVAL_REASONING,
    )
    dynamic_suffix = policy_context + suffix_tmpl.format(
        transcript=transcript,
        action_summary=action_summary,
    )

    response = client.converse(
        modelId=settings.evaluator_model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"text": static_prefix},
                    {"cachePoint": {"type": "default"}},
                    {"text": dynamic_suffix},
                ],
            }
        ],
        toolConfig={
            "tools": [_EVAL_TOOL],
            "toolChoice": {"tool": {"name": "compliance_verdict"}},
        },
        inferenceConfig={"maxTokens": 8192, "temperature": 0.0},
    )
    record_and_print_converse("evaluator", response)

    usage = response.get("usage", {})
    langfuse.update_current_generation(
        model=settings.evaluator_model,
        input={"transcript": transcript[:2000], "action_summary": action_summary},
        usage_details={
            "input": usage.get("inputTokens", 0),
            "output": usage.get("outputTokens", 0),
        },
        metadata={"service": _SERVICE},
    )

    # Extract structured output from tool use block — no JSON parsing needed
    for block in response["output"]["message"]["content"]:
        tool_use = block.get("toolUse", {})
        if tool_use.get("name") == "compliance_verdict":
            data = tool_use["input"]

            try:
                risk = PolicyViolationRisk(data.get("policy_violation_risk", "Medium"))
            except ValueError:
                risk = PolicyViolationRisk.MEDIUM

            try:
                confidence = ConfidenceLevel(data.get("confidence", "High"))
            except ValueError:
                confidence = ConfidenceLevel.HIGH

            return EvaluatorOutput(
                incident_detected=bool(data.get("incident_detected", False)),
                practice_category=data.get("practice_category", "None"),
                action_summary=data.get("action_summary", ""),
                policy_violation_risk=risk,
                confidence=confidence,
                reasoning=data.get("reasoning", ""),
                trigger_phrases=data.get("trigger_phrases", []),
                suppression_factors=data.get("suppression_factors", []),
                bsp_mentioned_in_note=bool(data.get("bsp_mentioned_in_note", False)),
                bsp_mention_excerpt=data.get("bsp_mention_excerpt"),
                reporting_required=bool(data.get("reporting_required", False)),
                notification_timeframe=data.get("notification_timeframe"),
            )

    raise ValueError("Evaluator: no compliance_verdict tool_use block in Bedrock response")


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
