from __future__ import annotations

import json
import time

from fastapi import HTTPException, status
from google import genai
from google.genai import types

from voice.core.settings import settings
from voice.prompts.personal_details_prompt import (
    PERSONAL_DETAILS_SYSTEM_PROMPT,
    build_personal_details_user_prompt,
)
from voice.services.usage_log import log_token_usage


class GeminiService:
    def __init__(self) -> None:
        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.model = settings.gemini_model_id

    def _invoke_once(self, user_prompt: str, system_prompt: str) -> tuple[dict, dict]:
        """Invoke Gemini and capture token usage.

        Gemini 2.5+ performs *implicit* caching automatically — repeated system
        instructions are cached by the backend with no client config required,
        and cached tokens are billed at a reduced rate. We surface the cached
        portion via ``cached_content_token_count`` so callers can report it.
        """
        response = self.client.models.generate_content(
            model=self.model,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.2,
                max_output_tokens=1200,
            ),
            contents=user_prompt,
        )
        text = (response.text or "").strip()
        # Strip markdown code fences if the model wraps output in them
        if text.startswith("```"):
            parts = text.split("```")
            text = parts[1] if len(parts) > 1 else text
            if text.startswith("json"):
                text = text[4:]

        # usage_metadata may be None on some responses — guard with getattr.
        usage = response.usage_metadata
        input_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
        output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
        # total = input + output (consistent across all SENA APIs), not Gemini's
        # total_token_count (which can include extra internal tokens).
        total_tokens = input_tokens + output_tokens
        # Tokens served from Gemini's implicit cache (billed at reduced rate).
        cache_read_tokens = int(getattr(usage, "cached_content_token_count", 0) or 0)

        log_token_usage(
            "voice_personal_details_gemini",
            input_tokens,
            output_tokens,
            cache_read_tokens=cache_read_tokens,
        )

        usage_dict = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "cache_read_tokens": cache_read_tokens,
            "cache_creation_tokens": 0,  # Gemini implicit caching has no separate creation cost
        }
        return json.loads(text.strip()), usage_dict

    def run_personal_details_turn(
        self,
        transcript: str,
        current_fields: dict,
        missing_fields: list[str],
        history: list[dict],
    ) -> tuple[dict, int, dict]:
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
                data, usage = self._invoke_once(prompt, PERSONAL_DETAILS_SYSTEM_PROMPT)
                latency_ms = int((time.perf_counter() - start) * 1000)
                return data, latency_ms, usage
            except (ValueError, KeyError, Exception) as exc:
                last_error = exc
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "Gemini AI provider unavailable",
                "fallback_used": False,
                "retryable": True,
                "cause": str(last_error),
            },
        )
