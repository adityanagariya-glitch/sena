from __future__ import annotations

"""
Rolling summary compressor — Bedrock Claude Haiku via tool use.

Switched from Gemini generate_content + response_schema to Bedrock Converse +
tool use structured output. Same structured output guarantee, single vendor,
prompt caching, and record_converse token tracking.

Input:  past_summary (str), new_notes (list[CaseNoteDTO])
Output: SummaryResult with summary_text + metadata

Model: SENA_AI_SUMMARIZER_MODEL (Haiku — summarization task, no Sonnet needed)
"""

import asyncio
import time
from typing import Any

import boto3
import structlog
from langfuse import observe, get_client
from pydantic import BaseModel

from core.settings import settings
from case_review.models.schemas import CaseNoteDTO
from case_review.prompts.summarize import PROMPT as _SUMMARIZE_PROMPT
from case_review.services.usage import record_and_print_converse

log = structlog.get_logger(__name__)

langfuse = get_client()
_SERVICE = "case_review"  # Langfuse prompt namespace — do not rename, breaks managed prompt lookup
_DASHBOARD_TAG = "case_review_summarizer"  # distinct from classifier.py's tag

_lf_summarize_prompt = None
try:
    _lf_summarize_prompt = langfuse.get_prompt(f"{_SERVICE}/summarize-system")
    _SUMMARIZE_PROMPT = _lf_summarize_prompt.compile()
except Exception:
    pass  # hardcoded _SUMMARIZE_PROMPT used as fallback

# Singleton Bedrock client — avoids per-call connection overhead
_bedrock_client = None


def _get_client():
    global _bedrock_client
    if _bedrock_client is None:
        kwargs: dict = {"region_name": settings.aws_region}
        if settings.aws_access_key_id and settings.aws_secret_access_key:
            kwargs["aws_access_key_id"] = settings.aws_access_key_id
            kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
        _bedrock_client = boto3.client("bedrock-runtime", **kwargs)
    return _bedrock_client


def _load_prompt() -> str:
    return _SUMMARIZE_PROMPT


# ── Tool schema (replaces Gemini response_schema) ─────────────────────────────

_SUMMARIZE_TOOL = {
    "toolSpec": {
        "name": "summarize_case_notes",
        "description": "Produce a rolling summary of NDIS support worker case notes",
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "summary_text": {"type": "string"},
                    "metadata": {
                        "type": "object",
                        "properties": {
                            "note_count": {"type": "integer"},
                            "last_dates": {"type": "array", "items": {"type": "string"}},
                            "incident_count": {"type": "integer"},
                            "risk_flags": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["note_count", "last_dates", "incident_count", "risk_flags"],
                    },
                },
                "required": ["summary_text", "metadata"],
            }
        },
    }
}


# ── Pydantic validation ───────────────────────────────────────────────────────

class SummaryMetadata(BaseModel):
    note_count: int
    last_dates: list[str]
    incident_count: int
    risk_flags: list[str]


class SummaryResult(BaseModel):
    summary_text: str
    metadata: dict[str, Any]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_notes(notes: list[CaseNoteDTO]) -> str:
    if not notes:
        return "(none)"
    parts = []
    for n in notes:
        block = f"### Note {n.note_id} | Date: {n.date}\n"
        if n.transcript:
            block += f"**Transcript:** {n.transcript}\n"
        block += f"**Drafted note:** {n.drafted_note}"
        parts.append(block)
    return "\n\n".join(parts)


# ── Core sync call (offloaded to thread pool) ─────────────────────────────────

@observe(as_type="generation", name="summarize-case-notes", capture_input=False, capture_output=False)
def _run_summarise(past_summary: str, new_notes: list[CaseNoteDTO]) -> SummaryResult:
    """Synchronous Bedrock Converse call — runs in a thread via asyncio.to_thread."""
    template = _load_prompt()

    # Prompt caching: static base instructions → cached prefix (before first dynamic var)
    # Dynamic content: past_summary + new_notes (varies per request)
    parts = template.split("{past_summary}", 1)
    static_prefix = parts[0].strip()
    suffix = parts[1] if len(parts) > 1 else "\n{new_notes}"

    filled_past = past_summary or "(No previous summary — this is the first session.)"
    dynamic_content = filled_past + suffix.replace("{new_notes}", _format_notes(new_notes))

    client = _get_client()
    response = client.converse(
        modelId=settings.summarizer_model,
        messages=[{
            "role": "user",
            "content": [
                {"text": static_prefix},
                {"cachePoint": {"type": "default"}},  # cache static instructions
                {"text": dynamic_content},
            ],
        }],
        toolConfig={
            "tools": [_SUMMARIZE_TOOL],
            "toolChoice": {"tool": {"name": "summarize_case_notes"}},
        },
        inferenceConfig={"maxTokens": 2048, "temperature": 0.2},
    )
    record_and_print_converse("summarizer", response)
    usage = (response or {}).get("usage", {})
    langfuse.update_current_generation(
        model=settings.summarizer_model,
        input=dynamic_content,
        usage_details={
            "input": usage.get("inputTokens", 0),
            "output": usage.get("outputTokens", 0),
        },
        prompt=_lf_summarize_prompt,
        metadata={"service": _DASHBOARD_TAG},
    )

    # Extract structured output from tool use block
    for block in response["output"]["message"]["content"]:
        if block.get("toolUse", {}).get("name") == "summarize_case_notes":
            data = block["toolUse"]["input"]
            meta = SummaryMetadata(**data["metadata"])
            result = SummaryResult(
                summary_text=data["summary_text"],
                metadata=meta.model_dump(),
            )
            return result
    raise ValueError("Summarizer: no tool_use block in Bedrock response")


# ── Public async entry point ──────────────────────────────────────────────────

@observe(name="case-review-summarise", capture_input=False, capture_output=False)
async def summarise(
    past_summary: str,
    new_notes: list[CaseNoteDTO],
    *,
    api_key: str,    # kept for API compatibility — not used (Bedrock uses IAM/env)
    model_id: str,   # kept for API compatibility — settings.summarizer_model is used
    tenant_id: str = "phase1_tbd",
    user_id: str | None = None,
    session_id: str | None = None,
    feature: Any = None,  # kept for API compatibility
) -> SummaryResult:
    """Compress past_summary + new_notes into an updated rolling summary.

    api_key, model_id, and feature are accepted for backwards compatibility
    with existing route handler calls but are not used.
    """
    langfuse.update_current_span(
        input={"new_note_count": len(new_notes), "has_past_summary": bool(past_summary)},
        metadata={"service": _DASHBOARD_TAG},
    )
    log.info("summariser.call", model=settings.summarizer_model, new_note_count=len(new_notes))
    start = time.perf_counter()

    try:
        result = await asyncio.to_thread(_run_summarise, past_summary, new_notes)
    except Exception as exc:
        log.error("summariser.error", error=type(exc).__name__, msg=str(exc)[:120])
        raise

    log.info(
        "summariser.done",
        latency_ms=int((time.perf_counter() - start) * 1000),
    )
    return result
