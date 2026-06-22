from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from types import TracebackType
from typing import Any

from google import genai
from google.genai import types

from voice.core.settings import settings
from voice.services.personal_details_service import (
    ALL_FIELDS,
    _compute_completeness,
    _compute_missing,
)
from voice.services.usage_log import log_token_usage

logger = logging.getLogger(__name__)

_LIVE_SYSTEM_PROMPT = """
You are the SENA Onboarding Agent helping collect participant personal details through a voice conversation.
Guide the participant or their support worker through filling in a personal details form conversationally.

Ask for missing fields naturally — one or two at a time. Confirm values before moving on.
Use Australian English. Be warm, patient, and clear.

IMPORTANT: When you extract one or more field values from the conversation, call update_fields IMMEDIATELY.
Do not wait until the end — call it as soon as you are confident about any value.

Fields to collect:
- first_name, last_name, email
- phone (Australian format, e.g. +61 4XX XXX XXX)
- date_of_birth (DD/MM/YYYY — parse natural language, e.g. "5th March 1985" → "05/03/1985")
- gender (accept any free-text response)
- about_me (short personal bio)
- preferred_language (default "English" if not mentioned)
- interpreter_required (boolean — only ask if preferred_language is not English)
- address_street, address_state, address_city, address_zip
- service_address_same (true/false — ask if service address differs from home)
- service_address_street/state/city/zip (only if service_address_same is false)
- emergency_contact_name, emergency_contact_relation, emergency_contact_email, emergency_contact_phone

Rules:
- Only include fields in update_fields where you have clear, confirmed information.
- Normalise phone to +61 format where possible.
- For interpreter_required: default false unless explicitly mentioned.
- Once a field is confirmed, never ask for it again.
- If the participant seems confused, offer a gentle example.
""".strip()

_UPDATE_FIELDS_DECLARATION = types.FunctionDeclaration(
    name="update_fields",
    description=(
        "Call immediately whenever you extract confirmed personal detail fields from the conversation. "
        "Only include fields you are confident about — omit fields you are unsure of."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            **{
                field: types.Schema(type=types.Type.STRING)
                for field in [
                    "first_name",
                    "last_name",
                    "email",
                    "phone",
                    "date_of_birth",
                    "gender",
                    "about_me",
                    "preferred_language",
                    "address_street",
                    "address_state",
                    "address_city",
                    "address_zip",
                    "service_address_street",
                    "service_address_state",
                    "service_address_city",
                    "service_address_zip",
                    "emergency_contact_name",
                    "emergency_contact_relation",
                    "emergency_contact_email",
                    "emergency_contact_phone",
                ]
            },
            "interpreter_required": types.Schema(type=types.Type.BOOLEAN),
            "service_address_same": types.Schema(type=types.Type.BOOLEAN),
        },
    ),
)


