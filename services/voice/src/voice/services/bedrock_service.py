from __future__ import annotations

import json
import time
import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, status

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

    def _invoke_once(self, user_prompt: str, system_prompt: str = SYSTEM_PROMPT) -> dict:
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
        return json.loads(text)

    def run_dictation_turn(
        self, transcript: str, session_snapshot: dict, history: list[dict]
    ) -> tuple[dict, int]:
        prompt = build_user_prompt(
            transcript=transcript, session_snapshot=session_snapshot, history=history
        )
        start = time.perf_counter()
        last_error: Exception | None = None
        attempts = settings.provider_max_retries + 1
        for _ in range(attempts):
            try:
                data = self._invoke_once(prompt)
                latency_ms = int((time.perf_counter() - start) * 1000)
                return data, latency_ms
            except (ValueError, KeyError, BotoCoreError, ClientError) as exc:
                last_error = exc
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
                data = self._invoke_once(prompt, system_prompt=PERSONAL_DETAILS_SYSTEM_PROMPT)
                latency_ms = int((time.perf_counter() - start) * 1000)
                return data, latency_ms
            except (ValueError, KeyError, BotoCoreError, ClientError) as exc:
                last_error = exc
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "AI provider unavailable",
                "fallback_used": False,
                "retryable": True,
                "cause": str(last_error),
            },
        )
