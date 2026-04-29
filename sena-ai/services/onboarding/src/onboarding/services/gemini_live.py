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
import json
import logging
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

    # ── Public ────────────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Open Gemini connection and bridge until the client disconnects."""
        client = genai.Client(api_key=settings.gemini_api_key)

        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=types.Content(
                parts=[types.Part(text=self._system_instruction)],
            ),
            # Lock TTS to English via a named prebuilt voice. Without this,
            # native-audio models auto-detect language from the first utterance —
            # ambiguous/quiet audio was being transcribed as Japanese ("はい").
            # SpeechConfig.language_code is absent in this SDK version (Pydantic
            # model forbids extra fields); voice selection is the supported path.
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Aoede")
                )
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
                    start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_LOW,
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
                    prefix_padding_ms=200,
                    silence_duration_ms=800,
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
            b2g = asyncio.create_task(self._browser_to_gemini(session))
            g2b = asyncio.create_task(self._gemini_to_browser(session))
            # If g2b exits first (e.g. advance_step closes the step), unblock b2g
            g2b.add_done_callback(lambda _t: b2g.cancel())
            try:
                await b2g  # blocks until client disconnects, stop, or step done
            except asyncio.CancelledError:
                pass
            finally:
                g2b.cancel()
                await asyncio.gather(g2b, return_exceptions=True)
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
                        if sc.output_transcription and sc.output_transcription.text:
                            txt = sc.output_transcription.text
                            log.info("AGENT_SAID %r session=%s", txt, self._session_id)
                            await self._ws.send_text(json.dumps({"type": "agent_said", "text": txt}))
                            await self._repo.append_transcript(
                                self._session_id,
                                {"speaker": "agent", "text": txt, "turn_id": self._turn_id},
                                ttl_sec=settings.session_max_sec,
                            )

                        # ── Audio output (PCM16 24 kHz chunks) ────────────────
                        if sc.model_turn:
                            for part in sc.model_turn.parts:
                                if part.inline_data:
                                    if not turn_started:
                                        await self._ws.send_text(json.dumps({"type": "turn_start"}))
                                        turn_started = True
                                    await self._ws.send_bytes(part.inline_data.data)
                                    chunk_count += 1

                        # ── Interruption (user spoke over the agent) ───────────
                        if sc.interrupted:
                            await self._ws.send_text(json.dumps({"type": "interrupted"}))
                            turn_started = False
                            chunk_count = 0

                        # ── Turn complete ──────────────────────────────────────
                        if sc.turn_complete:
                            await self._ws.send_text(json.dumps({"type": "turn_complete"}))
                            log.info("turn_complete chunks=%d turn=%d session=%s",
                                     chunk_count, self._turn_id, self._session_id)
                            self._turn_id += 1
                            chunk_count = 0
                            turn_started = False
                            if self._tools:
                                self._tools.set_turn_id(self._turn_id)
                            # Phase C — advance_step closed the step; end loop
                            # after the agent's farewell turn has flushed.
                            if self._tools and self._tools.step_completed:
                                return

                    # ── GoAway — Gemini about to close the connection ──────────
                    if msg.go_away:
                        log.warning("go_away time_left=%s session=%s",
                                    msg.go_away.time_left, self._session_id)

                # receive() iterator exhausted — re-enter for next turn
                log.debug("g2b_recv_iter_end loop=%d session=%s", loop_iter, self._session_id)
                await asyncio.sleep(0.01)
                continue

        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        except Exception:
            log.exception("g2b_error session=%s", self._session_id)

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
