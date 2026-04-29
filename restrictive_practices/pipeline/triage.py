"""Step 3 — Triage Classifier.

Gemini Flash gates the pipeline: cheap YES/NO decision before any RAG or Pro call.
Returns flagged=True + a 1-sentence action_summary only when a restrictive practice
signal is detected, allowing ~70% of clean notes to exit early.
"""

import asyncio
import json
import logging

from google import genai
from google.genai import types
from pydantic import BaseModel

from config import settings
from models.schemas import CaseNoteInput, TriageResult

logger = logging.getLogger(__name__)

_TRIAGE_PROMPT = """\
You are a compliance auditor for an Australian NDIS (National Disability Insurance Scheme) service provider.

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

Respond with JSON:
- "flagged": true if ANY restrictive practice is described or strongly implied, false otherwise
- "action_summary": a single sentence describing what was done (only when flagged=true, otherwise null)

Be conservative — flag if uncertain. False negatives (missed incidents) are worse than false positives.
"""


class _TriageResponse(BaseModel):
    flagged: bool
    action_summary: str | None = None


def _make_client() -> genai.Client:
    if settings.use_vertex_ai:
        return genai.Client(
            vertexai=True,
            project=settings.gcp_project,
            location=settings.gcp_location,
        )
    return genai.Client(api_key=settings.gemini_api_key)


def _run_triage(transcript: str) -> TriageResult:
    """Synchronous Gemini Flash call — runs in a thread via asyncio.to_thread."""
    client = _make_client()

    response = client.models.generate_content(
        model=settings.triage_model,
        contents=_TRIAGE_PROMPT.format(transcript=transcript),
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            # No response_schema — avoids triggering verbose thinking on a simple YES/NO task
            temperature=0.0,
            max_output_tokens=512,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )

    if not response.text:
        raise ValueError(f"Empty triage response. finish_reason={response.candidates[0].finish_reason if response.candidates else 'NONE'}")

    data = json.loads(response.text)
    parsed = _TriageResponse(**data)
    return TriageResult(
        flagged=parsed.flagged,
        action_summary=parsed.action_summary or None,
    )


async def run_triage(note: CaseNoteInput) -> TriageResult:
    """Async entry point — offloads blocking SDK call to a thread pool."""
    logger.info("triage start case_note_id=%s", note.case_note_id)
    result = await asyncio.to_thread(_run_triage, note.transcript)
    logger.info(
        "triage done case_note_id=%s flagged=%s",
        note.case_note_id,
        result.flagged,
    )
    return result
