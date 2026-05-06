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
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
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
from onboarding.services.tools import FUNCTION_DECLS, POLICY_BLOCK_DECL, PolicyBlockSignal

if TYPE_CHECKING:
    from onboarding.repositories.state_repo import FormStateRepo
    from onboarding.services.tools import ToolDispatcher

log = logging.getLogger(__name__)

_SILENCE_POLL_SEC = 2.0  # silence monitor check interval


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
        repo: "FormStateRepo",
        tool_dispatcher: "ToolDispatcher | None" = None,
        replay_context: str | None = None,
    ) -> None:
        self._ws = websocket
        self._session_id = session_id
        self._system_instruction = system_instruction
        self._repo = repo
        self._tools = tool_dispatcher
        self._replay_context = replay_context
        self._turn_id = 0
        self._last_screen_hash: str | None = None
        self._last_audio_at: float = 0.0
        self._gemini_is_speaking: bool = False
        # Voice protocol — preserve the words Gemini was saying when interrupted
        # so the next turn can address the interruption AND the unfinished thought.
        # Injected as a hidden [INTERRUPTED] text turn right after the cut-off.
        self._last_interrupted_intent: str | None = None
        # Silence watchdog — two-step protocol. _silence_warned flips True after
        # the first "still there?" check-in; the second timeout then summarises
        # pending fields. Reset to False on any new user audio.
        self._silence_warned: bool = False
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
            len(FUNCTION_DECLS) if tool_dispatcher else 0,
            "yes" if replay_context else "no",
        )

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
            compression_cfg = types.ContextWindowCompressionConfig(
                sliding_window=types.SlidingWindow()
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
                FUNCTION_DECLS if settings.onboarding_grounding_enabled
                else [*FUNCTION_DECLS, POLICY_BLOCK_DECL],
                grounding_enabled=settings.onboarding_grounding_enabled,
            ) if self._tools else None,
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
                    silence_duration_ms=1000,
                ),
                activity_handling=types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
                turn_coverage=types.TurnCoverage.TURN_INCLUDES_ONLY_ACTIVITY,
            ),
            session_resumption=types.SessionResumptionConfig(handle=None),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            input_audio_transcription=types.AudioTranscriptionConfig(),
        )

        async with client.aio.live.connect(
            model=settings.gemini_live_model_id, config=config
        ) as session:
            log.info("gemini_connected session=%s model=%s", self._session_id, settings.gemini_live_model_id)
            # Phase E — inject replay context so model continues without reintroducing
            if self._replay_context:
                await session.send_realtime_input(text=self._replay_context)
                log.debug("replay_context_injected session=%s", self._session_id)
            self._last_audio_at = time.monotonic()
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
                    # User is talking — clear the silence watchdog state so a
                    # later silence triggers the FIRST-step warn again, not the
                    # SECOND-step summary.
                    self._silence_warned = False
                    # Send all audio unconditionally — Gemini's VAD + START_OF_ACTIVITY_INTERRUPTS
                    # handles barge-in natively. The old _agent_speaking echo gate blocked user
                    # audio after turn N+1 model audio arrived, causing VAD to stop firing.
                    await session.send_realtime_input(
                        audio=types.Blob(data=raw_bytes, mime_type="audio/pcm;rate=16000")
                    )
                    total_chunks += 1
                    if total_chunks % 50 == 0:
                        log.info("audio_streaming chunks=%d session=%s", total_chunks, self._session_id)

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

        elif msg_type == "screen_state":
            await self._handle_screen_state(session, data, version=1)

        elif msg_type == "screen_state_v2":
            await self._handle_screen_state(session, data, version=2)

        elif msg_type == "stop":
            log.info("client_stop session=%s", self._session_id)
            return True

        # "start" arrives before run() — safe to ignore here if it slips through
        return False

    async def _handle_screen_state(
        self, session: "genai.live.AsyncSession", data: dict, *, version: int = 1
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
            log.debug("screen_state_duplicate_dropped session=%s version=%d", self._session_id, version)
            return

        try:
            if version == 2:
                v2_msg = ScreenStateV2Message(type="screen_state_v2", data=raw_data)
                state_v2 = v2_msg.data
            else:
                v1_msg = ScreenStateMessage(type="screen_state", data=raw_data)
                state_v2 = from_v1(v1_msg, session_step_id=None)
        except ValidationError as exc:
            log.warning("screen_state_invalid session=%s version=%d error=%s",
                        self._session_id, version, exc)
            await self._ws.send_text(
                json.dumps({"type": "error", "code": "screen_state_invalid",
                            "message": str(exc)})
            )
            return

        self._last_screen_hash = h
        injection = render_injection_text(state_v2)
        log.debug("screen_state_inject session=%s version=%d", self._session_id, version)
        await session.send_realtime_input(text=injection)

        if settings.debug:
            await self._ws.send_text(json.dumps({"type": "screen_state_ack", "accepted": True, "version": version}))

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
                    # ── Tool calls (Phase C) — handled before server_content ──
                    if self._tools and getattr(msg, "tool_call", None):
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
                                        # NOTE: Do NOT send audio_stream_end=True here.
                                        # Per Gemini Live API: audio_stream_end means
                                        # "microphone turned off / stream closed" — it
                                        # signals session-level end-of-input, not a
                                        # mid-conversation flush. Sending it on every
                                        # turn corrupts VAD state and causes Gemini to
                                        # mis-handle subsequent user audio. Echo must
                                        # be solved on the client (Flutter mic mute).
                                    await self._ws.send_bytes(part.inline_data.data)
                                    chunk_count += 1

                        # ── Interruption (user spoke over the agent) ───────────
                        if sc.interrupted:
                            log.info("interrupted turn=%d chunks_before=%d session=%s",
                                     self._turn_id, chunk_count, self._session_id)
                            interrupted_intent: str | None = None
                            if agent_transcript_buf:
                                full_text = "".join(agent_transcript_buf)
                                interrupted_intent = full_text.strip() or None
                                log.info("AGENT_SAID(interrupted) %r session=%s", full_text, self._session_id)
                                await self._ws.send_text(json.dumps({"type": "agent_said", "text": full_text}))
                                await self._repo.append_transcript(
                                    self._session_id,
                                    {"speaker": "agent", "text": full_text, "turn_id": self._turn_id},
                                    ttl_sec=settings.session_max_sec,
                                )
                                agent_transcript_buf.clear()
                            await self._ws.send_text(json.dumps({"type": "interrupted"}))
                            turn_started = False
                            chunk_count = 0
                            self._gemini_is_speaking = False

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
                                            f"\"{interrupted_intent}\". "
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
                                log.info("AGENT_SAID %r session=%s", full_text, self._session_id)
                                await self._ws.send_text(json.dumps({"type": "agent_said", "text": full_text}))
                                await self._repo.append_transcript(
                                    self._session_id,
                                    {"speaker": "agent", "text": full_text, "turn_id": self._turn_id},
                                    ttl_sec=settings.session_max_sec,
                                )
                                agent_transcript_buf.clear()
                            await self._ws.send_text(json.dumps({"type": "turn_complete"}))
                            log.info("turn_complete chunks=%d turn=%d session=%s",
                                     chunk_count, self._turn_id, self._session_id)
                            self._turn_id += 1
                            chunk_count = 0
                            turn_started = False
                            self._gemini_is_speaking = False
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
                                self._session_id, gemini_handle,
                            )

                    # ── GoAway — Gemini about to close the connection ──────────
                    # Forward to the client so the Flutter app can proactively
                    # call the resume endpoint before the drop becomes a hard
                    # disconnect.  Without this the client sees a silent audio
                    # gap with no indication a reconnect is needed.
                    if msg.go_away:
                        time_left = msg.go_away.time_left
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
                await asyncio.sleep(0.01)
                continue

        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        except Exception:
            log.exception("g2b_error session=%s", self._session_id)

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
                if elapsed < settings.onboarding_silence_timeout_sec or self._gemini_is_speaking:
                    continue

                if not self._silence_warned:
                    # First fire — gentle "are you still there?" cue.
                    log.info(
                        "silence_watchdog fired threshold=%.0fs step=warn session=%s",
                        elapsed, self._session_id,
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
                        elapsed, len(pending_labels), self._session_id,
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
                try:
                    await session.send_realtime_input(text=cue)
                except Exception:
                    pass
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
                section_values = state.values.get(section.id) or ({} if not section.is_repeatable else [])
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
        tool_call: "types.LiveServerToolCall",
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
            responses.append(
                types.FunctionResponse(
                    id=call.id,
                    name=call.name,
                    response=result,
                )
            )

        await session.send_tool_response(function_responses=responses)
