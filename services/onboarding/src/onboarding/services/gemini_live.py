"""
Gemini Live session wrapper for the onboarding WebSocket endpoint.

Ported from sena-ai/demo_live_server.py and extended with:
  - Structured JSON events emitted to the app WS (user_said, agent_said,
    turn_start, turn_complete, interrupted)
  - Transcript persistence to Redis on every speaker turn
  - text input: user_text WS message → send_realtime_input(text=...)
  - audio_end: flushes cached audio → send_realtime_input(audio_stream_end=True)

Audio formats:
  In  — raw PCM16, little-endian, 16 kHz mono  (MIME: audio/pcm;rate=16000)
  Out — raw PCM16, little-endian, 24 kHz mono  (client upsamples if needed)

Key implementation notes:
  - send_realtime_input(audio=Blob(...))  NOT the old session.send() path
  - session.receive() returns per-turn; wrap in `while True: ... continue`
    to handle subsequent turns without reopening the Gemini connection
  - No proactive audio on gemini-3.1-flash-live-preview; greeting fires on
    the user's first utterance (system prompt handles the wording)
"""
<<<<<<< HEAD

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
=======
from __future__ import annotations

import asyncio
import json
import logging
>>>>>>> ai-chatbot
import time
from typing import TYPE_CHECKING

from fastapi import WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types

from onboarding.core.settings import settings
from onboarding.services.grounding import build_live_tools
from onboarding.services.screen_context import (
    ScreenStateMessage,
    ScreenStateV2Message,
    from_v1,
    payload_hash,
    render_injection_text,
)
<<<<<<< HEAD
from onboarding.services.tools import FUNCTION_DECLS

# Phase 1 telemetry — opt-in by install. If sena_common isn't on the import
# path (e.g. shared/ hasn't been pip-installed editable into the venv), fall
# back to a no-op stub. AI critical path NEVER fails due to telemetry.
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


def _sum_audio_tokens(details: object) -> int:
    """Sum AUDIO-modality token_count from a usage_metadata *_tokens_details list.

    Gemini reports per-modality breakdowns as a list of ModalityTokenCount
    (each with `.modality` + `.token_count`). We pull the AUDIO slice so the
    cost calculator can price audio at the real rate instead of the 90/10
    heuristic. Returns 0 for None / text-only responses.
    """
    total = 0
    for item in details or []:  # type: ignore[union-attr]
        modality = getattr(item, "modality", None)
        name = getattr(modality, "name", None) or str(modality or "")
        if "AUDIO" in name.upper():
            total += int(getattr(item, "token_count", 0) or 0)
    return total


if TYPE_CHECKING:
    from onboarding.models.turn_payload import TurnPayload
    from onboarding.repositories.state_repo import FormStateRepo
    from onboarding.services.mobile_bridge import MobileBridge
    from onboarding.services.tools import ToolDispatcher

import structlog

log = structlog.get_logger(__name__)

_SILENCE_POLL_SEC = 2.0  # silence monitor check interval

#: Exception class names that mean "the client/WS went away" rather than a
#: server fault. The Flutter client dropping the WS (mobile network, app
#: backgrounded) surfaces as one of these across the starlette / uvicorn /
#: websockets stack. We log them at info, never as a noisy traceback.
_DISCONNECT_EXC_NAMES = frozenset(
    {
        "WebSocketDisconnect",
        "ClientDisconnected",
        "ConnectionClosed",
        "ConnectionClosedOK",
        "ConnectionClosedError",
    }
)


def _is_client_disconnect(exc: BaseException) -> bool:
    """True when `exc` is a normal client/WS teardown, not a server fault."""
    if type(exc).__name__ in _DISCONNECT_EXC_NAMES:
        return True
    return isinstance(exc, RuntimeError) and "close message has been sent" in str(exc)

=======
from onboarding.services.tools import FUNCTION_DECLS, POLICY_BLOCK_DECL, PolicyBlockSignal

if TYPE_CHECKING:
    from onboarding.repositories.state_repo import FormStateRepo
    from onboarding.services.tools import ToolDispatcher

log = logging.getLogger(__name__)

_SILENCE_POLL_SEC = 2.0  # silence monitor check interval

>>>>>>> ai-chatbot

class GeminiLiveSession:
    """
    Bridges a single Gemini Live connection to an app/browser WebSocket.

    Lifecycle:
      1. Caller awaits run()
      2. run() opens the Gemini connection, starts b2g + g2b tasks
      3. Blocks on b2g — returns when client disconnects or sends {"type":"stop"}
      4. Cancels g2b, cleans up

    The WS lock is NOT managed here — ws_routes.py acquires/releases it.
    """

    def __init__(
        self,
        websocket: WebSocket,
        session_id: str,
        system_instruction: str,
<<<<<<< HEAD
        repo: FormStateRepo,
        tool_dispatcher: ToolDispatcher | None = None,
        replay_context: str | None = None,
        mobile_bridge: MobileBridge | None = None,
        initial_state_text: str | None = None,
        *,
        tenant_id: str | None = None,
        user_id: str | None = None,
        participant_id: str | None = None,
=======
        repo: "FormStateRepo",
        tool_dispatcher: "ToolDispatcher | None" = None,
        replay_context: str | None = None,
>>>>>>> ai-chatbot
    ) -> None:
        self._ws = websocket
        self._session_id = session_id
        self._system_instruction = system_instruction
        self._repo = repo
        self._tools = tool_dispatcher
        self._replay_context = replay_context
<<<<<<< HEAD
        self._mobile_bridge = mobile_bridge
        # Phase 1.5 — auth context for per-turn usage logging. Sourced from
        # FormState at WS bootstrap (which itself was populated by the route
        # handler from the auth headers, NOT from request body). Falls back to
        # "unknown" only when the upstream tenant_id is empty so we never lose
        # the cost — but logs surface "unknown" as a queryable bucket, making
        # untenanted sessions easy to grep for and fix.
        self._tenant_id = tenant_id
        self._user_id = user_id
        self._participant_id = participant_id
        # Hidden text turn injected at session open so the model greets from the
        # REAL screen state without the participant having to say "these are
        # already filled" and without waiting for a get_current_state round-trip.
        self._initial_state_text = initial_state_text
        self._current_turn: TurnPayload | None = None
=======
>>>>>>> ai-chatbot
        self._turn_id = 0
        self._last_screen_hash: str | None = None
        self._last_audio_at: float = 0.0
        self._gemini_is_speaking: bool = False
<<<<<<< HEAD
        # Kickoff audio-suppression shield. gemini-3.1-flash-live-preview has a
        # known VAD bug: if the participant talks over the model's OPENING
        # greeting, the interrupt cancels turn 0 with zero output chunks and the
        # VAD then wedges — it stops emitting input_transcription for the rest of
        # the session (cookbook issue #1197). Workaround: DROP every inbound mic
        # frame from session open until the FIRST agent turn fully completes
        # (turn_complete with audio). A short timed window was not enough — the
        # barge-in frames arrive BEFORE the first model audio (before any timer
        # could arm), so we gate on turn completion instead of a clock.
        # True = still in the opening, suppress mic. Flipped False on first
        # real turn_complete (chunks > 0). A trailing grace timer also clears it
        # in case the opener produces no audio at all.
        self._kickoff_shield_active: bool = True
        self._kickoff_grace_until: float = 0.0
