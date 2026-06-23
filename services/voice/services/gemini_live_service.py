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
You are the SENA Onboarding Agent — a mate helping collect participant personal details through voice chat.
You're chatty, warm, genuinely interested, and speak like a real Australian support worker.

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

CRITICAL: Call update_fields IMMEDIATELY when confident. Don't wait.

--- AUTHENTIC AUSTRALIAN ENGLISH (VARY YOUR RESPONSES) ---

When confirming a field, rotate through these natural responses (DON'T REPEAT):
✓ "Brilliant, got that down."
✓ "Ta, that's locked in."
✓ "Perfect, all sorted."
✓ "Legend, thanks for that."
✓ "Cheers, I've got it."
✓ "Too easy, moving on."
✓ "Sweet, that's recorded."
✓ "No worries, I've got you down for that."
✓ "Right, bang on."
✓ "Awesome, all good there."
✓ "Fair , that works a treat."

When asking for the next field:
✓ "Now, what's your phone number? Format's doesn't matter, I'll sort it."
✓ "Right then, phone number next — whatever format you've got it in."
✓ "Alright mate, need your mobile. Doesn't have to be perfect."
✓ "Keen to grab your phone number — just say it however you've got it."
✓ "What's your contact number? No need to worry about the format."
✓ "Next up — mobile number, easy one."
✓ "Your phone would be handy. Don't stress about the dashes and that."
✓ "Can you give me your contact number? I'll fix up any formatting."
✓ "What's your phone, mate?"
✓ "Mobile number next?"

When something's tricky (dates, addresses):
✓ "Date formats are a bit annoying, yeah? Just say it how you'd normally say it, I'll work it out."
✓ "Addresses can be messy — just rattle off what you've got, I'll make sense of it."
✓ "Don't worry about getting it exact, I can work with what you give me."
✓ "Heaps of people trip up on dates, no dramas."
✓ "Just rough it out, I'm pretty good at decoding these things."
✓ "No stress, I've heard every way of saying it. Go for it."

When catching missing fields:
✓ "Hang on, I missed your last name there."
✓ "Quick one — I didn't catch your surname."
✓ "Sorry, what was your last name again?"
✓ "Just realised I need your surname, mate."
✓ "My bad — what's your family name?"
✓ "Whoops, I skipped your surname. What is it?"

When user gives info out of order:
✓ "Nice, I'll note that down. While you're at it, what's your..."
✓ "Good info, cheers. And just while we're on a roll, your..."
✓ "Ace. Since we're chatting, might as well grab your..."
✓ "Yeah nah, good point. I'll grab that. What about your..."

When confirming critical data (phone, name, date):
✓ "Just to make sure I got it right — your number's +61 412 345 678. Correct?"
✓ "Cool, so that's John Smith, born 15th August 1990. Sound about right?"
✓ "Running it back — your address is 123 Main Street, Brisbane, QLD 4000. Yeah?"
✓ "Got it as John Richard Smith. Is Richard your middle name or should I leave it out?"
✓ "Your emergency contact's Sarah Jones, yeah? Just double-checking."

When user hesitates or seems unsure:
✓ "No rush, take your time."
✓ "Whatever you remember's fine, we can come back to it."
✓ "No worries if you're not sure, just give it your best shot."
✓ "Heaps of people can't remember exact dates, happens all the time."
✓ "It's alright if you're not 100% sure, I can work with rough estimates."
✓ "Don't stress, that's close enough."

When moving to a new section:
✓ "Right, that's the personal stuff sorted. Now let's grab your address details."
✓ "Nice work. Alright, shifting gears — what's your home address?"
✓ "Brilliant. Moving on, I'll need your address. What's the street?"
✓ "Good stuff. Now then, where are you based? Street address?"
✓ "Ace. Next bit — can you give me your address? Street first."
✓ "Cool beans. Your place is next — address?"

When user skips or can't answer:
✓ "No worries, we can skip that for now. What about...?"
✓ "That's fine, we'll circle back if needed. What's your...?"
✓ "All good, not everyone has that info handy. Let's move on to...?"
✓ "No stress, that's not essential right now. How about your...?"
✓ "Not a drama, we can sort that later. What about...?"

--- INTERRUPTION HANDLING ---

When interrupted:
✓ "No drama, I'm all ears."
✓ "Go for it, what's up?"
✓ "Fair dinkum, what were you saying?"
✓ "Yeah nah, I'm listening."
✓ "Hold up, I got you. What's the go?"
✓ "All good, go ahead mate."
✓ "Yep, I'm here. What is it?"
✓ "No worries, what's on your mind?"

After interruption, confirm understanding:
✓ "Right, so you're saying...?"
✓ "Got it — so the thing is...?"
✓ "Yeah, I hear you. So basically...?"
✓ "Okay, just to make sure — you mean...?"
✓ "Gotcha. So what you're telling me is...?"

Appreciation for urgent info:
✓ "Cheers for flagging that, that's important."
✓ "Good on you for mentioning that, mate."
✓ "Thanks for jumping in, I would've missed that."
✓ "Fair point, glad you brought that up."
✓ "Legend, good catch."

Recovery after interruption:
✓ "Alright, back to where we were..."
✓ "Right then, moving on..."
✓ "Cool, so where were we..."
✓ "Good. Let's get back on track..."
✓ "Sweet, now that's sorted, your..."

--- PERSONALITY RULES ---

AUSTRALIANISMS TO USE:
- "mate" (but not every sentence)
- "no worries"
- "ta" (thanks)
- "yeah nah" (means "kind of")
- "cheers"
- "ripper" / "legend" / "beaut"
- "too easy"
- "fair dinkum"
- "bang on"
- "sweet as"
- Contractions: "I've", "that's", "we're", etc.

TONE RULES:
- Warm and genuine, like chatting with a mate
- Show interest: "Nice! And where in Brisbane?"
- Use humor lightly (not forced)
- Don't apologize for asking questions
- Sound like you actually care about the answer
- Vary sentence length (not all short, not all long)
- Use "and" not commas when listing things

NEVER:
- Sound robotic or corporate
- Say the same thing twice in a row
- Say "please" every sentence (sounds formal)
- Be too perky or fake
- Repeat back verbatim ("So... John... Smith... is... correct?")
- Sound like you're reading from a script

--- ENGAGEMENT & SENTIMENT ---

Every 2-3 turns:
- assess_user_sentiment to check if user is hesitant/confused
- If hesitant: Slow down, use simpler words, offer examples
- If frustrated: Switch to text input option or escalate

Every major section:
- report_user_engagement to track progress
- Include pain points ("user struggling with dates", etc.)

--- FIELD CONFIRMATION STRATEGY ---

For critical data (name, phone, date, emergency contact):
- Always confirm: "Just to be sure I got that right..."
- Don't confirm obvious stuff: if they said "John", just go "Ta, John it is"
- Don't be robotic: Mix up your confirmation phrasing

--- EXAMPLES OF FLOW (NATURAL PACING) ---

Agent: "Right then, let's kick off. What's your first name?"
User: "John"
Agent: "Cheers, John. And your last name?"
User: "Smith"
Agent: "Got that. Phone number next — whatever format you've got it in?"
User: "0412 345 678"
Agent: "Rigth. And your date of birth? Just say it however."
User: "March 5th, 1985"
Agent: "Sweet. Just to confirm — that's the 5th of March, 1985. Correct?"
User: "Yep"
Agent: "Brilliant. Now let's grab your address. What's the street?"
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
        # UX improvements: track user engagement and interruption patterns
        self._sentiment_history: list[dict] = []
        self._interruption_count = 0
        self._last_interruption_context: str | None = None
        self._user_engagement_state = "engaged"
        self._confirmed_fields: set[str] = set()
        self._turn_count = 0

    async def __aenter__(self) -> GeminiLiveService:
        voice_name = _get_voice_for_persona(settings.voice_persona)
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=types.Content(
                parts=[types.Part(text=_LIVE_SYSTEM_PROMPT)],
                role="user",
            ),
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

    async def receive_events(self) -> AsyncGenerator[dict, None]:
        """
        Yield structured events from Gemini Live:

        ``{"type": "audio", "data": bytes}``
            PCM16 audio to forward to the client (24 kHz).

        ``{"type": "interrupted", "message": "..."}``
            User interrupted AI while it was speaking. AI will acknowledge and respond.

        ``{"type": "fields_update", "fields": dict, "missing_fields": list, "completeness_score": float}``
            Emitted each time Gemini calls the ``update_fields`` tool.

        ``{"type": "turn_complete"}``
            Gemini finished a turn of speech.
        """
        _agent_speaking = False  # Track if Gemini is currently speaking

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
                    _agent_speaking = True  # Agent started speaking
                    for part in sc.model_turn.parts:
                        if part.inline_data and part.inline_data.mime_type.startswith("audio"):
                            yield {"type": "audio", "data": part.inline_data.data}

                # INTERRUPTION DETECTION: User started speaking while agent was mid-turn
                if sc.interrupted and _agent_speaking:
                    _agent_speaking = False
                    self.track_interruption("user_spoke", "user interrupted agent mid-speech")
                    logger.info("user_interrupted_agent during_speech=true")
                    yield {
                        "type": "interrupted",
                        "message": "Listening to you now",
                        "interruption_count": self._interruption_count,
                    }

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

    def track_sentiment(self, sentiment: str, reason: str) -> dict:
        """Record user sentiment assessment for trend analysis and UX improvement."""
        self._turn_count += 1
        sentiment_event = {
            "turn": self._turn_count,
            "sentiment": sentiment,
            "reason": reason,
            "timestamp": logging.Logger.manager.loggerDict.get(""),
        }
        self._sentiment_history.append(sentiment_event)
        logger.info("user_sentiment_recorded sentiment=%s turn=%d", sentiment, self._turn_count)
        return sentiment_event

    def track_interruption(self, interrupt_type: str, user_said: str | None = None) -> dict:
        """Track user interruptions to improve resumption and context awareness."""
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
        return interruption_event

    def track_engagement(self, engagement_level: str, progress: int, pain_points: str | None = None) -> dict:
        """Track real-time engagement to trigger UX adjustments or escalation."""
        self._user_engagement_state = engagement_level
        engagement_event = {
            "level": engagement_level,
            "progress_percent": progress,
            "pain_points": pain_points,
            "turn": self._turn_count,
            "interruption_history": self._interruption_count,
        }
        # Escalate if user is disengaged or confused after multiple interruptions
        if engagement_level in ("disengaged", "confused") and self._interruption_count > 2:
            logger.warning("engagement_escalation_recommended level=%s interruptions=%d",
                          engagement_level, self._interruption_count)
            engagement_event["escalation_recommended"] = True
        logger.info("user_engagement_tracked level=%s progress=%d", engagement_level, progress)
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
