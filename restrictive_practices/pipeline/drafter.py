"""Case Note Drafter — POST /v1/restrictive-practices/draft

Takes a voice transcript and uses Gemini Pro to extract content into the
structured 6-section NDIS case note form. Returns a pre-filled CaseDraftResponse
for worker review. No DB access — stateless extraction only.
"""

import asyncio
import json
import logging

import boto3
from pydantic import BaseModel

from config import settings
from models.schemas import CaseDraftResponse, DraftInput

logger = logging.getLogger(__name__)

_DRAFT_PROMPT = """\
You are an experienced NDIS case note writer assisting a support worker to complete their post-shift case note.

A support worker has recorded a voice transcript after their shift. Your task is to extract relevant information
from the transcript and map it into the six sections of the standard NDIS case note form.

FORM SECTIONS AND FIELDS:

Section 1 — Summary of Shift
  describe: What activities and community access opportunities did the worker and participant engage in together?
            Summarise the shift in 2–4 sentences.

Section 2 — Activities Completed & Skill-Building
  assisted: What tasks or activities did the worker assist the participant with?
  practised_skill: What specific skill did the participant practise during the shift?
  participants_level_of_independence: How independently did the participant perform tasks?
                                      (e.g. "High — required only verbal prompts at checkout")
  observations: Any notable observations about the participant's engagement, behaviour, or progress.

Section 3 — Well-being & Behaviour
  mood: Describe the participant's mood and emotional state during the shift.
  behavioural_events: Describe any behavioural events, incidents, or significant behaviour changes.
                      If none occurred, set to null.
  any_concerns: true if the worker expressed any concerns about the participant's wellbeing or behaviour,
                false otherwise.

Section 4 — Outcomes & Progress
  what_went_well: What positive outcomes or successes occurred during the shift?
  what_needs_further_support: What areas need more support or follow-up?
  participant_comments: Any comments or feedback expressed by the participant themselves.

Section 5 — Safety / Health Monitoring
  medication_reminders_given: true if the worker mentioned giving medication reminders or administering medication,
                              false otherwise.
  safety_hazards_observed: true if the worker noted any safety hazards, false otherwise.
  any_injuries: true if any injuries to the participant were mentioned, false otherwise.
  injury_description: If any_injuries is true, describe the injury. Otherwise null.

Section 6 — Notes / Additional Comments
  carer_feedback: Any feedback from family, carers, or other support persons.
  incident_occurred: true if the worker described any incident (behavioural, safety, or other), false otherwise.

INSTRUCTIONS:
- Extract information only from what is explicitly stated or clearly implied in the transcript.
- Do not invent or embellish details not present in the transcript.
- Use null for fields that cannot be determined from the transcript.
- Set boolean fields based on explicit mentions (e.g. "I gave him his medication" → medication_reminders_given: true).
- draft_note: Write 1–3 sentences identifying any fields that are absent or ambiguous in the transcript,
              so the worker knows what to check or add before submitting. If the transcript is comprehensive,
              set to null.

Transcript:
---
{transcript}
---

Respond with a single flat JSON object only — no markdown, no nested objects, no extra text. Include all fields listed above as top-level keys.
"""


class _DrafterResponse(BaseModel):
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
    draft_note: str | None = None


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


def _run_drafter(transcript: str) -> _DrafterResponse:
    """Synchronous Gemini Pro call — runs in a thread via asyncio.to_thread."""
    client = _make_client()

    response = client.converse(
        modelId=settings.evaluator_model,
        messages=[{"role": "user", "content": [{"text": _DRAFT_PROMPT.format(transcript=transcript)}]}],
        inferenceConfig={"maxTokens": 4096, "temperature": 0.0},
    )

    text = response["output"]["message"]["content"][0]["text"]
    if not text:
        raise ValueError(
            f"Empty drafter response. stopReason={response.get('stopReason', 'NONE')}"
        )

    try:
        data = _extract_json(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Drafter response not valid JSON: {exc}. Raw: {text[:200]}") from exc

    return _DrafterResponse(**data)


async def run_drafter(payload: DraftInput) -> CaseDraftResponse:
    """Async entry point — offloads blocking SDK call to a thread pool."""
    logger.info("drafter start case_note_id=%s worker=%s", payload.case_note_id, payload.worker_id)

    extracted = await asyncio.to_thread(_run_drafter, payload.transcript)

    logger.info("drafter done case_note_id=%s", payload.case_note_id)

    return CaseDraftResponse(
        case_note_id=payload.case_note_id,
        client_id=payload.client_id,
        worker_id=payload.worker_id,
        shift_date=payload.shift_date,
        shift_time=payload.shift_time,
        worker_position=payload.worker_position,
        describe=extracted.describe,
        assisted=extracted.assisted,
        practised_skill=extracted.practised_skill,
        participants_level_of_independence=extracted.participants_level_of_independence,
        observations=extracted.observations,
        mood=extracted.mood,
        behavioural_events=extracted.behavioural_events,
        any_concerns=extracted.any_concerns,
        what_went_well=extracted.what_went_well,
        what_needs_further_support=extracted.what_needs_further_support,
        participant_comments=extracted.participant_comments,
        medication_reminders_given=extracted.medication_reminders_given,
        safety_hazards_observed=extracted.safety_hazards_observed,
        any_injuries=extracted.any_injuries,
        injury_description=extracted.injury_description,
        carer_feedback=extracted.carer_feedback,
        incident_occurred=extracted.incident_occurred,
        draft_note=extracted.draft_note,
    )
