from __future__ import annotations

"""
Rolling summary compressor using Gemini structured output.

Input:  past_summary (str), new_notes (list[CaseNoteDTO])
Output: SummaryResult with summary_text + metadata

Uses response_schema for reliable JSON extraction — no manual parsing.
Model: SENA_AI_GEMINI_MODEL_ID (default: gemini-2.5-flash)
"""

from pathlib import Path
from typing import Any

import structlog
from google import genai
from google.genai import types
from pydantic import BaseModel

from case_review.models.schemas import CaseNoteDTO

log = structlog.get_logger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "summarize.md"
_prompt_template: str | None = None


def _load_prompt() -> str:
    global _prompt_template
    if _prompt_template is None:
        _prompt_template = _PROMPT_PATH.read_text(encoding="utf-8")
    return _prompt_template


class SummaryResult(BaseModel):
    """Structured output from the summariser LLM call."""
    summary_text: str
    metadata: dict[str, Any]


class SummaryMetadata(BaseModel):
    """Schema for Gemini structured output — mirrors the JSON schema in the prompt."""
    note_count: int
    last_dates: list[str]
    incident_count: int
    risk_flags: list[str]


class _GeminiSummaryOutput(BaseModel):
    """Full structured output schema passed to response_schema."""
    summary_text: str
    metadata: SummaryMetadata


def _format_notes(notes: list[CaseNoteDTO]) -> str:
    if not notes:
        return "(none)"
    parts = []
    for n in notes:
        parts.append(
            f"### Note {n.note_id} | Date: {n.date}\n"
            f"**Transcript:** {n.transcript}\n"
            f"**Drafted note:** {n.drafted_note}"
        )
    return "\n\n".join(parts)


async def summarise(
    past_summary: str,
    new_notes: list[CaseNoteDTO],
    *,
    api_key: str,
    model_id: str,
) -> SummaryResult:
    """
    Compress past_summary + new_notes into an updated rolling summary.
    Returns SummaryResult with summary_text and metadata dict.
    """
    prompt = (
        _load_prompt()
        .replace("{past_summary}", past_summary or "(No previous summary — this is the first session.)")
        .replace("{new_notes}", _format_notes(new_notes))
    )

    client = genai.Client(api_key=api_key)

    log.info("summariser.call", model=model_id, new_note_count=len(new_notes))

    response = client.models.generate_content(
        model=model_id,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=_GeminiSummaryOutput,
            temperature=0.2,
        ),
    )

    raw = response.text
    parsed = _GeminiSummaryOutput.model_validate_json(raw)

    log.info(
        "summariser.done",
        incident_count=parsed.metadata.incident_count,
        risk_flags=parsed.metadata.risk_flags,
    )

    return SummaryResult(
        summary_text=parsed.summary_text,
        metadata=parsed.metadata.model_dump(),
    )
