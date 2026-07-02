"""Step — Single-Shift AI Summariser.

Claude Haiku reads the case note form and produces a structured shift summary:
progress observations, risk indicators, behavioural patterns, and flagged
verbatim highlights. Runs in parallel with the triage step on every note.
"""

import asyncio
import json
import logging

import boto3
from pydantic import BaseModel

from config import settings
from models.schemas import CaseNoteInput, SummaryOutput
from pipeline.quality_score import score_note
from pipeline.style_examples import FEW_SHOT_SUMMARY, STYLE_GUIDE

logger = logging.getLogger(__name__)

_SUMMARY_PROMPT = """\
You are summarising a single NDIS (National Disability Insurance Scheme) support shift for \
a clinical supervisor reviewing case notes.

{style_guide}

{few_shot_summary}

Your task: read the support worker case note below and produce a structured summary covering \
participant progress, risk indicators, behavioural patterns, and the most noteworthy verbatim \
excerpts from the note. Write summary bullets in third-person clinical voice matching the Premium \
standard illustrated above.

Case Note:
---
{transcript}
---

Respond with a single flat JSON object only — no markdown, no extra text, no preamble.

Required keys (all at the top level — no nesting):
- "ai_confidence": float between 0.0 and 1.0 representing how complete and clear the case note is \
(1.0 = comprehensive and unambiguous; 0.0 = critically sparse or unreadable)
- "progress_identified": list of 2-5 short strings describing positive observations about \
participant progress during this shift; return [] only if absolutely nothing positive is present
- "potential_risks": list of 0-4 short strings identifying risk indicators or concerns noted in \
this shift; return [] if no risks are evident
- "patterns_detected": list of 0-3 short strings describing behavioural or situational patterns \
visible in this note (recurring themes, triggers, or trends); return [] if no patterns are evident
- "flagged_highlights": list of 2-4 strings that are direct verbatim quotes (exact words) from \
the case note that most warrant a supervisor's attention; do NOT paraphrase — copy the exact text

If any list would be empty, return [] for that key.
"""


class _SummaryResponse(BaseModel):
    """Internal parse model — ai_confidence is unconstrained so clamping happens before SummaryOutput."""

    ai_confidence: float = 0.0
    progress_identified: list[str] = []
    potential_risks: list[str] = []
    patterns_detected: list[str] = []
    flagged_highlights: list[str] = []


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


def _run_summary(text: str) -> SummaryOutput:
    """Synchronous Bedrock call — offloaded to thread pool."""
    client = _make_client()

    prompt = _SUMMARY_PROMPT.format(
        style_guide=STYLE_GUIDE,
        few_shot_summary=FEW_SHOT_SUMMARY,
        transcript=text,
    )

    response = client.converse(
        modelId=settings.triage_model,
        messages=[
            {
                "role": "user",
                "content": [{"text": prompt}],
            }
        ],
        inferenceConfig={"maxTokens": 1024, "temperature": 0.0},
    )

    raw_text = response["output"]["message"]["content"][0]["text"]
    if not raw_text:
        raise ValueError(
            f"Empty summary response. stopReason={response.get('stopReason', 'NONE')}"
        )

    try:
        data = _extract_json(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Summary response not valid JSON: {exc}. Raw: {raw_text[:200]}"
        ) from exc

    parsed = _SummaryResponse(**data)

    # Clamp ai_confidence before constructing SummaryOutput — ge/le validators would raise otherwise
    clamped_confidence = max(0.0, min(1.0, parsed.ai_confidence))

    return SummaryOutput(
        ai_confidence=clamped_confidence,
        progress_identified=parsed.progress_identified,
        potential_risks=parsed.potential_risks,
        patterns_detected=parsed.patterns_detected,
        flagged_highlights=parsed.flagged_highlights,
        # Quality fields populated in run_summary after async thread returns
    )


async def run_summary(note: CaseNoteInput) -> SummaryOutput:
    """Async entry point — offloads blocking SDK call to a thread pool."""
    logger.info("summary start case_note_id=%s", note.case_note_id)
    result = await asyncio.to_thread(_run_summary, note.to_text())

    # Run heuristic quality scorer on the original note (zero LLM cost)
    quality_score, quality_label, quality_gaps = score_note(note)
    result.note_quality_score = quality_score
    result.note_quality_label = quality_label
    result.quality_gaps = quality_gaps

    logger.info(
        "summary done case_note_id=%s ai_confidence=%.2f quality=%s score=%.3f",
        note.case_note_id,
        result.ai_confidence,
        quality_label,
        quality_score,
    )
    return result
