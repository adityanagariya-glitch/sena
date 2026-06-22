"""Case Note Drafter — POST /v1/case-review/voice/draft

Extracts structured case note fields from a free-text shift transcript using
Bedrock Claude Sonnet. Returns initial_values in {section_id: {field_id: value}}
format, ready for seeding a voice session's FormState so Gemini only handles the
remaining empty fields.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import boto3
import structlog
from pydantic import BaseModel

from core.settings import settings
from case_review.services.usage import record_and_print_converse

log = structlog.get_logger(__name__)

_STYLE_GUIDE = """\
WRITING STYLE — MANDATORY:
- Third-person, clinical, objective voice ("Participant demonstrated…", NOT "He was ok…")
- Past tense, complete sentences, no abbreviations
- Specific observable indicators (e.g. "raised vocal tone", "avoided eye contact") not vague labels
- No subjective judgements ("seemed fine", "was good") — describe observable behaviours only
- Professional NDIS documentation register throughout
"""

_DRAFT_PROMPT = """\
You are an experienced NDIS case note writer assisting a support worker to document a completed shift.

{style_guide}

A support worker has dictated their shift notes. Extract relevant information and map it into the
standard NDIS case note form. Produce field content that is professional, specific, and clinically
appropriate (2–4 sentences for narrative fields; specific observable indicators throughout).

FORM FIELDS TO EXTRACT:

Section: summary
  summaryOfShift: Concise 2–4 sentence overview of the shift focus, activities, and participant
                  presentation.

