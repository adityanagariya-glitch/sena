from __future__ import annotations

"""
Rolling summary compressor using Gemini structured output.

Input:  past_summary (str), new_notes (list[CaseNoteDTO])
Output: SummaryResult with summary_text + metadata

Uses response_schema for reliable JSON extraction — no manual parsing.
Model: SENA_AI_GEMINI_MODEL_ID (default: gemini-3-flash-preview, standard generate_content — NOT Live API)
"""

import time
from pathlib import Path
from typing import Any

import structlog
from google import genai
from google.genai import types
from pydantic import BaseModel


import enum

class UsageFeature(str, enum.Enum):
    VOICE_ONBOARDING = "voice_onboarding"
    CASE_NOTE_DRAFTING = "case_note_drafting"
    CASE_NOTE_SUMMARY = "case_note_summary"
    INCIDENT_REPORT_ANALYSIS = "incident_report_analysis"
    AI_CHAT = "ai_chat"
    PSR_SUMMARY = "psr_summary"
    MONTHLY_REPORT = "monthly_report"
    STAFF_DOC_EXTRACTION = "staff_doc_extraction"

def emit_usage(**_kwargs: object) -> None:  # type: ignore[misc]
    return None

from case_review.models.schemas import CaseNoteDTO
from case_review.services.usage import record_gemini

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
    tenant_id: str = "phase1_tbd",
    user_id: str | None = None,
    session_id: str | None = None,
    feature: UsageFeature = UsageFeature.CASE_NOTE_SUMMARY,
) -> SummaryResult:
    """
    Compress past_summary + new_notes into an updated rolling summary.
    Returns SummaryResult with summary_text and metadata dict.

    `feature` defaults to CASE_NOTE_SUMMARY but accepts PSR_SUMMARY or
    MONTHLY_REPORT so the same summariser feeds three of the client's billable
    features without duplication. Pass the right value from the route handler.
    """
    prompt = (
        _load_prompt()
        .replace("{past_summary}", past_summary or "(No previous summary — this is the first session.)")
        .replace("{new_notes}", _format_notes(new_notes))
    )

    client = genai.Client(api_key=api_key)

    log.info("summariser.call", model=model_id, new_note_count=len(new_notes))

    start = time.perf_counter()
    try:
        response = client.models.generate_content(
            model=model_id,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_GeminiSummaryOutput,
                temperature=0.2,
            ),
        )
    except Exception as exc:
        emit_usage(
            tenant_id=tenant_id,
            user_id=user_id,
            feature=feature,
            model=model_id,
            session_id=session_id,
            latency_ms=int((time.perf_counter() - start) * 1000),
            success=False,
            failure_reason=type(exc).__name__,
        )
        raise

    latency_ms = int((time.perf_counter() - start) * 1000)
    um = getattr(response, "usage_metadata", None)
    # Accumulate into the request-scoped usage total surfaced on the API response.
    record_gemini(response)
    emit_usage(
        tenant_id=tenant_id,
        user_id=user_id,
        feature=feature,
        model=model_id,
        session_id=session_id,
        prompt_tokens=int(getattr(um, "prompt_token_count", 0) or 0),
        response_tokens=int(getattr(um, "candidates_token_count", 0) or 0),
        cached_tokens=int(getattr(um, "cached_content_token_count", 0) or 0),
        latency_ms=latency_ms,
        success=True,
        new_note_count=len(new_notes),
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
