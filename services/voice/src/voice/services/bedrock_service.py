from __future__ import annotations

import json
import time
import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, status

<<<<<<< HEAD
# Phase 1 telemetry — opt-in by install. If sena_common isn't on the import
# path, fall back to a no-op stub so the AI critical path never fails.
# To enable real logging: `pip install -e sena-ai/shared/` from repo root.
try:
    from sena_common.usage_logger import UsageFeature, emit_usage
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

=======
>>>>>>> ai-chatbot
from voice.core.settings import settings
from voice.prompts.dictation_prompt import SYSTEM_PROMPT, build_user_prompt
from voice.prompts.personal_details_prompt import (
    PERSONAL_DETAILS_SYSTEM_PROMPT,
    build_personal_details_user_prompt,
)


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

<<<<<<< HEAD
    def _invoke_once(
        self,
        user_prompt: str,
        system_prompt: str = SYSTEM_PROMPT,
    ) -> tuple[dict, dict]:
        """Return (parsed_inner_json, raw_payload).

        raw_payload carries Anthropic's `usage` block (input_tokens,
        output_tokens, cache_*). Callers emit_usage with it.
        """
=======
    def _invoke_once(self, user_prompt: str, system_prompt: str = SYSTEM_PROMPT) -> dict:
>>>>>>> ai-chatbot
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": settings.bedrock_max_tokens,
            "temperature": settings.bedrock_temperature,
            "system": system_prompt,
            "messages": [{"role": "user", "content": [{"type": "text", "text": user_prompt}]}],
        }
        response = self.client.invoke_model(
            modelId=settings.bedrock_model_id, body=json.dumps(body)
        )
        payload = json.loads(response["body"].read())
        text = payload["content"][0]["text"]
<<<<<<< HEAD
        return json.loads(text), payload

    def run_dictation_turn(
        self,
        transcript: str,
        session_snapshot: dict,
        history: list[dict],
        *,
        tenant_id: str = "phase1_tbd",
        user_id: str | None = None,
        session_id: str | None = None,
=======
        return json.loads(text)

    def run_dictation_turn(
        self, transcript: str, session_snapshot: dict, history: list[dict]
>>>>>>> ai-chatbot
    ) -> tuple[dict, int]:
        prompt = build_user_prompt(
            transcript=transcript, session_snapshot=session_snapshot, history=history
        )
        start = time.perf_counter()
        last_error: Exception | None = None
        attempts = settings.provider_max_retries + 1
        for _ in range(attempts):
            try:
<<<<<<< HEAD
                data, payload = self._invoke_once(prompt)
                latency_ms = int((time.perf_counter() - start) * 1000)
                usage = payload.get("usage", {}) or {}
                emit_usage(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    feature=UsageFeature.CASE_NOTE_DRAFTING,
                    model=settings.bedrock_model_id,
                    session_id=session_id,
                    prompt_tokens=int(usage.get("input_tokens", 0) or 0),
                    response_tokens=int(usage.get("output_tokens", 0) or 0),
                    cached_tokens=int(
                        (usage.get("cache_read_input_tokens", 0) or 0)
                        + (usage.get("cache_creation_input_tokens", 0) or 0)
                    ),
                    latency_ms=latency_ms,
                    success=True,
                    history_turns=len(history),
                )
                return data, latency_ms
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
=======
                data = self._invoke_once(prompt)
                latency_ms = int((time.perf_counter() - start) * 1000)
                return data, latency_ms
            except (ValueError, KeyError, BotoCoreError, ClientError) as exc:
                last_error = exc
>>>>>>> ai-chatbot
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "AI provider unavailable",
                "fallback_used": False,
                "retryable": True,
                "cause": str(last_error),
            },
        )

    def run_personal_details_turn(
        self,
        transcript: str,
        current_fields: dict,
        missing_fields: list[str],
        history: list[dict],
<<<<<<< HEAD
        *,
        tenant_id: str = "phase1_tbd",
        user_id: str | None = None,
        session_id: str | None = None,
=======
>>>>>>> ai-chatbot
    ) -> tuple[dict, int]:
        prompt = build_personal_details_user_prompt(
            transcript=transcript,
            current_fields=current_fields,
            missing_fields=missing_fields,
            history=history,
        )
        start = time.perf_counter()
        last_error: Exception | None = None
        attempts = settings.provider_max_retries + 1
        for _ in range(attempts):
            try:
<<<<<<< HEAD
                data, payload = self._invoke_once(prompt, system_prompt=PERSONAL_DETAILS_SYSTEM_PROMPT)
                latency_ms = int((time.perf_counter() - start) * 1000)
                usage = payload.get("usage", {}) or {}
                emit_usage(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    # Personal-details flow rolls up under VOICE_ONBOARDING for billing —
                    # it's the client-facing onboarding voice agent, just routed through
                    # Bedrock instead of Gemini Live for this particular sub-flow.
                    feature=UsageFeature.VOICE_ONBOARDING,
                    model=settings.bedrock_model_id,
                    session_id=session_id,
                    prompt_tokens=int(usage.get("input_tokens", 0) or 0),
                    response_tokens=int(usage.get("output_tokens", 0) or 0),
                    cached_tokens=int(
                        (usage.get("cache_read_input_tokens", 0) or 0)
                        + (usage.get("cache_creation_input_tokens", 0) or 0)
                    ),
                    latency_ms=latency_ms,
                    success=True,
                    history_turns=len(history),
                    missing_field_count=len(missing_fields),
                )
                return data, latency_ms
            except (ValueError, KeyError, BotoCoreError, ClientError) as exc:
                last_error = exc
        emit_usage(
            tenant_id=tenant_id,
            user_id=user_id,
            feature=UsageFeature.VOICE_ONBOARDING,
            model=settings.bedrock_model_id,
            session_id=session_id,
            latency_ms=int((time.perf_counter() - start) * 1000),
            success=False,
            failure_reason="bedrock_provider_unavailable",
        )
=======
                data = self._invoke_once(prompt, system_prompt=PERSONAL_DETAILS_SYSTEM_PROMPT)
                latency_ms = int((time.perf_counter() - start) * 1000)
                return data, latency_ms
            except (ValueError, KeyError, BotoCoreError, ClientError) as exc:
                last_error = exc
>>>>>>> ai-chatbot
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "AI provider unavailable",
                "fallback_used": False,
                "retryable": True,
                "cause": str(last_error),
            },
        )