=======
>>>>>>> ai-chatbot
        # Voice protocol — preserve the words Gemini was saying when interrupted
        # so the next turn can address the interruption AND the unfinished thought.
        # Injected as a hidden [INTERRUPTED] text turn right after the cut-off.
        self._last_interrupted_intent: str | None = None
        # Silence watchdog — two-step protocol. _silence_warned flips True after
        # the first "still there?" check-in; the second timeout then summarises
        # pending fields. Reset to False on any new user audio.
        self._silence_warned: bool = False
<<<<<<< HEAD
        # Set True after the summary step fires; no further watchdog cues until
        # a real user utterance arrives. Prevents the "keeps speaking" loop.
        self._silence_exhausted: bool = False
        # Phase 1 usage logging — Gemini Live emits cumulative usage_metadata
        # on receive events. Track last-emitted-cumulative so each turn_complete
        # logs only its DELTA (the per-turn token cost). Cumulative-to-delta
        # math is correct even if some events arrive without metadata.
        self._usage_emitted_prompt: int = 0
        self._usage_emitted_response: int = 0
        self._usage_emitted_cached: int = 0
        self._usage_emitted_prompt_audio: int = 0
        self._usage_emitted_response_audio: int = 0
        # Latest cumulative read from msg.usage_metadata — updated on EVERY
        # receive event that carries one. Read at turn_complete time.
        self._usage_cum_prompt: int = 0
        self._usage_cum_response: int = 0
        self._usage_cum_cached: int = 0
        # Audio-modality subset of the cumulative prompt/response tokens, summed
        # from usage_metadata.*_tokens_details. Lets the cost calculator price
        # audio at the real rate instead of the 90/10 heuristic (Phase 1.6).
        self._usage_cum_prompt_audio: int = 0
        self._usage_cum_response_audio: int = 0
        self._tool_calls_in_turn: int = 0
        # Diagnostic — proves the system_instruction is unique per session.
        # If two consecutive sessions log the same sha8, the prompt builder
        # is leaking state across requests; that would be the cross-screen
        # leak source. SHA-only — full prompt never hits the log.
        _instruction_sha8 = hashlib.sha256(system_instruction.encode("utf-8")).hexdigest()[:8]
        log.info(
            "gemini_bridge_constructed session=%s system_instruction_sha8=%s "
            "instruction_chars=%d tools_count=%d replay_context=%s",
            session_id,
            _instruction_sha8,
            len(system_instruction),
            (len(FUNCTION_DECLS) if tool_dispatcher else 0),
            ("yes" if replay_context else "no"),
        )
=======
>>>>>>> ai-chatbot

    # ── Public ────────────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Open Gemini connection and bridge until the client disconnects."""
        client = genai.Client(api_key=settings.gemini_api_key)

        # Long-session compression — official Gemini Live mechanism for sessions
        # that would otherwise exceed the model's native window. Sliding window
        # automatically drops the oldest turns when the context approaches the
        # limit, so a 20-minute onboarding doesn't drop with a token error.
        # Verified against /googleapis/js-genai (Context7) — first-class
        # LiveConnectConfig property.
        compression_cfg = None
        try:
<<<<<<< HEAD
            # Option D Layer 3 — aggressive sliding-window compression so
            # stale conversational drift gets summarised away faster, leaving
            # recent function_response.state payloads to dominate the model's
            # attention. 4000 tokens ≈ 5–7 min of voice — long enough to keep
            # recent exchanges, short enough to evict stale drift fast.
            # See .claude/plans/per-screen-session-model/ISSUE_AND_SOLUTION.md §7.12.
            compression_cfg = types.ContextWindowCompressionConfig(
                sliding_window=types.SlidingWindow(target_tokens=4000)
=======
            compression_cfg = types.ContextWindowCompressionConfig(
                sliding_window=types.SlidingWindow()
>>>>>>> ai-chatbot
            )
        except (AttributeError, TypeError):
            # SDK older than the compression types — keep going without it.
            log.warning(
                "context_window_compression unavailable in this SDK version "
                "session=%s — long sessions may hit token limits",
                self._session_id,
            )

        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=types.Content(
                parts=[types.Part(text=self._system_instruction)],
            ),
            **({"context_window_compression": compression_cfg} if compression_cfg else {}),
            # language_code="en-AU" sets TTS accent to Australian English (SDK >= 1.10).
            # voice_name="Aoede" pins ASR to English so the native-audio model does not
            # auto-detect language from quiet/ambiguous first audio (was transcribing as
            # Japanese "はい" without this pin).
            speech_config=types.SpeechConfig(
                language_code="en-AU",
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Aoede")
                ),
            ),
            # Phase C/E — tool list built by grounding module; includes Google Search
            # when SENA_AI_ONBOARDING_GROUNDING_ENABLED=true (default off).
            tools=build_live_tools(
<<<<<<< HEAD
                FUNCTION_DECLS,
                grounding_enabled=settings.onboarding_grounding_enabled,
            )
            if self._tools
            else None,
=======
                FUNCTION_DECLS if settings.onboarding_grounding_enabled
                else [*FUNCTION_DECLS, POLICY_BLOCK_DECL],
                grounding_enabled=settings.onboarding_grounding_enabled,
            ) if self._tools else None,
>>>>>>> ai-chatbot
            # Multi-turn REQUIRES explicit realtime_input_config with VAD.
            # Without it the receive() iterator exits after the first turn and
            # the session silently stops processing audio.
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    disabled=False,
                    # LOW for both = patient listening. NDIS participants with
                    # cognitive/communication support needs pause mid-answer;
                    # HIGH end-sensitivity + short silence cuts them off and
                    # makes Gemini call update_field with partial answers.
                    start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_LOW,
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
                    prefix_padding_ms=200,
<<<<<<< HEAD
                    # 3 s — NDIS participants with cognitive/communication
                    # support needs often pause 2-3 s mid-answer; 1 s cut them
                    # off prematurely (user-reported: "had to ask AI to take
                    # its time"). 3 s matches the upper end of natural
                    # conversational pause without making the session feel stuck.
                    silence_duration_ms=3000,
=======
                    silence_duration_ms=1000,
>>>>>>> ai-chatbot
                ),
                activity_handling=types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
                turn_coverage=types.TurnCoverage.TURN_INCLUDES_ONLY_ACTIVITY,
            ),
<<<<<<< HEAD
=======
            session_resumption=types.SessionResumptionConfig(handle=None),
