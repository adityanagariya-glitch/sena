from __future__ import annotations

"""
Case note paragraph classifier — Bedrock Claude Haiku via tool use.

Switched from Gemini generate_content + response_schema to Bedrock Converse +
tool use structured output. Tool use on Claude enforces the JSON schema at the
model level — same reliability as Gemini response_schema but on a single vendor
(AWS Bedrock) with prompt caching and record_converse token tracking.

Input:  raw_paragraph (str)
Output: ClassifyResult — classified_fields dict, confidence dict,
        missing_required list, reask_prompts list

Model: SENA_AI_CLASSIFIER_MODEL (Haiku — extraction task, no Sonnet needed)
"""

import asyncio
import time
from pathlib import Path
from typing import Any

import boto3
import structlog
from pydantic import BaseModel

from core.settings import settings
from case_review.models.case_note_field_schema import schema_as_text
from case_review.services.usage import record_and_print_converse

log = structlog.get_logger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "classify.md"
_prompt_template: str | None = None

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
    global _prompt_template
    if _prompt_template is None:
        _prompt_template = _PROMPT_PATH.read_text(encoding="utf-8")
    return _prompt_template


# ── Tool schema (replaces Gemini response_schema) ─────────────────────────────
# Claude tool use enforces this JSON schema at the model level — no manual parsing.

_CLASSIFY_TOOL = {
    "toolSpec": {
        "name": "classify_case_note",
        "description": "Extract and classify NDIS case note fields from the raw paragraph",
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "field_classifications": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "field_id": {"type": "string"},
                                "value": {"type": ["string", "null"]},
                                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                            },
                            "required": ["field_id", "confidence"],
                        },
                    },
                    "missing_required": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "reask_prompts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "field_id": {"type": "string"},
                                "label": {"type": "string"},
                                "reason": {"type": "string"},
                                "suggested_question": {"type": "string"},
                            },
                            "required": ["field_id", "label", "reason", "suggested_question"],
                        },
                    },
                },
                "required": ["field_classifications", "missing_required", "reask_prompts"],
            }
        },
    }
}


# ── Pydantic validation models ────────────────────────────────────────────────

class _FieldClassification(BaseModel):
    field_id: str
    value: str | None = None
    confidence: float = 0.0


class _ReaskPromptOutput(BaseModel):
    field_id: str
    label: str
    reason: str
    suggested_question: str


class _ClassifyOutput(BaseModel):
    field_classifications: list[_FieldClassification]
    missing_required: list[str]
    reask_prompts: list[_ReaskPromptOutput]


# ── Public result type ────────────────────────────────────────────────────────

class ClassifyResult(BaseModel):
    classified_fields: dict[str, Any]
    confidence: dict[str, float]
    missing_required: list[str]
    reask_prompts: list[dict[str, Any]]


# ── Core sync call (offloaded to thread pool) ─────────────────────────────────

def _run_classify(raw_paragraph: str) -> ClassifyResult:
    """Synchronous Bedrock Converse call — runs in a thread via asyncio.to_thread."""
    template = _load_prompt().replace("{field_schema}", schema_as_text())

    # Prompt caching: static instructions + field schema → cached prefix
    # Only the raw paragraph varies per call.
    parts = template.split("{paragraph}", 1)
    static_prefix = parts[0].strip()
    suffix = parts[1].strip() if len(parts) > 1 and parts[1].strip() else ""
    dynamic_content = raw_paragraph + ("\n\n" + suffix if suffix else "")

    client = _get_client()
    response = client.converse(
        modelId=settings.classifier_model,
        messages=[{
            "role": "user",
            "content": [
                {"text": static_prefix},
                {"cachePoint": {"type": "default"}},  # cache static instructions
                {"text": dynamic_content},
            ],
        }],
        toolConfig={
            "tools": [_CLASSIFY_TOOL],
            "toolChoice": {"tool": {"name": "classify_case_note"}},
        },
        inferenceConfig={"maxTokens": 2048, "temperature": 0.1},
    )
    record_and_print_converse("classifier", response)

    # Extract structured output from tool use block
    for block in response["output"]["message"]["content"]:
        if block.get("toolUse", {}).get("name") == "classify_case_note":
            parsed = _ClassifyOutput(**block["toolUse"]["input"])
            return ClassifyResult(
                classified_fields={fc.field_id: fc.value for fc in parsed.field_classifications},
                confidence={fc.field_id: fc.confidence for fc in parsed.field_classifications},
                missing_required=parsed.missing_required,
                reask_prompts=[rp.model_dump() for rp in parsed.reask_prompts],
            )
    raise ValueError("Classifier: no tool_use block in Bedrock response")


# ── Public async entry point ──────────────────────────────────────────────────

async def classify(
    raw_paragraph: str,
    *,
    api_key: str,    # kept for API compatibility — not used (Bedrock uses IAM/env)
    model_id: str,   # kept for API compatibility — settings.classifier_model is used
    tenant_id: str = "phase1_tbd",
    user_id: str | None = None,
    session_id: str | None = None,
) -> ClassifyResult:
    """Classify raw_paragraph into structured NDIS case note fields.

    api_key and model_id are accepted for backwards compatibility with existing
    route handler calls but are not used — Bedrock authenticates via IAM/env vars
    and the model is controlled by settings.classifier_model.
    """
    log.info("classifier.call", model=settings.classifier_model, paragraph_len=len(raw_paragraph))
    start = time.perf_counter()

    try:
        result = await asyncio.to_thread(_run_classify, raw_paragraph)
    except Exception as exc:
        log.error("classifier.error", error=type(exc).__name__, msg=str(exc)[:120])
        raise

    log.info(
        "classifier.done",
        total_fields=len(result.classified_fields),
        missing_required=result.missing_required,
        reask_count=len(result.reask_prompts),
        latency_ms=int((time.perf_counter() - start) * 1000),
    )
    return result
