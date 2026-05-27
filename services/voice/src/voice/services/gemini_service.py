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


class GeminiService:
    def __init__(self) -> None:
        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.model = settings.gemini_model_id

    def _invoke_once(self, user_prompt: str, system_prompt: str) -> dict:
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
        return json.loads(text.strip())

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
                data = self._invoke_once(prompt, PERSONAL_DETAILS_SYSTEM_PROMPT)
                latency_ms = int((time.perf_counter() - start) * 1000)
                return data, latency_ms
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