>>>>>>> ai-chatbot
            output_audio_transcription=types.AudioTranscriptionConfig(),
            input_audio_transcription=types.AudioTranscriptionConfig(),
        )

        async with client.aio.live.connect(
            model=settings.gemini_live_model_id, config=config
        ) as session:
<<<<<<< HEAD
            log.info(
                "gemini_connected session=%s model=%s",
                self._session_id,
                settings.gemini_live_model_id,
            )
=======
            log.info("gemini_connected session=%s model=%s", self._session_id, settings.gemini_live_model_id)
>>>>>>> ai-chatbot
            # Phase E — inject replay context so model continues without reintroducing
            if self._replay_context:
                await session.send_realtime_input(text=self._replay_context)
                log.debug("replay_context_injected session=%s", self._session_id)
<<<<<<< HEAD
            # Seed the live screen state as a hidden context turn so the model's
            # FIRST greeting already knows which fields are filled — no
            # get_current_state round-trip, no "these are already filled"
            # reminder from the participant.
            if self._initial_state_text:
                await session.send_realtime_input(text=self._initial_state_text)
                log.info("initial_state_seeded session=%s", self._session_id)
            else:
                # gemini-3.1-flash-live-preview does NOT speak proactively, so
                # without a kickoff turn the agent stays silent until the
                # participant speaks first. When there's no bootstrap state to
                # seed, still inject a minimal opener cue so the agent ALWAYS
                # greets at screen open.
                await session.send_realtime_input(
                    text="[BEGIN] Greet the participant warmly per your system "
                    "prompt and ask the first required field."
                )
                log.info("kickoff_greeting_injected session=%s", self._session_id)
            self._last_audio_at = time.monotonic()
            # Hard cap on the kickoff shield: if the opener never produces a
            # turn_complete (e.g. silent / model stalls), lift the shield after
            # 8 s so the participant is never permanently muted.
            self._kickoff_grace_until = time.monotonic() + 8.0
=======
            self._last_audio_at = time.monotonic()
>>>>>>> ai-chatbot
            b2g = asyncio.create_task(self._browser_to_gemini(session))
            g2b = asyncio.create_task(self._gemini_to_browser(session))
            silence = asyncio.create_task(self._silence_monitor(session))
            # If g2b exits first (e.g. advance_step closes the step), unblock b2g
            g2b.add_done_callback(lambda _t: b2g.cancel())
            try:
                await b2g  # blocks until client disconnects, stop, or step done
            except asyncio.CancelledError:
                pass
            finally:
                g2b.cancel()
                silence.cancel()
                await asyncio.gather(g2b, silence, return_exceptions=True)
<<<<<<< HEAD
                # client_stop cancels g2b before its final turn_complete emits,
                # so flush the last turn's usage here. Telemetry never breaks
                # teardown — swallow any error.
                try:
                    self._flush_pending_usage(reason="session_end")
                except Exception:
                    log.exception("usage_flush_failed session=%s", self._session_id)
=======
>>>>>>> ai-chatbot
        log.info("gemini_disconnected session=%s", self._session_id)

    # ── Private: client → Gemini ──────────────────────────────────────────────

    async def _browser_to_gemini(self, session: genai.live.AsyncSession) -> None:
        """Forward browser audio + control messages → Gemini."""
        total_chunks = 0
        try:
            while True:
                msg = await self._ws.receive()
                if msg["type"] == "websocket.disconnect":
                    return

                raw_bytes = msg.get("bytes")
                raw_text = msg.get("text")

                if raw_bytes:
                    self._last_audio_at = time.monotonic()
<<<<<<< HEAD
                    # User is talking — clear silence watchdog state so the next
                    # silence period restarts the full warn → summary cycle.
                    self._silence_warned = False
                    self._silence_exhausted = False
                    # Kickoff shield (cookbook #1197): drop EVERY inbound mic
                    # frame until the opening agent turn finishes. Barging the
                    # opening interrupts turn 0 with zero chunks and wedges
                    # Gemini's VAD for the whole session (no more
                    # input_transcription). Gating on turn-completion (not a
                    # timer) is required because the barge-in frames land before
                    # the first model audio. The 8 s grace cap lifts the shield
                    # if the opener never completes.
                    if self._kickoff_shield_active:
                        if time.monotonic() >= self._kickoff_grace_until:
                            self._kickoff_shield_active = False
                            log.info(
                                "kickoff_shield_lifted reason=grace session=%s",
                                self._session_id,
                            )
                        else:
                            continue
=======
                    # User is talking — clear the silence watchdog state so a
                    # later silence triggers the FIRST-step warn again, not the
                    # SECOND-step summary.
                    self._silence_warned = False
>>>>>>> ai-chatbot
                    # Send all audio unconditionally — Gemini's VAD + START_OF_ACTIVITY_INTERRUPTS
                    # handles barge-in natively. The old _agent_speaking echo gate blocked user
                    # audio after turn N+1 model audio arrived, causing VAD to stop firing.
                    await session.send_realtime_input(
                        audio=types.Blob(data=raw_bytes, mime_type="audio/pcm;rate=16000")
                    )
                    total_chunks += 1
                    if total_chunks % 50 == 0:
<<<<<<< HEAD
                        log.info(
                            "audio_streaming chunks=%d session=%s",
                            total_chunks,
                            self._session_id,
                        )
=======
                        log.info("audio_streaming chunks=%d session=%s", total_chunks, self._session_id)
>>>>>>> ai-chatbot

                elif raw_text:
                    stop_requested = await self._handle_control(session, raw_text)
                    if stop_requested:
                        return

        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        except Exception:
            log.exception("b2g_error session=%s", self._session_id)

    async def _handle_control(self, session: genai.live.AsyncSession, raw_text: str) -> bool:
        """
        Handle a JSON control message from the client.
        Returns True if the session should stop.
        """
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            log.warning("invalid_json_from_client session=%s", self._session_id)
            return False

        msg_type = data.get("type")

        if msg_type == "user_text":
            text = data.get("text", "").strip()
            if text:
                await session.send_realtime_input(text=text)

        elif msg_type == "audio_end":
            # Signal end-of-utterance so Gemini flushes its audio buffer
            await session.send_realtime_input(audio_stream_end=True)

<<<<<<< HEAD
        elif msg_type == "tool_response":
            request_id = data.get("request_id")
            result = data.get("result", {})
            if isinstance(request_id, str) and self._mobile_bridge is not None:
                self._mobile_bridge.resolve(request_id, result)

        elif msg_type in ("screen_state", "screen_state_v2"):
            # api.md: enforce SCREEN_STATE_MAX_BYTES BEFORE Pydantic parse to
            # prevent memory exhaustion via a giant payload.
            if len(raw_text) > settings.screen_state_max_bytes:
                await self._ws.send_text(
                    json.dumps(
                        {
                            "type": "error",
                            "code": "screen_state_too_large",
                            "message": (
                                f"screen_state payload exceeds "
                                f"{settings.screen_state_max_bytes} bytes"
                            ),
                        }
                    )
                )
                return False
            if msg_type == "screen_state":
                await self._handle_screen_state(session, data, version=1)
            else:
                await self._handle_screen_state_v2_turn(session, data)

        elif msg_type == "validation_failed":
            await self._handle_validation_failed(session, data)

        elif msg_type == "validation_cleared":
            await self._handle_validation_cleared(data)
