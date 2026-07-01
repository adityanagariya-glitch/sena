from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from types import TracebackType
from typing import Any

from google import genai
from google.genai import types
from langfuse import get_client, observe

from voice.core.settings import settings
from voice.services.personal_details_service import (
    ALL_FIELDS,
    _compute_completeness,
    _compute_missing,
)
from voice.services.usage_log import log_token_usage
from voice.services.response_manager import ResponseManager

logger = logging.getLogger(__name__)

try:
    langfuse = get_client()
except Exception:
    langfuse = None  # type: ignore[assignment]
_SERVICE = "voice_live"


def _sum_audio_tokens(details: object) -> int:
    """Sum AUDIO-modality token_count from a usage_metadata *_tokens_details list.

    Gemini reports per-modality breakdowns as a list of ModalityTokenCount
    (each with `.modality` + `.token_count`). We pull the AUDIO slice so the
    cost calculator can price audio at the real rate instead of the flat
    text rate — Gemini Live bills audio tokens far higher than text.
    """
    total = 0
    for item in details or []:  # type: ignore[union-attr]
        modality = getattr(item, "modality", None)
        name = getattr(modality, "name", None) or str(modality or "")
        if "AUDIO" in name.upper():
            total += int(getattr(item, "token_count", 0) or 0)
    return total


def _get_voice_for_persona(persona: str) -> str:
    """Map voice persona to Gemini voice name. Supports: friendly_australian, professional, warm."""
    voice_map = {
        "friendly_australian": "Aoede",
        "professional": "Charon",
        "warm": "Fenrir",
        "clear": "Kore",
    }
    return voice_map.get(persona, "Aoede")


