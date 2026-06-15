"""Step 3 — Triage Classifier.

Claude Haiku gates the pipeline: cheap YES/NO decision before any RAG or Sonnet call.
Returns flagged=True + a 1-sentence action_summary only when a restrictive practice
signal is detected, allowing ~70% of clean notes to exit early.
"""

import asyncio
import json
import logging

import boto3
from pydantic import BaseModel

from services.case_review.core.settings import settings
from case_review.models.schemas import CaseNoteInput, TriageResult
from case_review.services.pipeline.style_examples import FEW_SHOT_TRIAGE

logger = logging.getLogger(__name__)

_TRIAGE_PROMPT = """\
You are a compliance auditor for an Australian NDIS (National Disability Insurance Scheme) service provider.

{few_shot_triage}

Your task: read the support worker case note below and determine whether it contains ANY evidence of a
regulated restrictive practice being used on a participant.

The five regulated restrictive practices under the NDIS are:
1. Chemical Restraint — using medication (not prescribed for a medical condition) to control behaviour
2. Seclusion — involuntary confinement of a person alone in a room or area they cannot freely leave
3. Physical Restraint — using physical force to restrict a person's free movement
4. Mechanical Restraint — using a device to restrict a person's free movement
5. Environmental Restraint — restricting a person's access to parts of their environment or their liberty

Case Note:
---
{transcript}
---

Respond with a single flat JSON object only — no markdown, no extra text.
Keys: "flagged" (bool) and "action_summary" (str or null).

Be conservative — flag if uncertain. False negatives (missed incidents) are worse than false positives.
"""


class _TriageResponse(BaseModel):
    flagged: bool
    action_summary: str | None = None


def _extract_json(text: str) -> dict:
    """Extract JSON object from model output, tolerating markdown fences and trailing text."""
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


def _run_triage(transcript: str) -> TriageResult:
    """Synchronous Bedrock call — runs in a thread via asyncio.to_thread."""
    client = _make_client()

    response = client.converse(
        modelId=settings.triage_model,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "text": _TRIAGE_PROMPT.format(
                            few_shot_triage=FEW_SHOT_TRIAGE,
                            transcript=transcript,
                        )
                    }
                ],
            }
        ],
        inferenceConfig={"maxTokens": 512, "temperature": 0.0},
    )

    text = response["output"]["message"]["content"][0]["text"]
    if not text:
        raise ValueError(f"Empty triage response. stopReason={response.get('stopReason', 'NONE')}")

    try:
        data = _extract_json(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Triage response not valid JSON: {exc}. Raw: {text[:200]}") from exc
    parsed = _TriageResponse(**data)
    return TriageResult(
        flagged=parsed.flagged,
        action_summary=parsed.action_summary or None,
    )


async def run_triage(note: CaseNoteInput) -> TriageResult:
    """Async entry point — offloads blocking SDK call to a thread pool."""
    logger.info("triage start case_note_id=%s", note.case_note_id)
    result = await asyncio.to_thread(_run_triage, note.to_text())
    logger.info(
        "triage done case_note_id=%s flagged=%s",
        note.case_note_id,
        result.flagged,
    )
    return result