=======
        elif msg_type == "screen_state":
            await self._handle_screen_state(session, data, version=1)

        elif msg_type == "screen_state_v2":
            await self._handle_screen_state(session, data, version=2)
>>>>>>> ai-chatbot

        elif msg_type == "stop":
            log.info("client_stop session=%s", self._session_id)
            return True

        # "start" arrives before run() — safe to ignore here if it slips through
        return False

<<<<<<< HEAD
    async def _handle_validation_failed(self, session: genai.live.AsyncSession, data: dict) -> None:
        """Flutter reports a client-side validation rejection — upsert into
        pending_validation_errors and inject a re-ask prompt into Gemini."""
        section_id = data.get("section_id", "")
        field_id = data.get("field_id", "")
        repeatable_index = data.get("repeatable_index")
        reason_human = data.get("reason_human", "The value was not accepted.")
        code = data.get("code", "client_validation_failed")

        if not section_id or not field_id:
            log.warning(
                "validation_failed missing section/field session=%s",
                self._session_id,
            )
            return

        state = await self._repo.get_state(self._session_id)
        if state is None:
            return

        key = (section_id, field_id, repeatable_index)
        state.pending_validation_errors = [
            e
            for e in state.pending_validation_errors
            if (
                e.get("section_id"),
                e.get("field_id"),
                e.get("repeatable_index"),
            )
            != key
        ]
        state.pending_validation_errors.append(
            {
                "section_id": section_id,
                "field_id": field_id,
                "repeatable_index": repeatable_index,
                "code": code,
                "reason_human": reason_human,
            }
        )
        await self._repo.save_state(state, ttl_sec=settings.session_max_sec)

        loc = f"{section_id}.{field_id}"
        if repeatable_index is not None:
            loc += f"[{repeatable_index}]"
        injection = (
            f"[SCREEN VALIDATION] The screen rejected the value stored for {loc}: "
            f"{reason_human} — re-ask the participant for a corrected value (Rule 7)."
        )
        # N-3 race fix: flush any in-flight audio buffer before injecting text
        # so the [SCREEN VALIDATION] hint cannot be concatenated into the user's
        # current utterance and misread as their speech by Gemini's VAD.
        await session.send_realtime_input(audio_stream_end=True)
        await session.send_realtime_input(text=injection)
        log.info(
            "validation_failed_injected session=%s loc=%s code=%s",
            self._session_id,
            loc,
            code,
        )

    async def _handle_validation_cleared(self, data: dict) -> None:
        """Flutter reports a validation error has been resolved — remove from state."""
        section_id = data.get("section_id", "")
        field_id = data.get("field_id", "")
        repeatable_index = data.get("repeatable_index")

        if not section_id or not field_id:
            return

        state = await self._repo.get_state(self._session_id)
        if state is None:
            return

        key = (section_id, field_id, repeatable_index)
        state.pending_validation_errors = [
            e
            for e in state.pending_validation_errors
            if (
                e.get("section_id"),
                e.get("field_id"),
                e.get("repeatable_index"),
            )
            != key
        ]
        await self._repo.save_state(state, ttl_sec=settings.session_max_sec)
        log.info(
            "validation_cleared session=%s section=%s field=%s",
            self._session_id,
            section_id,
            field_id,
        )

    async def _handle_screen_state_v2_turn(
        self, session: genai.live.AsyncSession, data: dict
    ) -> None:
        """Handle screen_state_v2 with TurnPayload — updates _current_turn and
        falls through to the legacy screen-state injection for Gemini context."""
        from pydantic import ValidationError

        from onboarding.models.turn_payload import TurnPayload

        turn_json = data.get("turn")
        if turn_json is not None:
            try:
                new_turn = TurnPayload.model_validate(turn_json)
                self._current_turn = new_turn
                # Do NOT inject [TURN] as send_realtime_input(text=...) —
                # Gemini Live treats realtime text as a user message and will
                # trigger a model turn AND poison VAD state for subsequent
                # audio. The TurnPayload is already embedded in the system
                # instruction at session start, and update_field round-trips
                # surface live deltas to the agent.
            except ValidationError as e:
                await self._ws.send_text(
                    json.dumps(
                        {
                            "type": "error",
                            "code": "turn_invalid",
                            "message": str(e),
                        }
                    )
                )
                return
        else:
            # No turn key — delegate to legacy handler for backwards-compat.
            await self._handle_screen_state(session, data, version=2)

    async def _handle_screen_state(
        self, session: genai.live.AsyncSession, data: dict, *, version: int = 1
=======
    async def _handle_screen_state(
        self, session: "genai.live.AsyncSession", data: dict, *, version: int = 1
>>>>>>> ai-chatbot
    ) -> None:
        """
        Validate, deduplicate, and inject a screen_state (v1 or v2) message as a
        Gemini text turn. Identical consecutive payloads are dropped (idempotent).
        Payload logged at debug only — PII compliance.
        """
        from pydantic import ValidationError

        raw_data = data.get("data", {})
        h = payload_hash(raw_data)
        if h == self._last_screen_hash:
<<<<<<< HEAD
            log.debug(
                "screen_state_duplicate_dropped session=%s version=%d",
                self._session_id,
                version,
            )
=======
            log.debug("screen_state_duplicate_dropped session=%s version=%d", self._session_id, version)
>>>>>>> ai-chatbot
            return

        try:
            if version == 2:
                v2_msg = ScreenStateV2Message(type="screen_state_v2", data=raw_data)
                state_v2 = v2_msg.data
            else:
                v1_msg = ScreenStateMessage(type="screen_state", data=raw_data)
                state_v2 = from_v1(v1_msg, session_step_id=None)
        except ValidationError as exc:
<<<<<<< HEAD
            log.warning(
                "screen_state_invalid session=%s version=%d error=%s",
                self._session_id,
                version,
                exc,
            )
            await self._ws.send_text(
                json.dumps(
                    {
                        "type": "error",
                        "code": "screen_state_invalid",
                        "message": str(exc),
                    }
                )
=======
            log.warning("screen_state_invalid session=%s version=%d error=%s",
                        self._session_id, version, exc)
            await self._ws.send_text(
                json.dumps({"type": "error", "code": "screen_state_invalid",
                            "message": str(exc)})
>>>>>>> ai-chatbot
            )
            return

        self._last_screen_hash = h
        injection = render_injection_text(state_v2)
<<<<<<< HEAD
        log.debug(
            "screen_state_inject session=%s version=%d",
            self._session_id,
            version,
        )
        await session.send_realtime_input(text=injection)

        # N-4 fix: mirror v2 field_errors into state.pending_validation_errors so
        # advance_step's gate has a single source of truth regardless of whether
        # Flutter also sends a separate validation_failed control frame.
        # Use state_v2.field_errors (dict[dotted_path → reason_human]) from the
        # already-validated Pydantic model — avoids raw_data format skew.
        if state_v2.field_errors:
            state_fv = await self._repo.get_state(self._session_id)
            if state_fv is not None:
                existing_keys = {
                    (e.get("section_id"), e.get("field_id"), e.get("repeatable_index"))
                    for e in state_fv.pending_validation_errors
                }
                newly_rejected: list[str] = []
                for dotted_path, reason_human in state_v2.field_errors.items():
                    parts = dotted_path.split(".", 1)
                    if len(parts) != 2:
                        continue
                    sec, fld = parts
                    key = (sec, fld, None)
                    if key not in existing_keys:
                        newly_rejected.append(reason_human)
                    state_fv.pending_validation_errors = [
                        e
                        for e in state_fv.pending_validation_errors
                        if (
                            e.get("section_id"),
                            e.get("field_id"),
                            e.get("repeatable_index"),
                        )
                        != key
                    ]
                    state_fv.pending_validation_errors.append(
                        {
                            "section_id": sec,
                            "field_id": fld,
                            "repeatable_index": None,
                            "code": "client_validation",
                            "reason_human": reason_human,
                        }
                    )
                await self._repo.save_state(state_fv, ttl_sec=settings.session_max_sec)
                # Parity with _handle_validation_failed: a screen-originated
                # validation error must be SPOKEN, not just stored — otherwise the
                # participant sees a rejected field the agent never mentions. Only
                # cue NEWLY-appearing errors so repeated screen_states don't nag.
                if newly_rejected:
                    await session.send_realtime_input(audio_stream_end=True)
                    await session.send_realtime_input(
                        text=(
                            "[SCREEN VALIDATION] The screen rejected: "
                            + "; ".join(newly_rejected[:3])
                            + " — tell the participant in plain words and re-ask "
                            "for a corrected value (Rule 7)."
                        )
                    )
                    log.info(
                        "screen_state_validation_injected session=%s count=%d",
                        self._session_id,
                        len(newly_rejected),
                    )

        if settings.debug:
            await self._ws.send_text(
                json.dumps(
                    {
                        "type": "screen_state_ack",
                        "accepted": True,
                        "version": version,
                    }
                )
            )

    def _flush_pending_usage(self, *, reason: str) -> None:
        """Emit any usage delta not yet flushed by a turn_complete.

        Idempotent via the existing watermark advanced at turn_complete: if
        cum == emitted all deltas are 0 and we early-return, so calling this
        twice (turn_complete already ran, then session end) emits nothing the
        second time. Guards on TOKEN deltas only — chunk_count is a g2b-local
        not readable here, so audio_chunks_out is 0; the abandoned final turn's
        tool calls are still counted faithfully because the watermark blocks any
        double-emit. Why this exists: client_stop cancels g2b before its final
        turn_complete runs, so the last turn's tokens would otherwise be lost.
        """
        d_prompt = max(0, self._usage_cum_prompt - self._usage_emitted_prompt)
        d_response = max(0, self._usage_cum_response - self._usage_emitted_response)
        d_cached = max(0, self._usage_cum_cached - self._usage_emitted_cached)
        if not (d_prompt or d_response or d_cached):
            return
        d_prompt_audio = max(
            0, self._usage_cum_prompt_audio - self._usage_emitted_prompt_audio
        )
        d_response_audio = max(
            0, self._usage_cum_response_audio - self._usage_emitted_response_audio
        )
        emit_usage(
            tenant_id=self._tenant_id or "unknown",
            user_id=self._user_id,
            feature=UsageFeature.VOICE_ONBOARDING,
            model=settings.gemini_live_model_id,
            session_id=self._session_id,
            prompt_tokens=d_prompt,
            response_tokens=d_response,
            cached_tokens=d_cached,
            prompt_audio_tokens=d_prompt_audio,
            response_audio_tokens=d_response_audio,
            tool_call_count=self._tool_calls_in_turn,
            success=True,
            turn_id=self._turn_id,
            audio_chunks_out=0,
            participant_id=self._participant_id,
            step_id=(self._current_turn.step.id if self._current_turn else None),
            step_number=(
                self._current_turn.step.number if self._current_turn else None
            ),
        )
        self._usage_emitted_prompt = self._usage_cum_prompt
        self._usage_emitted_response = self._usage_cum_response
        self._usage_emitted_cached = self._usage_cum_cached
        self._usage_emitted_prompt_audio = self._usage_cum_prompt_audio
        self._usage_emitted_response_audio = self._usage_cum_response_audio
        log.info(
            "usage_flushed reason=%s prompt=%d response=%d turn=%d session=%s",
            reason,
            d_prompt,
            d_response,
            self._turn_id,
            self._session_id,
        )
=======
        log.debug("screen_state_inject session=%s version=%d", self._session_id, version)
        await session.send_realtime_input(text=injection)

        if settings.debug:
            await self._ws.send_text(json.dumps({"type": "screen_state_ack", "accepted": True, "version": version}))
>>>>>>> ai-chatbot

    # ── Private: Gemini → client ──────────────────────────────────────────────

    async def _gemini_to_browser(self, session: genai.live.AsyncSession) -> None:
        """
        Forward Gemini audio and transcript events → client.

        session.receive() is a per-turn async iterator — it exhausts after each
        turn batch. The outer `while True` re-enters it for subsequent turns
        without closing the Gemini connection.
        """
        chunk_count = 0
        turn_started = False
        loop_iter = 0
        agent_transcript_buf: list[str] = []

        try:
            while True:
                loop_iter += 1
                async for msg in session.receive():
<<<<<<< HEAD
                    # ── Usage telemetry (Phase 1) — cumulative per session ──
                    # `msg.usage_metadata` may arrive on any event; we keep the
                    # latest cumulative read and emit the delta at turn_complete.
                    _um = getattr(msg, "usage_metadata", None)
                    if _um is not None:
                        self._usage_cum_prompt = int(
                            getattr(_um, "prompt_token_count", 0) or 0
                        )
                        self._usage_cum_response = int(
                            getattr(_um, "response_token_count", 0)
                            or getattr(_um, "candidates_token_count", 0)
                            or 0
                        )
                        self._usage_cum_cached = int(
                            getattr(_um, "cached_content_token_count", 0) or 0
                        )
                        # Per-modality split (Phase 1.6) — sum the AUDIO slice so
                        # cost is priced exactly, not via the 90/10 heuristic.
                        self._usage_cum_prompt_audio = _sum_audio_tokens(
                            getattr(_um, "prompt_tokens_details", None)
                        )
                        self._usage_cum_response_audio = _sum_audio_tokens(
                            getattr(_um, "candidates_tokens_details", None)
                            or getattr(_um, "response_tokens_details", None)
                        )

                    # ── Tool calls (Phase C) — handled before server_content ──
                    if self._tools and getattr(msg, "tool_call", None):
                        # Count the number of function calls in this batch — used in
                        # the per-turn usage emit at turn_complete.
                        _calls = getattr(msg.tool_call, "function_calls", None) or []
                        self._tool_calls_in_turn += len(_calls)
=======
                    # ── Tool calls (Phase C) — handled before server_content ──
                    if self._tools and getattr(msg, "tool_call", None):
>>>>>>> ai-chatbot
                        await self._handle_tool_call(session, msg.tool_call)
                        if self._tools.step_completed:
                            # Let queued agent audio flush, then end loop
                            continue

                    sc = msg.server_content

                    if sc:
                        # ── Input transcription (user speech → text) ───────────
                        if sc.input_transcription and sc.input_transcription.text:
                            txt = sc.input_transcription.text
                            log.info("USER_SAID %r session=%s", txt, self._session_id)
                            await self._ws.send_text(json.dumps({"type": "user_said", "text": txt}))
                            await self._repo.append_transcript(
                                self._session_id,
                                {"speaker": "user", "text": txt, "turn_id": self._turn_id},
                                ttl_sec=settings.session_max_sec,
                            )

                        # ── Output transcription (Gemini speech → text) ────────
                        # Gemini streams transcription word-by-word aligned with TTS audio.
                        # Accumulate chunks; emit one consolidated agent_said per turn.
                        if sc.output_transcription and sc.output_transcription.text:
                            agent_transcript_buf.append(sc.output_transcription.text)

                        # ── Audio output (PCM16 24 kHz chunks) ────────────────
                        if sc.model_turn:
                            for part in sc.model_turn.parts:
                                if part.inline_data:
                                    if not turn_started:
                                        await self._ws.send_text(json.dumps({"type": "turn_start"}))
                                        turn_started = True
                                        self._gemini_is_speaking = True
<<<<<<< HEAD
                                        # Do NOT send audio_stream_end here in
                                        # auto-VAD mode — it is only honoured
                                        # in manual-VAD mode and otherwise
                                        # corrupts VAD state. Echo is fully
                                        # handled by Flutter mic mute.
=======
                                        # NOTE: Do NOT send audio_stream_end=True here.
                                        # Per Gemini Live API: audio_stream_end means
                                        # "microphone turned off / stream closed" — it
                                        # signals session-level end-of-input, not a
                                        # mid-conversation flush. Sending it on every
                                        # turn corrupts VAD state and causes Gemini to
                                        # mis-handle subsequent user audio. Echo must
                                        # be solved on the client (Flutter mic mute).
>>>>>>> ai-chatbot
                                    await self._ws.send_bytes(part.inline_data.data)
                                    chunk_count += 1

                        # ── Interruption (user spoke over the agent) ───────────
                        if sc.interrupted:
<<<<<<< HEAD
                            log.info(
                                "interrupted turn=%d chunks_before=%d session=%s",
                                self._turn_id,
                                chunk_count,
                                self._session_id,
                            )
=======
                            log.info("interrupted turn=%d chunks_before=%d session=%s",
                                     self._turn_id, chunk_count, self._session_id)
>>>>>>> ai-chatbot
                            interrupted_intent: str | None = None
                            if agent_transcript_buf:
                                full_text = "".join(agent_transcript_buf)
                                interrupted_intent = full_text.strip() or None
<<<<<<< HEAD
                                log.info(
                                    "AGENT_SAID(interrupted) %r session=%s",
                                    full_text,
                                    self._session_id,
                                )
                                await self._ws.send_text(
                                    json.dumps(
                                        {
                                            "type": "agent_said",
                                            "text": full_text,
                                        }
                                    )
                                )
                                await self._repo.append_transcript(
                                    self._session_id,
                                    {
                                        "speaker": "agent",
                                        "text": full_text,
                                        "turn_id": self._turn_id,
                                    },
=======
                                log.info("AGENT_SAID(interrupted) %r session=%s", full_text, self._session_id)
                                await self._ws.send_text(json.dumps({"type": "agent_said", "text": full_text}))
                                await self._repo.append_transcript(
                                    self._session_id,
                                    {"speaker": "agent", "text": full_text, "turn_id": self._turn_id},
>>>>>>> ai-chatbot
                                    ttl_sec=settings.session_max_sec,
                                )
                                agent_transcript_buf.clear()
                            await self._ws.send_text(json.dumps({"type": "interrupted"}))
                            turn_started = False
                            chunk_count = 0
                            self._gemini_is_speaking = False
<<<<<<< HEAD
                            # Reset silence timer — user gets a fresh window after each agent turn
                            self._last_audio_at = time.monotonic()
=======
>>>>>>> ai-chatbot

                            # Voice protocol — preserve the interrupted thought
                            # so the next agent turn can address the user's
                            # interruption AND the unfinished idea. Inject as a
                            # hidden text turn the model treats as fresh
                            # context (system prompt teaches it to expect this
                            # exact prefix).
                            if interrupted_intent:
                                self._last_interrupted_intent = interrupted_intent
                                try:
                                    await session.send_realtime_input(
                                        text=(
                                            "[INTERRUPTED] You were saying: "
<<<<<<< HEAD
                                            f'"{interrupted_intent}". '
=======
                                            f"\"{interrupted_intent}\". "
>>>>>>> ai-chatbot
                                            "Address what the user just said first, "
                                            "then return to that thought only if it "
                                            "is still relevant."
                                        )
                                    )
                                    log.info(
                                        "interrupt_intent preserved chars=%d session=%s",
                                        len(interrupted_intent),
                                        self._session_id,
                                    )
                                except Exception:
                                    log.exception(
                                        "interrupt_intent_inject_failed session=%s",
                                        self._session_id,
                                    )

                        # ── Turn complete ──────────────────────────────────────
                        if sc.turn_complete:
                            if agent_transcript_buf:
                                full_text = "".join(agent_transcript_buf)
<<<<<<< HEAD
                                log.info(
                                    "AGENT_SAID %r session=%s",
                                    full_text,
                                    self._session_id,
                                )
                                await self._ws.send_text(
                                    json.dumps(
                                        {
                                            "type": "agent_said",
                                            "text": full_text,
                                        }
                                    )
                                )
                                await self._repo.append_transcript(
                                    self._session_id,
                                    {
                                        "speaker": "agent",
                                        "text": full_text,
                                        "turn_id": self._turn_id,
                                    },
=======
                                log.info("AGENT_SAID %r session=%s", full_text, self._session_id)
                                await self._ws.send_text(json.dumps({"type": "agent_said", "text": full_text}))
                                await self._repo.append_transcript(
                                    self._session_id,
                                    {"speaker": "agent", "text": full_text, "turn_id": self._turn_id},
>>>>>>> ai-chatbot
                                    ttl_sec=settings.session_max_sec,
                                )
                                agent_transcript_buf.clear()
                            await self._ws.send_text(json.dumps({"type": "turn_complete"}))
<<<<<<< HEAD
                            log.info(
                                "turn_complete chunks=%d turn=%d session=%s",
                                chunk_count,
                                self._turn_id,
                                self._session_id,
                            )
                            # Lift the kickoff shield once the opening turn has
                            # actually SPOKEN (chunks > 0). A zero-chunk turn_
                            # complete is the interrupted/empty opener — keep the
                            # shield up so the (now-armed) real greeting on the
                            # retry is still protected.
                            if self._kickoff_shield_active and chunk_count > 0:
                                self._kickoff_shield_active = False
                                log.info(
                                    "kickoff_shield_lifted reason=opener_spoke turn=%d session=%s",
                                    self._turn_id,
                                    self._session_id,
                                )

                            # ── Phase 1 usage emit — per turn delta ──────────
                            # Cumulative-to-delta math. If any event in this
                            # turn carried usage_metadata, the cumulative
                            # totals advanced; the delta is this turn's cost.
                            d_prompt = max(0, self._usage_cum_prompt - self._usage_emitted_prompt)
                            d_response = max(0, self._usage_cum_response - self._usage_emitted_response)
                            d_cached = max(0, self._usage_cum_cached - self._usage_emitted_cached)
                            d_prompt_audio = max(
                                0,
                                self._usage_cum_prompt_audio
                                - self._usage_emitted_prompt_audio,
                            )
                            d_response_audio = max(
                                0,
                                self._usage_cum_response_audio
                                - self._usage_emitted_response_audio,
                            )
                            if d_prompt or d_response or d_cached or chunk_count or self._tool_calls_in_turn:
                                emit_usage(
                                    tenant_id=self._tenant_id or "unknown",
                                    user_id=self._user_id,
                                    feature=UsageFeature.VOICE_ONBOARDING,
                                    model=settings.gemini_live_model_id,
                                    session_id=self._session_id,
                                    prompt_tokens=d_prompt,
                                    response_tokens=d_response,
                                    cached_tokens=d_cached,
                                    prompt_audio_tokens=d_prompt_audio,
                                    response_audio_tokens=d_response_audio,
                                    tool_call_count=self._tool_calls_in_turn,
                                    success=True,
                                    turn_id=self._turn_id,
                                    audio_chunks_out=chunk_count,
                                    participant_id=self._participant_id,
                                    # Per-screen cost attribution. One WS session
                                    # = one onboarding step, but the step id only
                                    # exists once a screen_state_v2/TurnPayload has
                                    # arrived; None-safe until then (aggregator
                                    # buckets missing ids under "(no-step)").
                                    step_id=(
                                        self._current_turn.step.id
                                        if self._current_turn
                                        else None
                                    ),
                                    step_number=(
                                        self._current_turn.step.number
                                        if self._current_turn
                                        else None
                                    ),
                                )
                                self._usage_emitted_prompt = self._usage_cum_prompt
                                self._usage_emitted_response = self._usage_cum_response
                                self._usage_emitted_cached = self._usage_cum_cached
                                self._usage_emitted_prompt_audio = self._usage_cum_prompt_audio
                                self._usage_emitted_response_audio = (
                                    self._usage_cum_response_audio
                                )

=======
                            log.info("turn_complete chunks=%d turn=%d session=%s",
                                     chunk_count, self._turn_id, self._session_id)
>>>>>>> ai-chatbot
                            self._turn_id += 1
                            chunk_count = 0
                            turn_started = False
                            self._gemini_is_speaking = False
<<<<<<< HEAD
                            self._tool_calls_in_turn = 0
                            # Reset silence timer — user gets a fresh window after each agent turn
                            self._last_audio_at = time.monotonic()
=======
>>>>>>> ai-chatbot
                            if self._tools:
                                self._tools.set_turn_id(self._turn_id)
                            # Phase C — advance_step closed the step; end loop
                            # after the agent's farewell turn has flushed.
                            if self._tools and self._tools.step_completed:
                                return

                    # ── Session resumption handle (Gemini-level, ~every 60 s) ──
                    # The server sends updated handles so the connection can be
                    # resumed at the Gemini level after a drop.  We log the arrival
                    # here; a future phase can forward this to Redis via the repo
                    # to enable Gemini-native reconnect (faster than app-level replay).
                    resumption_update = getattr(msg, "session_resumption_update", None)
                    if resumption_update:
                        gemini_handle = getattr(resumption_update, "resumable_session_handle", None)
                        if gemini_handle:
                            log.debug(
                                "gemini_session_handle_updated session=%s handle=%.12s…",
<<<<<<< HEAD
                                self._session_id,
                                gemini_handle,
=======
                                self._session_id, gemini_handle,
>>>>>>> ai-chatbot
                            )

                    # ── GoAway — Gemini about to close the connection ──────────
                    # Forward to the client so the Flutter app can proactively
                    # call the resume endpoint before the drop becomes a hard
                    # disconnect.  Without this the client sees a silent audio
                    # gap with no indication a reconnect is needed.
                    if msg.go_away:
                        time_left = msg.go_away.time_left
<<<<<<< HEAD
                        log.warning(
                            "go_away time_left=%s session=%s",
                            time_left,
                            self._session_id,
                        )
                        with contextlib.suppress(Exception):
                            ms: int = 0
                            if time_left is not None:
                                with contextlib.suppress(Exception):
                                    ms = int(time_left.total_seconds() * 1000)
                            await self._ws.send_text(
                                json.dumps(
                                    {
                                        "type": "go_away",
                                        "time_left_ms": ms,
                                    }
                                )
                            )

                # receive() iterator exhausted — re-enter for next turn
                log.debug(
                    "g2b_recv_iter_end loop=%d session=%s",
                    loop_iter,
                    self._session_id,
                )
=======
                        log.warning("go_away time_left=%s session=%s",
                                    time_left, self._session_id)
                        try:
                            ms: int = 0
                            if time_left is not None:
                                try:
                                    ms = int(time_left.total_seconds() * 1000)
                                except Exception:
                                    pass
                            await self._ws.send_text(json.dumps({
                                "type": "go_away",
                                "time_left_ms": ms,
                            }))
                        except Exception:
                            pass

                # receive() iterator exhausted — re-enter for next turn
                log.debug("g2b_recv_iter_end loop=%d session=%s", loop_iter, self._session_id)
>>>>>>> ai-chatbot
                await asyncio.sleep(0.01)
                continue

        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
<<<<<<< HEAD
        except Exception as exc:
            if _is_client_disconnect(exc):
                log.info("g2b_client_disconnected session=%s", self._session_id)
            else:
                log.exception("g2b_error session=%s", self._session_id)
=======
        except Exception:
            log.exception("g2b_error session=%s", self._session_id)
>>>>>>> ai-chatbot

    # ── Private: silence monitor ──────────────────────────────────────────────

    async def _silence_monitor(self, session: genai.live.AsyncSession) -> None:
        """
        Two-step silence watchdog (per voice protocol).

        Polls every _SILENCE_POLL_SEC seconds. If the user has been silent for
        >= settings.onboarding_silence_timeout_sec AND Gemini is not currently
        speaking:

        - **First fire** (self._silence_warned == False): inject a gentle
          check-in cue ("Are you still there?").
        - **Second fire** (self._silence_warned == True): inject a pending-
          fields summary cue listing missing-required field labels so the
          agent can recap what's left.

        self._silence_warned resets to False whenever new user audio arrives
        (in _browser_to_gemini), so a quick reply restarts the cycle.

        Set SENA_AI_ONBOARDING_SILENCE_TIMEOUT_SEC=0 to disable entirely.
        """
        if settings.onboarding_silence_timeout_sec <= 0:
            return
        try:
            while True:
                await asyncio.sleep(_SILENCE_POLL_SEC)
                elapsed = time.monotonic() - self._last_audio_at
<<<<<<< HEAD
                if (
                    elapsed < settings.onboarding_silence_timeout_sec
                    or self._gemini_is_speaking
                    or self._silence_exhausted
                ):
=======
                if elapsed < settings.onboarding_silence_timeout_sec or self._gemini_is_speaking:
>>>>>>> ai-chatbot
                    continue

                if not self._silence_warned:
                    # First fire — gentle "are you still there?" cue.
                    log.info(
                        "silence_watchdog fired threshold=%.0fs step=warn session=%s",
<<<<<<< HEAD
                        elapsed,
                        self._session_id,
=======
                        elapsed, self._session_id,
>>>>>>> ai-chatbot
                    )
                    cue = (
                        "[SILENCE TIMEOUT] The participant has been silent. "
                        "Check in warmly in Australian English, e.g. "
                        "'Hey, just checking — are you still there? No rush at all, "
                        "take your time.'"
                    )
                    self._silence_warned = True
                else:
                    # Second fire — recap pending fields. Pull the live state
                    # so the cue mentions only what's still missing.
                    pending_labels = await self._collect_pending_required_labels()
                    log.info(
                        "silence_watchdog fired threshold=%.0fs step=summary "
                        "pending=%d session=%s",
<<<<<<< HEAD
                        elapsed,
                        len(pending_labels),
                        self._session_id,
=======
                        elapsed, len(pending_labels), self._session_id,
>>>>>>> ai-chatbot
                    )
                    if pending_labels:
                        joined = ", ".join(pending_labels[:6])
                        cue = (
                            "[SILENCE TIMEOUT — SUMMARY] The participant is still "
                            "silent. Gently summarise what's left, then offer to "
                            "continue. For example: 'When you're ready, we still "
                            f"need: {joined}. No rush — just let me know when you "
                            "want to keep going.'"
                        )
                    else:
                        cue = (
                            "[SILENCE TIMEOUT — SUMMARY] The participant is still "
                            "silent. Reassure them you're here whenever they're "
                            "ready, in Australian English."
                        )
<<<<<<< HEAD
                    self._silence_exhausted = True
                with contextlib.suppress(Exception):
                    await session.send_realtime_input(text=cue)
=======
                try:
                    await session.send_realtime_input(text=cue)
                except Exception:
                    pass
>>>>>>> ai-chatbot
                # Reset the audio-at timestamp so the watchdog doesn't fire
                # again immediately. _silence_warned stays True until a real
                # user utterance arrives in _browser_to_gemini.
                self._last_audio_at = time.monotonic()
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("silence_monitor_error session=%s", self._session_id)

    async def _collect_pending_required_labels(self) -> list[str]:
        """Best-effort: read the live FormState + schema and return the labels
        of required fields that are still empty. Used by the silence summary."""
        try:
            state = await self._repo.get_state(self._session_id)
            schema = await self._repo.get_schema(self._session_id)
            if state is None or schema is None:
                return []
            pending: list[str] = []
            for section in schema.sections:
<<<<<<< HEAD
                default_val = {} if not section.is_repeatable else []
                section_values = state.values.get(section.id) or default_val
=======
                section_values = state.values.get(section.id) or ({} if not section.is_repeatable else [])
>>>>>>> ai-chatbot
                for f in section.all_fields():
                    if not f.required or f.visible_if is not None:
                        continue
                    label = f.label or f.id
                    if section.is_repeatable:
                        rows = section_values if isinstance(section_values, list) else []
                        if not rows:
                            pending.append(label)
                    else:
                        row = section_values if isinstance(section_values, dict) else {}
                        fv = row.get(f.id)
                        v = fv.get("value") if isinstance(fv, dict) else None
                        if v in (None, "", []):
                            pending.append(label)
            return pending
        except Exception:
            log.exception("collect_pending_labels_failed session=%s", self._session_id)
            return []

    # ── Private: tool_call handling (Phase C) ────────────────────────────────

    async def _handle_tool_call(
        self,
        session: genai.live.AsyncSession,
<<<<<<< HEAD
        tool_call: types.LiveServerToolCall,
=======
        tool_call: "types.LiveServerToolCall",
>>>>>>> ai-chatbot
    ) -> None:
        """
        Dispatch every function call in a tool_call batch and send the
        aggregated tool response back. Function calling on Gemini Live is
        synchronous — the model will not continue until we reply.
        """
        assert self._tools is not None  # guarded by caller

        function_calls = getattr(tool_call, "function_calls", None) or []
        if not function_calls:
            return

        responses: list[types.FunctionResponse] = []
        for call in function_calls:
            args_dict = dict(call.args) if call.args else {}
            try:
                result = await self._tools.dispatch(call.name, args_dict)
<<<<<<< HEAD
            except Exception as exc:
                if _is_client_disconnect(exc):
                    # Client WS dropped mid-dispatch — abort the batch quietly;
                    # the b2g/g2b loops handle teardown. No traceback.
                    log.info(
                        "tool_dispatch_client_disconnected tool=%s session=%s",
                        call.name,
                        self._session_id,
                    )
                    return
                log.exception(
                    "tool_dispatch_error tool=%s session=%s",
                    call.name,
                    self._session_id,
                )
                result = {
                    "ok": False,
                    "reason": "Internal dispatch error",
                    "code": "dispatch_error",
                }
=======
            except PolicyBlockSignal as exc:
                log.info("policy_block_signal question=%r session=%s", exc.question, self._session_id)
                await self._ws.send_text(json.dumps({
                    "type": "error",
                    "code": "policy_block",
                    "message": (
                        "This question requires current NDIS policy data. "
                        "Please re-ask with Google Search grounding enabled."
                    ),
                }))
                await self._ws.close(4011)
                return
>>>>>>> ai-chatbot
            responses.append(
                types.FunctionResponse(
                    id=call.id,
                    name=call.name,
                    response=result,
                )
            )

        await session.send_tool_response(function_responses=responses)