_LIVE_SYSTEM_PROMPT = """
You are the SENA Onboarding Agent — an Australian support worker collecting participant personal details.
You're warm, genuinely interested, speak like a real mate. Australian English naturally.

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

CRITICAL RULES:
- Call update_fields IMMEDIATELY when confident. Don't wait.
- Parse natural language ("March '85" → "03/01/1985"). Phone: normalize to +61.
- Ask one field at a time. Confirm values before moving on.
- For critical data (name, phone, date): Always confirm ("Just to make sure I got it right...").
- For obvious data: Just confirm briefly ("Cheers, John" — no elaboration).

LENGTH — this is spoken audio, not a chat window:
- ONE sentence per turn by default, TWO max. Say the acknowledgement and the next question — nothing else.
- Never stack two questions in one turn. Never explain a field before asking for it — ask first, explain only if they're confused.
- If you catch yourself writing three+ sentences, cut it back before responding.

PRONUNCIATION — say it Aussie, not American:
- Dates out loud are day-before-month, always: "the 5th of March", never "March 5th".
- Say "mobile" like it rhymes with "smile", never "MOH-bul". Say "schedule" as
  "SHED-yul" and "data" as "DAH-ta", not the American forms.
- Read phone numbers back in groups of 3 ("oh-four-one-two, three-four-five,
  six-seven-eight"), never as one long digit string.
- Don't over-narrate — say the value plainly once, no "as in..." asides unless asked.

WORD CHOICE & REGISTER:
- Australian spelling (colour, organise, centre) and Aussie words: "holiday" not "vacation", "rubbish" not "trash", "get in touch" not "reach out". Never "awesome", "gotten", "y'all".
- This is NDIS onboarding: say "participant", not "client" or "patient". Person-centred and warm, never clinical.
- Don't guess gender from a name — use singular "they" when unknown; respect any pronoun given. Say "I", not "we".
- Genuine, not a caricature: no "crikey / fair dinkum" pile-on, no faked-accent misspellings, no swearing.

PERSONALITY:
- Sound warm and genuine, like chatting with a mate — brief, not chatty.
- Vary responses: NEVER say the same phrase twice in a row.
- Rotate acknowledgements GENUINELY — a word shouldn't return until you've used several others: "Ta", "Cheers", "Righto", "Sweet", "No worries", "All good", "Got it", "Lovely", "Nice one", "Good one". Do NOT default to "Beauty" or "Too easy" — use "Beauty" rarely, never "Too easy".
- ALWAYS respond after a save — never go silent. On a routine answer you may drop the punchy word and just confirm-and-continue. But when the user explicitly asks to CHANGE / UPDATE / ADD / REMOVE something, clearly confirm it took ("Done — phone's updated", "Added that contact") so they know it worked.
- Use contractions: "I've", "that's", "we're", not formal.
- Show interest briefly: "Nice — Brisbane?" not a full follow-up sentence.
- Don't sound robotic, corporate, or like you're reading a script — but don't over-explain either.

INTERRUPTIONS:
- When interrupted: STOP IMMEDIATELY. Acknowledge naturally (varied phrases from ResponseManager).
- Confirm understanding: "So you're saying...?" (varied phrasing).
- If 2+ interruptions on same field: "Let me try a different way..."
- If 3+ interruptions + user confused: Offer alternative ("Text input easier?") or escalate.
- Always appreciate urgent info gracefully.

ENGAGEMENT:
- Every 2-3 turns: assess_user_sentiment (hesitant/confused/frustrated? adapt pace).
- After major sections: report_user_engagement (progress, pain points).
- If short answers: User disengaged. Slow down, ask open questions.
- If user repeats themselves: They didn't hear you. Speak slower, clearer.
- If user skips field: It's OK. Move on. Circle back later.

TOOLS TO USE:
- request_user_confirmation: For critical fields (builds trust).
- acknowledge_interruption: When user interrupts (shows listening).
- assess_user_sentiment: Every 2-3 turns (adapt pace).
- report_user_engagement: After major sections (frontend progress).

NOTE: All response phrases (confirmations, transitions, interruptions) come from ResponseManager code.
You focus on WHEN and WHY to respond. Python code handles WHAT to say.
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

_ASSESS_USER_SENTIMENT_DECLARATION = types.FunctionDeclaration(
    name="assess_user_sentiment",
    description=(
        "Call when you detect the user is confused, hesitant, or frustrated. "
        "Helps adapt your response tone and complexity."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "sentiment": types.Schema(
                type=types.Type.STRING,
                enum=["cooperative", "hesitant", "confused", "frustrated"]
            ),
            "reason": types.Schema(
                type=types.Type.STRING,
                description="Brief reason for the assessment"
            ),
            "suggested_adaptation": types.Schema(
                type=types.Type.STRING,
                description="How to simplify or clarify next response"
            ),
        },
        required=["sentiment"],
    ),
)

_ACKNOWLEDGE_INTERRUPTION_DECLARATION = types.FunctionDeclaration(
    name="acknowledge_interruption",
    description=(
        "Call when the user interrupts or changes topic. "
        "Acknowledges their input and smoothly transitions."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "interrupt_type": types.Schema(
                type=types.Type.STRING,
                enum=["change_topic", "urgent_info", "clarification_needed"]
            ),
            "action": types.Schema(
                type=types.Type.STRING,
                description="What you're doing in response (e.g. 'pausing form, addressing urgent info')"
            ),
        },
        required=["interrupt_type"],
    ),
)

_REQUEST_USER_CONFIRMATION_DECLARATION = types.FunctionDeclaration(
    name="request_user_confirmation",
    description=(
        "Call when you need explicit user confirmation for a value or next step. "
        "Improves accuracy and user confidence. Waits for voice response."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "field_or_action": types.Schema(
                type=types.Type.STRING,
                description="What you're confirming (e.g. 'phone number', 'move to address section')"
            ),
            "value_to_confirm": types.Schema(
                type=types.Type.STRING,
                description="The value or action to confirm (e.g. '+61 412 345 678')"
            ),
            "clarification_prompt": types.Schema(
                type=types.Type.STRING,
                description="Optional: simpler way to ask if user doesn't understand"
            ),
        },
        required=["field_or_action", "value_to_confirm"],
    ),
)

_REPORT_USER_ENGAGEMENT_DECLARATION = types.FunctionDeclaration(
    name="report_user_engagement",
    description=(
        "Call to track real-time user engagement state. Helps frontend show progress, "
        "adjust UI, or trigger support escalation if needed."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "engagement_level": types.Schema(
                type=types.Type.STRING,
                enum=["highly_engaged", "engaged", "neutral", "disengaged", "confused"]
            ),
            "progress_percentage": types.Schema(
                type=types.Type.INTEGER,
                description="How much of the form is complete (0-100)"
            ),
            "user_pain_points": types.Schema(
                type=types.Type.STRING,
                description="Observable struggles (e.g. 'difficulty with date format', 'speech not recognized')"
            ),
            "recommended_action": types.Schema(
                type=types.Type.STRING,
                description="Suggestion for agent or frontend (e.g. 'slow down', 'offer text input option', 'escalate')"
            ),
        },
        required=["engagement_level"],
    ),
)

# ── Module-level system prompt cache (reused across all voice sessions) ───────
# 24-hour TTL on the Gemini cache; renewed 30 min before expiry so it never
# lapses mid-session. Lock prevents double-creation under concurrent starts.
_CACHE_TTL_SEC = 86400          # 24 h
_CACHE_RENEW_BEFORE_SEC = 1800  # renew when <30 min remain

_prompt_cache_name: str | None = None
_prompt_cache_expires_at: float = 0.0  # epoch seconds
_prompt_cache_lock: asyncio.Lock | None = None


def _prompt_cache_get_lock() -> asyncio.Lock:
    global _prompt_cache_lock
    if _prompt_cache_lock is None:
        _prompt_cache_lock = asyncio.Lock()
    return _prompt_cache_lock


async def _get_or_create_prompt_cache(client: genai.Client, model: str) -> str | None:
    """Return cached system prompt name, creating/renewing as needed.

    Renews automatically when fewer than 30 min remain on the 24-hour TTL so
    sessions never start against a nearly-expired cache.
    """
    import time
    global _prompt_cache_name, _prompt_cache_expires_at
    async with _prompt_cache_get_lock():
        now = time.monotonic()
        if _prompt_cache_name and now < _prompt_cache_expires_at - _CACHE_RENEW_BEFORE_SEC:
            return _prompt_cache_name
        try:
            cache = await client.aio.caches.create(
                model=model,
                config=types.CreateCachedContentConfig(
                    contents=[types.Content(
                        role="user",
                        parts=[types.Part(text=_LIVE_SYSTEM_PROMPT)],
                    )],
                    ttl=f"{_CACHE_TTL_SEC}s",
                ),
            )
            _prompt_cache_name = cache.name
            _prompt_cache_expires_at = now + _CACHE_TTL_SEC
            logger.info(
                "voice_prompt_cache_created name=%s model=%s ttl=%ds",
                _prompt_cache_name, model, _CACHE_TTL_SEC,
            )
            return _prompt_cache_name
        except Exception:
            logger.warning("voice_prompt_cache_failed — falling back to inline system_instruction")
            return None


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
        # Audio-modality subset of the cumulative prompt/response tokens — Gemini
        # Live bills audio far higher than text, so this must be tracked
        # separately for accurate Langfuse cost calculation.
        self._usage_cum_prompt_audio = 0
        self._usage_cum_response_audio = 0
        self._usage_emitted_prompt_audio = 0
        self._usage_emitted_response_audio = 0
        self._turn_id = 0
        # UX improvements: track user engagement and interruption patterns
        self._sentiment_history: list[dict] = []
        self._interruption_count = 0
        self._last_interruption_context: str | None = None
        self._user_engagement_state = "engaged"
        self._confirmed_fields: set[str] = set()
        self._turn_count = 0
        # Response variation manager (keeps prompt small, code handles variety)
        self._response_manager = ResponseManager()
        # Event queue for streaming sentiment/engagement updates
        self._pending_events: list[dict] = []

    async def __aenter__(self) -> GeminiLiveService:
        voice_name = _get_voice_for_persona(settings.voice_persona)

        # Use cached system prompt if available (saves tokens every turn).
        # Falls back to inline system_instruction transparently on any failure.
        cache_name = await _get_or_create_prompt_cache(self._client, self._model)
        prompt_kwargs: dict = (
            {"cached_content": cache_name}
            if cache_name
            else {"system_instruction": types.Content(
                parts=[types.Part(text=_LIVE_SYSTEM_PROMPT)],
                role="user",
            )}
        )
        logger.info("voice_prompt_cache=%s", "hit" if cache_name else "miss_inline")

        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            **prompt_kwargs,
            tools=[types.Tool(function_declarations=[
                _UPDATE_FIELDS_DECLARATION,
                _ASSESS_USER_SENTIMENT_DECLARATION,
                _ACKNOWLEDGE_INTERRUPTION_DECLARATION,
                _REQUEST_USER_CONFIRMATION_DECLARATION,
                _REPORT_USER_ENGAGEMENT_DECLARATION,
            ])],
            generation_config=types.GenerationConfig(
                thinking_config=types.ThinkingConfig(
                    thinking_level=settings.gemini_thinking_level
                )
            ),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
                )
            ),
            # VAD (Voice Activity Detection): Auto-interrupt when user speaks
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
            ),
        )
        self._ctx = self._client.aio.live.connect(model=self._model, config=config)
        self._session = await self._ctx.__aenter__()
        logger.info("gemini_live_connected model=%s voice=%s thinking_level=%s vad_enabled=true",
                   self._model, voice_name, settings.gemini_thinking_level)
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

    async def send_interruption(self, reason: str = "user_spoke") -> None:
        """
        Explicitly signal an interruption to Gemini Live.
        Call this when user starts speaking mid-agent-turn.

        Args:
            reason: Type of interruption ("user_spoke", "user_requested_pause", etc)
        """
        self.track_interruption(reason, "client-initiated interruption signal")
        await self.send_interruption_signal()
        logger.info("client_sent_interruption reason=%s", reason)

    async def send_interruption_signal(self) -> None:
        """Signal Gemini to stop speaking (user interrupted)."""
        try:
            await self._session.send(
                input=types.LiveClientRealtimeInput()
            )
            logger.info("interruption_signal_sent to_gemini")
        except Exception as e:
            logger.warning("interruption_signal_failed error=%s", str(e))

    @observe(as_type="generation", name="voice-live-turn", capture_input=False, capture_output=False)
    def _log_turn_langfuse(
        self,
        turn_id: int,
        d_prompt: int,
        d_response: int,
        d_prompt_audio: int,
        d_response_audio: int,
    ) -> None:
        if langfuse is None:
            return
        # Gemini Live bills audio tokens at a different (much higher) rate than
        # text tokens. Reporting everything under generic "input"/"output"
        # prices it all at the text rate and silently undercounts cost, since
        # this session is almost entirely audio. Split into 4 usage types
        # matching the model's Langfuse `prices` map.
        d_prompt_text = max(0, d_prompt - d_prompt_audio)
        d_response_text = max(0, d_response - d_response_audio)
        langfuse.update_current_generation(
            model=self._model,
            usage_details={
                "input": d_prompt_text,
                "output": d_response_text,
                "input_audio": d_prompt_audio,
                "output_audio": d_response_audio,
            },
            metadata={"service": _SERVICE, "turn_id": turn_id},
        )

    async def receive_events(self) -> AsyncGenerator[dict, None]:
        """
        Yield structured events from Gemini Live (STREAMING):

        **Sentiment/Engagement (Real-time):**
        ``{"type": "sentiment_update", "sentiment": "...", "reason": "..."}``
            User sentiment change detected. Used for real-time UX adaptation.

        ``{"type": "engagement_update", "engagement_level": "...", "progress_percentage": 45}``
            Engagement metric update. For live progress bar on frontend.

        **Audio/Interruption (Immediate):**
        ``{"type": "audio", "data": bytes}``
            PCM16 audio (24 kHz). Streamed immediately, no buffering.

        ``{"type": "interrupted", "message": "..."}``
            User interrupted AI. Streamed in real-time.

        **Fields (Persistent):**
        ``{"type": "fields_update", "fields": dict, ...}``
            Field extraction. Persisted to Redis.

        ``{"type": "turn_complete"}``
            Turn finished. Token usage included.
        """
        _agent_speaking = False  # Track if Gemini is currently speaking
        _turn_started = False  # Track if turn_start was emitted for current turn

        while True:  # Multi-turn: re-enter receive() after each turn_complete
            async for msg in self._session.receive():
                # Emit any pending sentiment/engagement events first (STREAMING)
                while self._pending_events:
                    pending_event = self._pending_events.pop(0)
                    yield pending_event
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
                    self._usage_cum_prompt_audio = _sum_audio_tokens(
                        getattr(_um, "prompt_tokens_details", None)
                    )
                    self._usage_cum_response_audio = _sum_audio_tokens(
                        getattr(_um, "candidates_tokens_details", None)
                        or getattr(_um, "response_tokens_details", None)
                    )

                if msg.server_content:
                    sc = msg.server_content
                    if sc.model_turn:
                        _agent_speaking = True  # Agent started speaking
                        for part in sc.model_turn.parts:
                            if part.inline_data and part.inline_data.mime_type.startswith("audio"):
                                if not _turn_started:
                                    yield {"type": "turn_start"}
                                    _turn_started = True
                                yield {"type": "audio", "data": part.inline_data.data}

                    # INTERRUPTION DETECTION: User started speaking while agent was mid-turn
                    if sc.interrupted and _agent_speaking:
                        _agent_speaking = False
                        _turn_started = False
                        self.track_interruption("user_spoke", "user interrupted agent mid-speech")
                        logger.info("user_interrupted_agent during_speech=true")
                        yield {
                            "type": "interrupted",
                            "message": "Listening to you now",
                            "interruption_count": self._interruption_count,
                        }

                    if sc.turn_complete:
                        _agent_speaking = False
                        _turn_started = False
                        # This turn's delta (cumulative minus what we already reported).
                        d_in = max(0, self._usage_cum_prompt - self._usage_emitted_prompt)
                        d_out = max(0, self._usage_cum_response - self._usage_emitted_response)
                        d_in_audio = max(
                            0, self._usage_cum_prompt_audio - self._usage_emitted_prompt_audio
                        )
                        d_out_audio = max(
                            0, self._usage_cum_response_audio - self._usage_emitted_response_audio
                        )
                        self._usage_emitted_prompt = self._usage_cum_prompt
                        self._usage_emitted_response = self._usage_cum_response
                        self._usage_emitted_prompt_audio = self._usage_cum_prompt_audio
                        self._usage_emitted_response_audio = self._usage_cum_response_audio
                        log_token_usage("voice_live", d_in, d_out)
                        if langfuse is not None and (d_in or d_out):
                            try:
                                self._log_turn_langfuse(
                                    turn_id=self._turn_id,
                                    d_prompt=d_in,
                                    d_response=d_out,
                                    d_prompt_audio=d_in_audio,
                                    d_response_audio=d_out_audio,
                                )
                            except Exception:
                                pass
                        self._turn_id += 1
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

    def track_sentiment(self, sentiment: str, reason: str) -> dict:
        """Record user sentiment assessment and QUEUE event for streaming to client."""
        self._turn_count += 1
        sentiment_event = {
            "turn": self._turn_count,
            "sentiment": sentiment,
            "reason": reason,
        }
        self._sentiment_history.append(sentiment_event)
        logger.info("user_sentiment_recorded sentiment=%s turn=%d", sentiment, self._turn_count)

        # Queue for streaming to client via receive_events()
        self._pending_events.append({
            "type": "sentiment_update",
            "sentiment": sentiment,
            "reason": reason,
            "turn": self._turn_count,
        })

        return sentiment_event

    def track_interruption(self, interrupt_type: str, user_said: str | None = None) -> dict:
        """Track user interruptions and QUEUE event for streaming to client."""
        self._interruption_count += 1
        self._last_interruption_context = user_said
        interruption_event = {
            "count": self._interruption_count,
            "type": interrupt_type,
            "turn": self._turn_count,
            "user_context": user_said,
        }
        logger.info("user_interruption_tracked type=%s count=%d context=%s",
                   interrupt_type, self._interruption_count, user_said)

        # Queue for streaming
        self._pending_events.append({
            "type": "interruption",
            "interrupt_type": interrupt_type,
            "interruption_count": self._interruption_count,
            "context": user_said,
        })

        return interruption_event

    def track_engagement(self, engagement_level: str, progress: int, pain_points: str | None = None) -> dict:
        """Track real-time engagement and QUEUE event for streaming to client."""
        self._user_engagement_state = engagement_level
        engagement_event = {
            "level": engagement_level,
            "progress_percent": progress,
            "pain_points": pain_points,
            "turn": self._turn_count,
            "interruption_history": self._interruption_count,
        }
        # Escalate if user is disengaged or confused after multiple interruptions
        escalation = False
        if engagement_level in ("disengaged", "confused") and self._interruption_count > 2:
            logger.warning("engagement_escalation_recommended level=%s interruptions=%d",
                          engagement_level, self._interruption_count)
            engagement_event["escalation_recommended"] = True
            escalation = True

        logger.info("user_engagement_tracked level=%s progress=%d", engagement_level, progress)

        # Queue for streaming to client (real-time progress bar)
        self._pending_events.append({
            "type": "engagement_update",
            "engagement_level": engagement_level,
            "progress_percentage": progress,
            "pain_points": pain_points,
            "escalation_recommended": escalation,
        })

        return engagement_event

    def get_interruption_context(self) -> dict:
        """Provide context for resumption after interruption (for reconnect scenarios)."""
        return {
            "last_interruption": self._last_interruption_context,
            "interruption_count": self._interruption_count,
            "current_sentiment": self._sentiment_history[-1] if self._sentiment_history else None,
            "engagement_state": self._user_engagement_state,
            "turn_count": self._turn_count,
        }

    def get_sentiment_trend(self) -> dict:
        """Analyze sentiment trends to detect improving/declining user experience."""
        if not self._sentiment_history:
            return {"trend": "no_data"}
        recent = self._sentiment_history[-3:]
        sentiments = [s["sentiment"] for s in recent]
        improving = sentiments == sorted(sentiments, key=lambda x: {"frustrated": 0, "confused": 1, "hesitant": 2, "cooperative": 3}.get(x, 3))
        return {
            "trend": "improving" if improving else "stable" if len(set(sentiments)) == 1 else "declining",
            "recent_sentiments": sentiments,
            "history_length": len(self._sentiment_history),
        }