class GeminiLiveService:
    """
    Manages one Gemini Live WebSocket session for the personal details onboarding flow.

    Usage::

        async with GeminiLiveService(initial_fields=fields) as live:
            await live.send_audio(pcm_bytes)
            async for event in live.receive_events():
                ...
    """

    def __init__(self, initial_fields: dict | None = None) -> None:
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._model = settings.gemini_live_model_id
        self._fields: dict = dict(ALL_FIELDS)
        if initial_fields:
            self._fields.update({k: v for k, v in initial_fields.items() if k in self._fields})
        self._session: Any = None
        self._ctx: Any = None
        # Gemini Live emits CUMULATIVE usage_metadata per session; track the latest
        # and log the per-turn delta at turn_complete.
        self._usage_cum_prompt = 0
        self._usage_cum_response = 0
        self._usage_emitted_prompt = 0
        self._usage_emitted_response = 0

    async def __aenter__(self) -> GeminiLiveService:
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=types.Content(
                parts=[types.Part(text=_LIVE_SYSTEM_PROMPT)],
                role="user",
            ),
            tools=[types.Tool(function_declarations=[_UPDATE_FIELDS_DECLARATION])],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Aoede")
                )
            ),
        )
        self._ctx = self._client.aio.live.connect(model=self._model, config=config)
        self._session = await self._ctx.__aenter__()
        logger.info("gemini_live_connected model=%s", self._model)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._ctx is not None:
            try:
                await self._ctx.__aexit__(exc_type, exc_val, exc_tb)
            except Exception:
                logger.debug("gemini_live_close_error", exc_info=True)

    async def send_audio(self, pcm16_bytes: bytes) -> None:
        """Send a raw PCM16 16 kHz mono audio chunk to Gemini Live."""
        await self._session.send(
            input=types.LiveClientRealtimeInput(
                media_chunks=[types.Blob(data=pcm16_bytes, mime_type="audio/pcm;rate=16000")]
            )
        )

    async def receive_events(self) -> AsyncGenerator[dict, None]:
        """
        Yield structured events from Gemini Live:

        ``{"type": "audio", "data": bytes}``
            PCM16 audio to forward to the client (24 kHz).

        ``{"type": "fields_update", "fields": dict, "missing_fields": list, "completeness_score": float}``
            Emitted each time Gemini calls the ``update_fields`` tool.

        ``{"type": "turn_complete"}``
            Gemini finished a turn of speech.
        """
        async for msg in self._session.receive():
            # Usage telemetry — usage_metadata may arrive on any event and is
            # cumulative for the session; keep the latest read.
            _um = getattr(msg, "usage_metadata", None)
            if _um is not None:
                self._usage_cum_prompt = int(getattr(_um, "prompt_token_count", 0) or 0)
                self._usage_cum_response = int(
                    getattr(_um, "response_token_count", 0)
                    or getattr(_um, "candidates_token_count", 0)
                    or 0
                )

            if msg.server_content:
                sc = msg.server_content
                if sc.model_turn:
                    for part in sc.model_turn.parts:
                        if part.inline_data and part.inline_data.mime_type.startswith("audio"):
                            yield {"type": "audio", "data": part.inline_data.data}
                if sc.turn_complete:
                    # This turn's delta (cumulative minus what we already reported).
                    d_in = max(0, self._usage_cum_prompt - self._usage_emitted_prompt)
                    d_out = max(0, self._usage_cum_response - self._usage_emitted_response)
                    self._usage_emitted_prompt = self._usage_cum_prompt
                    self._usage_emitted_response = self._usage_cum_response
                    log_token_usage("voice_live", d_in, d_out)
                    yield {
                        "type": "turn_complete",
                        "token_usage": {
                            "input_tokens": d_in,
                            "output_tokens": d_out,
                            "total_tokens": d_in + d_out,
                        },
                    }

            if msg.tool_call:
                for fn_call in msg.tool_call.function_calls:
                    if fn_call.name != "update_fields":
                        continue

                    updates = dict(fn_call.args or {})
                    for key, value in updates.items():
                        if key in self._fields and value is not None:
                            self._fields[key] = value

                    # Mirror home address to service address if same
                    if self._fields.get("service_address_same") is True:
                        for sub in ("street", "state", "city", "zip"):
                            self._fields[f"service_address_{sub}"] = self._fields.get(
                                f"address_{sub}"
                            )

                    missing = _compute_missing(self._fields)
                    score = _compute_completeness(self._fields)

                    # Acknowledge the tool call so Gemini continues speaking
                    await self._session.send(
                        input=types.LiveClientToolResponse(
                            function_responses=[
                                types.FunctionResponse(
                                    id=fn_call.id,
                                    name="update_fields",
                                    response={"result": "ok", "missing_fields": missing},
                                )
                            ]
                        )
                    )

                    logger.info(
                        "live_fields_updated completeness=%.2f missing=%d",
                        score,
                        len(missing),
                    )
                    yield {
                        "type": "fields_update",
                        "fields": dict(self._fields),
                        "missing_fields": missing,
                        "completeness_score": score,
                    }

    @property
    def current_fields(self) -> dict:
        return dict(self._fields)
