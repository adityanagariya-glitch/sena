from __future__ import annotations

import json
import time
import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, status
from langfuse import observe, get_client

# Phase 1 telemetry — opt-in by install. If sena_common isn't on the import
# path, fall back to a no-op stub so the AI critical path never fails.
# To enable real logging: `pip install -e sena-ai/shared/` from repo root.
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

from voice.core.settings import settings
from voice.prompts.dictation_prompt import SYSTEM_PROMPT, build_user_prompt
from voice.prompts.personal_details_prompt import (
    PERSONAL_DETAILS_SYSTEM_PROMPT,
    build_personal_details_user_prompt,
)
from voice.services.usage_log import log_token_usage

langfuse = get_client()
_SERVICE = "voice"  # Langfuse prompt namespace — do not rename, breaks managed prompt lookup
_TAG_DICTATION = "voice_dictation"
_TAG_PERSONAL_DETAILS = "voice_personal_details_bedrock"

_lf_dictation_prompt = None
try:
    _lf_dictation_prompt = langfuse.get_prompt(f"{_SERVICE}/dictation-system")
except Exception:
    pass

_lf_personal_details_prompt = None
try:
    _lf_personal_details_prompt = langfuse.get_prompt(f"{_SERVICE}/personal-details-system")
except Exception:
    pass


class BedrockService:
    def __init__(self):
        self.client = boto3.client(
            "bedrock-runtime",
            region_name=settings.aws_region,
            config=Config(
                read_timeout=max(2, int(settings.provider_timeout_seconds) + 1),
                retries={"max_attempts": 1},
            ),
        )

    @observe(as_type="generation", name="voice-bedrock-invoke", capture_input=False, capture_output=False)
    def _invoke_once(
        self,
        user_prompt: str,
        system_prompt: str = SYSTEM_PROMPT,
    ) -> tuple[dict, dict]:
        """Return (parsed_inner_json, raw_payload).

        raw_payload carries Anthropic's `usage` block (input_tokens,
        output_tokens, cache_*). Callers emit_usage with it.
        Uses prompt caching on system prompt to reduce token usage and latency.
        """
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": settings.bedrock_max_tokens,
            "temperature": settings.bedrock_temperature,
            "system": [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"}
                }
            ],
            "messages": [{"role": "user", "content": [{"type": "text", "text": user_prompt}]}],
        }
        response = self.client.invoke_model(
            modelId=settings.bedrock_model_id, body=json.dumps(body)
        )
        payload = json.loads(response["body"].read())
        text = payload["content"][0]["text"]
        usage = payload.get("usage", {}) or {}
        is_personal_details = system_prompt is PERSONAL_DETAILS_SYSTEM_PROMPT
        lf_prompt = _lf_personal_details_prompt if is_personal_details else _lf_dictation_prompt
        tag = _TAG_PERSONAL_DETAILS if is_personal_details else _TAG_DICTATION
        langfuse.update_current_generation(
            model=settings.bedrock_model_id,
            input=user_prompt[:2000],
            output=text[:2000],
            usage_details={
                "input": int(usage.get("input_tokens", 0) or 0),
                "output": int(usage.get("output_tokens", 0) or 0),
            },
            prompt=lf_prompt,
            metadata={"service": tag},
        )
        return json.loads(text), payload

    @observe(name="voice-dictation", capture_input=False, capture_output=False)
    def run_dictation_turn(
        self,
        transcript: str,
        session_snapshot: dict,
        history: list[dict],
        *,
        tenant_id: str = "phase1_tbd",
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> tuple[dict, int, dict]:
        langfuse.update_current_span(
            input={"transcript_len": len(transcript), "history_turns": len(history)},
            metadata={"service": _TAG_DICTATION},
        )
        prompt = build_user_prompt(
            transcript=transcript, session_snapshot=session_snapshot, history=history
        )
        start = time.perf_counter()
        last_error: Exception | None = None
        attempts = settings.provider_max_retries + 1
        for _ in range(attempts):
            try:
                data, payload = self._invoke_once(prompt)
                latency_ms = int((time.perf_counter() - start) * 1000)
                usage = payload.get("usage", {}) or {}
                input_tokens = int(usage.get("input_tokens", 0) or 0)
                output_tokens = int(usage.get("output_tokens", 0) or 0)
                cache_read_tokens = int(usage.get("cache_read_input_tokens", 0) or 0)
                cache_creation_tokens = int(usage.get("cache_creation_input_tokens", 0) or 0)
                emit_usage(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    feature=UsageFeature.CASE_NOTE_DRAFTING,
                    model=settings.bedrock_model_id,
                    session_id=session_id,
                    prompt_tokens=input_tokens,
                    response_tokens=output_tokens,
                    cache_read_tokens=cache_read_tokens,
                    cache_write_tokens=cache_creation_tokens,
                    latency_ms=latency_ms,
                    success=True,
                    history_turns=len(history),
                )
                log_token_usage(
                    "voice_dictation",
                    input_tokens,
                    output_tokens,
                    cache_read_tokens=cache_read_tokens,
                    cache_write_tokens=cache_creation_tokens,
                )
                token_usage = {
                    "input_tokens": input_tokens + cache_read_tokens + cache_creation_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": input_tokens + cache_read_tokens + cache_creation_tokens + output_tokens,
                    "cache_read_tokens": cache_read_tokens,
                    "cache_creation_tokens": cache_creation_tokens,
                }
                return data, latency_ms, token_usage
            except (ValueError, KeyError, BotoCoreError, ClientError) as exc:
                last_error = exc
        emit_usage(
            tenant_id=tenant_id,
            user_id=user_id,
            feature=UsageFeature.CASE_NOTE_DRAFTING,
            model=settings.bedrock_model_id,
            session_id=session_id,
            latency_ms=int((time.perf_counter() - start) * 1000),
            success=False,
            failure_reason="bedrock_provider_unavailable",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "AI provider unavailable",
                "fallback_used": False,
                "retryable": True,
                "cause": str(last_error),
            },
        )

