"""Step 0 — Incident Splitter.

A single shift can contain MULTIPLE distinct incidents (e.g. a restraint at a
shop, an environmental restriction at home, and a separate emotional outburst).
The downstream pipeline (triage → RAG → evaluator → drafter) evaluates ONE note
at a time, so this module first segments the transcript into discrete incidents.

Claude Haiku reads the full shift transcript and returns a list of incident
segments — each a self-contained slice of the narrative covering one event. The
route then runs the full pipeline once per segment, producing an independent
AI Summary / Risk Summary / Incident Report bundle for each.

If the model finds no discrete incidents, it returns [] and the caller falls
back to a single whole-shift summary.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import boto3
from pydantic import BaseModel

from core.settings import settings
from case_review.services.usage import record_and_print_converse

logger = logging.getLogger(__name__)

_SPLITTER_PROMPT = """\
You are reading a single NDIS (National Disability Insurance Scheme) support-shift \
case note. A shift can contain SEVERAL separate incidents — for example a physical \
restraint at a shop, an environmental restriction (a locked room) at home, and a \
later emotional outburst are THREE distinct incidents.

Your task: identify every DISTINCT incident or notable event in the note below and \
return each as its own segment.

What counts as an incident (include it):
- Any use of a restrictive practice (physical restraint, environmental restriction, \
chemical/seclusion/mechanical restraint), authorised OR unauthorised
- Aggression, property damage, self-harm, injury, or assault risk
- Emotional dysregulation / behavioural escalation requiring intervention
- A safety event, hazard, or significant boundary-setting event

What does NOT count (do NOT create a segment for it):
- Ordinary routine care (meals, hygiene prompts, calm activities) UNLESS it involved \
one of the events above

For each incident, copy the relevant VERBATIM portion of the note (the sentences that \
describe that specific event, with enough surrounding context to stand alone).

Respond with a single JSON array only — no markdown, no preamble. Each element:
{{"title": "<short label, e.g. 'Physical restraint at art store'>", \
"segment": "<verbatim excerpt covering this incident>"}}

If there are NO incidents at all, return an empty array: []

Case Note:
---
{transcript}
---
"""


class IncidentSegment(BaseModel):
    """One discrete incident sliced out of the shift transcript."""
    title: str
    segment: str


def _make_client():
    kwargs: dict[str, Any] = {"region_name": settings.aws_region}
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    return boto3.client("bedrock-runtime", **kwargs)


def _extract_json_array(text: str) -> list[dict]:
    """Pull the first JSON array out of the model output, tolerating fences/preamble."""
    start = text.find("[")
    if start == -1:
        return []
    end = text.rfind("]") + 1
    if end <= start:
        return []
    try:
        data = json.loads(text[start:end])
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _run_splitter(transcript: str) -> list[IncidentSegment]:
    """Synchronous Bedrock call — offloaded to a thread pool."""
    client = _make_client()
    prompt = _SPLITTER_PROMPT.format(transcript=transcript)

    response = client.converse(
        modelId=settings.triage_model,  # Haiku — cheap segmentation pass
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 4096, "temperature": 0.0},
    )
    record_and_print_converse("incident_split", response)

    raw = response["output"]["message"]["content"][0]["text"]
    items = _extract_json_array(raw)

    segments: list[IncidentSegment] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        seg = str(it.get("segment", "")).strip()
        if not seg:
            continue
        title = str(it.get("title", "")).strip() or "Incident"
        segments.append(IncidentSegment(title=title, segment=seg))
    return segments


async def split_incidents(transcript: str) -> list[IncidentSegment]:
    """Async entry point — segment a shift transcript into discrete incidents.

    Returns [] when the note contains no incidents (caller falls back to a
    single whole-shift summary).
    """
    if not transcript or not transcript.strip():
        return []
    logger.info("incident_split start chars=%d", len(transcript))
    segments = await asyncio.to_thread(_run_splitter, transcript)
    logger.info("incident_split done — %d incident(s) detected", len(segments))
    return segments
