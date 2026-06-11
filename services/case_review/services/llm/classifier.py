from __future__ import annotations

"""
Case note paragraph classifier using Gemini structured output.

Input:  raw_paragraph (str)
Output: ClassifyResult — classified_fields dict, confidence dict,
        missing_required list, reask_prompts list

Uses response_schema for reliable JSON — no manual parsing.
Model: SENA_AI_GEMINI_MODEL_ID (standard generate_content, NOT Live API)
"""

import time
from pathlib import Path
from typing import Any

import structlog
from google import genai
from google.genai import types
from pydantic import BaseModel

# Phase 1 telemetry — opt-in by install. Stub if sena_common not on path.
try:
    from services.shared import UsageFeature, emit_usage
except ImportError:
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

from case_review.models.case_note_field_schema import schema_as_text

log = structlog.get_logger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "classify.md"
_prompt_template: str | None = None


def _load_prompt() -> str:
    global _prompt_template
    if _prompt_template is None:
        _prompt_template = _PROMPT_PATH.read_text(encoding="utf-8")
    return _prompt_template


# ── Gemini structured output schema ──────────────────────────────────────────

class _FieldClassification(BaseModel):
    field_id: str
    value: str | None = None
    confidence: float = 0.0


class _ReaskPromptOutput(BaseModel):
    field_id: str
    label: str
    reason: str
    suggested_question: str


class _GeminiClassifyOutput(BaseModel):
    field_classifications: list[_FieldClassification]
    missing_required: list[str]
    reask_prompts: list[_ReaskPromptOutput]


# ── Public result type ────────────────────────────────────────────────────────

class ClassifyResult(BaseModel):
    classified_fields: dict[str, Any]    # field_id → extracted value (None if absent)
    confidence: dict[str, float]         # field_id → 0.0–1.0
    missing_required: list[str]          # field_ids of required fields with null value
    reask_prompts: list[dict[str, Any]]  # serialised _ReaskPromptOutput dicts


async def classify(
    raw_paragraph: str,
    *,
    api_key: str,
    model_id: str,
    tenant_id: str = "phase1_tbd",
    user_id: str | None = None,
    session_id: str | None = None,
) -> ClassifyResult:
    """
    Classify raw_paragraph into structured case note fields.

    Returns ClassifyResult. If required fields are missing, reask_prompts
    will be non-empty — callers should surface these to the staff member.

    tenant_id / user_id / session_id are PHASE-1 OPTIONAL — pass them from the
    route handler's AuthContext to enable per-org billing rollups. Default
    "phase1_tbd" sentinel is logged when caller hasn't been threaded yet.
    """
    prompt = (
        _load_prompt()
        .replace("{field_schema}", schema_as_text())
        .replace("{paragraph}", raw_paragraph)
    )

    client = genai.Client(api_key=api_key)

    log.info("classifier.call", model=model_id, paragraph_len=len(raw_paragraph))

    start = time.perf_counter()
    try:
        response = client.models.generate_content(
            model=model_id,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_GeminiClassifyOutput,
                temperature=0.1,
            ),
        )
    except Exception as exc:
        emit_usage(
            tenant_id=tenant_id,
            user_id=user_id,
            feature=UsageFeature.CASE_NOTE_SUMMARY,  # classifier feeds case_note_summary pipeline
            model=model_id,
            session_id=session_id,
            latency_ms=int((time.perf_counter() - start) * 1000),
            success=False,
            failure_reason=type(exc).__name__,
        )
        raise

    latency_ms = int((time.perf_counter() - start) * 1000)
    um = getattr(response, "usage_metadata", None)
    emit_usage(
        tenant_id=tenant_id,
        user_id=user_id,
        feature=UsageFeature.CASE_NOTE_SUMMARY,
        model=model_id,
        session_id=session_id,
        prompt_tokens=int(getattr(um, "prompt_token_count", 0) or 0),
        response_tokens=int(getattr(um, "candidates_token_count", 0) or 0),
        cached_tokens=int(getattr(um, "cached_content_token_count", 0) or 0),
        latency_ms=latency_ms,
        success=True,
        paragraph_len=len(raw_paragraph),
    )

    parsed = _GeminiClassifyOutput.model_validate_json(response.text)

    classified_fields: dict[str, Any] = {}
    confidence: dict[str, float] = {}
    for fc in parsed.field_classifications:
        classified_fields[fc.field_id] = fc.value
        confidence[fc.field_id] = fc.confidence

    log.info(
        "classifier.done",
        total_fields=len(classified_fields),
        missing_required=parsed.missing_required,
        reask_count=len(parsed.reask_prompts),
    )

    return ClassifyResult(
        classified_fields=classified_fields,
        confidence=confidence,
        missing_required=parsed.missing_required,
        reask_prompts=[rp.model_dump() for rp in parsed.reask_prompts],
    )