#    @observe(name="voice-personal-details", capture_input=False, capture_output=False)
    # TODO: This method is dead code — never called (personal details uses Gemini instead).
    # Commented out pending test verification. If tests pass, delete this method entirely.
    # See: voice/services/personal_details_service.py which routes to gemini.run_personal_details_turn()
    #
    # def run_personal_details_turn(
    #     self,
    #     transcript: str,
    #     current_fields: dict,
    #     missing_fields: list[str],
    #     history: list[dict],
    #     *,
    #     tenant_id: str = "phase1_tbd",
    #     user_id: str | None = None,
    #     session_id: str | None = None,
    # ) -> tuple[dict, int, dict]:
    #     langfuse.update_current_span(
    #         input={"transcript_len": len(transcript), "missing_field_count": len(missing_fields)},
    #         metadata={"service": _TAG_PERSONAL_DETAILS},
    #     )
    #     prompt = build_personal_details_user_prompt(
    #         transcript=transcript,
    #         current_fields=current_fields,
    #         missing_fields=missing_fields,
    #         history=history,
    #     )
    #     start = time.perf_counter()
    #     last_error: Exception | None = None
    #     attempts = settings.provider_max_retries + 1
    #     for _ in range(attempts):
    #         try:
    #             data, payload = self._invoke_once(prompt, system_prompt=PERSONAL_DETAILS_SYSTEM_PROMPT)
    #             latency_ms = int((time.perf_counter() - start) * 1000)
    #             usage = payload.get("usage", {}) or {}
    #             input_tokens = int(usage.get("input_tokens", 0) or 0)
    #             output_tokens = int(usage.get("output_tokens", 0) or 0)
    #             cache_read_tokens = int(usage.get("cache_read_input_tokens", 0) or 0)
    #             cache_creation_tokens = int(usage.get("cache_creation_input_tokens", 0) or 0)
    #             emit_usage(
    #                 tenant_id=tenant_id,
    #                 user_id=user_id,
    #                 feature=UsageFeature.VOICE_ONBOARDING,
    #                 model=settings.bedrock_model_id,
    #                 session_id=session_id,
    #                 prompt_tokens=input_tokens,
    #                 response_tokens=output_tokens,
    #                 cache_read_tokens=cache_read_tokens,
    #                 cache_write_tokens=cache_creation_tokens,
    #                 latency_ms=latency_ms,
    #                 success=True,
    #                 history_turns=len(history),
    #                 missing_field_count=len(missing_fields),
    #             )
    #             log_token_usage(
    #                 "voice_personal_details_bedrock",
    #                 input_tokens,
    #                 output_tokens,
    #                 cache_read_tokens=cache_read_tokens,
    #                 cache_write_tokens=cache_creation_tokens,
    #             )
    #             token_usage = {
    #                 "input_tokens": input_tokens + cache_read_tokens + cache_creation_tokens,
    #                 "output_tokens": output_tokens,
    #                 "total_tokens": input_tokens + cache_read_tokens + cache_creation_tokens + output_tokens,
    #                 "cache_read_tokens": cache_read_tokens,
    #                 "cache_creation_tokens": cache_creation_tokens,
    #             }
    #             return data, latency_ms, token_usage
    #         except (ValueError, KeyError, BotoCoreError, ClientError) as exc:
    #             last_error = exc
    #     emit_usage(
    #         tenant_id=tenant_id,
    #         user_id=user_id,
    #         feature=UsageFeature.VOICE_ONBOARDING,
    #         model=settings.bedrock_model_id,
    #         session_id=session_id,
    #         latency_ms=int((time.perf_counter() - start) * 1000),
    #         success=False,
    #         failure_reason="bedrock_provider_unavailable",
    #     )
    #     raise HTTPException(
    #         status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    #         detail={
    #             "error": "AI provider unavailable",
    #             "fallback_used": False,
    #             "retryable": True,
    #             "cause": str(last_error),
    #         },
    #
    #)