Section: activitiesAndSkill
  assisted: What tasks did the worker assist the participant with?
  practisedSkill: What specific skill did the participant practise?
  participantsLevelOfIndependence: Level of independence shown (e.g. "High — required verbal prompts
                                   only at checkout").
  observation: Notable observations about engagement, behaviour, or progress.

Section: wellbeingAndBehaviour
  mood: The participant's mood and emotional state throughout the shift.
  behaviouralEvents: Any behavioural events or significant changes. null if none occurred.
  anyConcerns: true if the worker expressed any wellbeing or behavioural concerns, false otherwise.

Section: outcomesAndProgress
  whatWentWell: Positive outcomes or successes during the shift.
  furtherSupport: Areas needing additional support or follow-up.
  participantsComments: Any comments or feedback the participant themselves expressed.

Section: safetyAndHealth
  medicationReminderGiven: true if medication reminders or administration were mentioned, false otherwise.
  safetyHazardObserved: true if any safety hazards were noted, false otherwise.
  anyInjuries: true if any injuries to the participant were mentioned, false otherwise.
  injuryDetails: Describe the injury if anyInjuries is true; otherwise null.

Section: feedback
  careFeedback: Any feedback from family, carers, or other support persons. null if none mentioned.
  anyIncident: true if any incident (behavioural, safety, or other) occurred, false otherwise.

Section: handover
  handover: Handover note for the next worker — 2–4 sentences summarising what they need to know.

INSTRUCTIONS:
- Extract only from what is explicitly stated or clearly implied. Never invent details.
- Use null for string fields that cannot be determined from the transcript.
- Boolean fields: set based on explicit mentions; default false if no mention.
- gaps_note: 1–2 sentences identifying absent or ambiguous fields the worker should clarify with voice.
             null if the transcript is comprehensive.

Transcript:
---
{transcript}
---

Respond with a single JSON object only — no markdown, no extra text. All keys must use camelCase
exactly as listed above.
"""

# Flat extracted model — maps directly to the Bedrock JSON response.
_FIELD_MAP: dict[str, tuple[str, str]] = {
    "summaryOfShift":                 ("summary",               "summaryOfShift"),
    "assisted":                        ("activitiesAndSkill",    "assisted"),
    "practisedSkill":                  ("activitiesAndSkill",    "practisedSkill"),
    "participantsLevelOfIndependence": ("activitiesAndSkill",    "participantsLevelOfIndependence"),
    "observation":                     ("activitiesAndSkill",    "observation"),
    "mood":                            ("wellbeingAndBehaviour", "mood"),
    "behaviouralEvents":               ("wellbeingAndBehaviour", "behaviouralEvents"),
    "anyConcerns":                     ("wellbeingAndBehaviour", "anyConcerns"),
    "whatWentWell":                    ("outcomesAndProgress",   "whatWentWell"),
    "furtherSupport":                  ("outcomesAndProgress",   "furtherSupport"),
    "participantsComments":            ("outcomesAndProgress",   "participantsComments"),
    "medicationReminderGiven":         ("safetyAndHealth",       "medicationReminderGiven"),
    "safetyHazardObserved":            ("safetyAndHealth",       "safetyHazardObserved"),
    "anyInjuries":                     ("safetyAndHealth",       "anyInjuries"),
    "injuryDetails":                   ("safetyAndHealth",       "injuryDetails"),
    "careFeedback":                    ("feedback",              "careFeedback"),
    "anyIncident":                     ("feedback",              "anyIncident"),
    "handover":                        ("handover",              "handover"),
}


class _Extracted(BaseModel):
    summaryOfShift: str | None = None
    assisted: str | None = None
    practisedSkill: str | None = None
    participantsLevelOfIndependence: str | None = None
    observation: str | None = None
    mood: str | None = None
    behaviouralEvents: str | None = None
    anyConcerns: bool = False
    whatWentWell: str | None = None
    furtherSupport: str | None = None
    participantsComments: str | None = None
    medicationReminderGiven: bool = False
    safetyHazardObserved: bool = False
    anyInjuries: bool = False
    injuryDetails: str | None = None
    careFeedback: str | None = None
    anyIncident: bool = False
    handover: str | None = None
    gaps_note: str | None = None


def _extract_json(text: str) -> dict[str, Any]:
    start = text.find("{")
    if start == -1:
        raise json.JSONDecodeError("No JSON object found", text, 0)
    obj, _ = json.JSONDecoder().raw_decode(text, start)
    return obj  # type: ignore[return-value]


def _make_client() -> Any:
    kwargs: dict[str, Any] = {"region_name": settings.aws_region}
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    return boto3.client("bedrock-runtime", **kwargs)


def _run_sync(transcript: str) -> _Extracted:
    """Synchronous Bedrock call — offloaded via asyncio.to_thread."""
    client = _make_client()
    # Prompt caching: static prefix (style guide + instructions) cached before
    # the cachePoint; only the transcript varies per request.
    prefix_tmpl, suffix_tmpl = _DRAFT_PROMPT.split("{transcript}", 1)
    static_prefix = prefix_tmpl.format(style_guide=_STYLE_GUIDE)
    dynamic_suffix = transcript + suffix_tmpl
    response = client.converse(
        modelId=settings.bedrock_model_id,
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
        inferenceConfig={"maxTokens": 4096, "temperature": 0.0},
    )
    record_and_print_converse("voice_drafter", response)
    text = response["output"]["message"]["content"][0]["text"]
    if not text:
        raise ValueError(
            f"Empty drafter response. stopReason={response.get('stopReason', 'NONE')}"
        )
    try:
        data = _extract_json(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Drafter not valid JSON: {exc}. Raw: {text[:200]}") from exc
    # LLM sometimes nests a field one level too deep when section and field share the same
    # name (e.g. handover: {handover: "..."} instead of handover: "..."). Flatten those.
    for key in list(data.keys()):
        v = data[key]
        if isinstance(v, dict) and len(v) == 1 and key in v:
            data[key] = v[key]
    return _Extracted(**data)


async def run_draft(transcript: str) -> tuple[dict[str, dict[str, Any]], str | None]:
    """Extract case note fields from a shift transcript.

    Returns:
        (initial_values, gaps_note) where initial_values is {section_id: {field_id: value}}
        ready for FormState seeding, and gaps_note is an optional guidance string.
    """
    log.info("draft_start", transcript_chars=len(transcript))
    extracted = await asyncio.to_thread(_run_sync, transcript)
    log.info("draft_done", has_gaps=bool(extracted.gaps_note))

    initial_values: dict[str, dict[str, Any]] = {}
    for field_name, (section_id, field_id) in _FIELD_MAP.items():
        val = getattr(extracted, field_name, None)
        # Skip None string fields. Include booleans (False = explicitly not present in shift).
        if val is None:
            continue
        if section_id not in initial_values:
            initial_values[section_id] = {}
        initial_values[section_id][field_id] = val

    return initial_values, extracted.gaps_note
