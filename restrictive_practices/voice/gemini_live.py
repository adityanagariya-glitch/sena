"""
Gemini Live session wrapper for the case-note voice WebSocket endpoint.

Ported from sena-ai/services/onboarding/src/onboarding/services/gemini_live.py
with three import rewires and setting-name updates.

Audio formats:
  In  — raw PCM16, little-endian, 16 kHz mono  (MIME: audio/pcm;rate=16000)
  Out — raw PCM16, little-endian, 24 kHz mono  (client upsamples if needed)
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import time
from typing import TYPE_CHECKING

from fastapi import WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types

from config import settings
from voice.grounding import build_live_tools
from voice.screen_context import (
    ScreenStateMessage,
    ScreenStateV2Message,
    from_v1,
    payload_hash,
    render_injection_text,
)
from voice.tools import FUNCTION_DECLS, POLICY_BLOCK_DECL, PolicyBlockSignal

if TYPE_CHECKING:
    from voice.state_repo import VoiceStateRepo
    from voice.tools import ToolDispatcher

import structlog

log = structlog.get_logger(__name__)

_SILENCE_POLL_SEC = 2.0


class GeminiLiveSession:
    """
    Bridges a single Gemini Live connection to an app/browser WebSocket.

    Lifecycle:
      1. Caller awaits run()
      2. run() opens the Gemini connection, starts b2g + g2b tasks
      3. Blocks on b2g — returns when client disconnects or sends {"type":"stop"}
      4. Cancels g2b, cleans up

    The WS lock is NOT managed here — voice_routes.py acquires/releases it.
    """

    def __init__(
        self,
        websocket: WebSocket,
        session_id: str,
        system_instruction: str,
        repo: VoiceStateRepo,
        tool_dispatcher: ToolDispatcher | None = None,
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
        self._last_interrupted_intent: str | None = None
        self._silence_warned: bool = False
        self._silence_exhausted: bool = False
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

    # ── Public ────────────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Open Gemini connection and bridge until the client disconnects."""
        client = genai.Client(api_key=settings.gemini_api_key)

        compression_cfg = None
        try:
            compression_cfg = types.ContextWindowCompressionConfig(
                sliding_window=types.SlidingWindow()
            )
        except (AttributeError, TypeError):
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
            speech_config=types.SpeechConfig(
                language_code="en-AU",
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Aoede")
                ),
            ),
            tools=build_live_tools(
                FUNCTION_DECLS if settings.voice_grounding_enabled
                else [*FUNCTION_DECLS, POLICY_BLOCK_DECL],
                grounding_enabled=settings.voice_grounding_enabled,
            ) if self._tools else None,
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    disabled=False,
                    start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_LOW,
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
                    prefix_padding_ms=200,
                    silence_duration_ms=3000,
                ),
                activity_handling=types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
                turn_coverage=types.TurnCoverage.TURN_INCLUDES_ONLY_ACTIVITY,
            ),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            input_audio_transcription=types.AudioTranscriptionConfig(),
        )

        async with client.aio.live.connect(
            model=settings.gemini_live_model_id, config=config
        ) as session:
            log.info(
                "gemini_connected session=%s model=%s",
                self._session_id,
                settings.gemini_live_model_id,
            )
            if self._replay_context:
                await session.send_realtime_input(text=self._replay_context)
                log.debug("replay_context_injected session=%s", self._session_id)
            self._last_audio_at = time.monotonic()
            b2g = asyncio.create_task(self._browser_to_gemini(session))
            g2b = asyncio.create_task(self._gemini_to_browser(session))
            silence = asyncio.create_task(self._silence_monitor(session))
            g2b.add_done_callback(lambda _t: b2g.cancel())
            try:
                await b2g
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
                    self._silence_warned = False
                    self._silence_exhausted = False
                    await session.send_realtime_input(
                        audio=types.Blob(data=raw_bytes, mime_type="audio/pcm;rate=16000")
                    )
                    total_chunks += 1
                    if total_chunks % 50 == 0:
                        log.info(
                            "audio_streaming chunks=%d session=%s",
                            total_chunks,
                            self._session_id,
                        )

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
            await session.send_realtime_input(audio_stream_end=True)

        elif msg_type == "screen_state":
            await self._handle_screen_state(session, data, version=1)

        elif msg_type == "screen_state_v2":
            await self._handle_screen_state(session, data, version=2)

        elif msg_type == "validation_failed":
            await self._handle_validation_failed(session, data)

        elif msg_type == "validation_cleared":
            await self._handle_validation_cleared(data)

        elif msg_type == "stop":
            log.info("client_stop session=%s", self._session_id)
            return True

        return False

    async def _handle_validation_failed(
        self, session: genai.live.AsyncSession, data: dict
    ) -> None:
        """Flutter reports a client-side validation rejection."""
        section_id = data.get("section_id", "")
        field_id = data.get("field_id", "")
        repeatable_index = data.get("repeatable_index")
        reason_human = data.get("reason_human", "The value was not accepted.")
        code = data.get("code", "client_validation_failed")

        if not section_id or not field_id:
            log.warning(
                "validation_failed missing section/field session=%s", self._session_id
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
        await self._repo.save_state(state, ttl_sec=settings.voice_session_max_sec)

        loc = f"{section_id}.{field_id}"
        if repeatable_index is not None:
            loc += f"[{repeatable_index}]"
        injection = (
            f"[SCREEN VALIDATION] The screen rejected the value stored for {loc}: "
            f"{reason_human} — re-ask the worker for a corrected value (Rule 7)."
        )
        await session.send_realtime_input(audio_stream_end=True)
        await session.send_realtime_input(text=injection)
        log.info(
            "validation_failed_injected session=%s loc=%s code=%s",
            self._session_id,
            loc,
            code,
        )

    async def _handle_validation_cleared(self, data: dict) -> None:
        """Flutter reports a validation error has been resolved."""
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
        await self._repo.save_state(state, ttl_sec=settings.voice_session_max_sec)
        log.info(
            "validation_cleared session=%s section=%s field=%s",
            self._session_id,
            section_id,
            field_id,
        )

    async def _handle_screen_state(
        self, session: genai.live.AsyncSession, data: dict, *, version: int = 1
    ) -> None:
        """Validate, deduplicate, and inject a screen_state message as a Gemini text turn."""
        from pydantic import ValidationError

        raw_data = data.get("data", {})
        h = payload_hash(raw_data)
        if h == self._last_screen_hash:
            log.debug(
                "screen_state_duplicate_dropped session=%s version=%d",
                self._session_id,
                version,
            )
            return

        try:
            if version == 2:
                v2_msg = ScreenStateV2Message(type="screen_state_v2", data=raw_data)
                state_v2 = v2_msg.data
            else:
                v1_msg = ScreenStateMessage(type="screen_state", data=raw_data)
                state_v2 = from_v1(v1_msg, session_step_id=None)
        except ValidationError as exc:
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
            )
            return

        self._last_screen_hash = h
        injection = render_injection_text(state_v2)
        log.debug("screen_state_inject session=%s version=%d", self._session_id, version)
        await session.send_realtime_input(text=injection)

        if state_v2.field_errors:
            state_fv = await self._repo.get_state(self._session_id)
            if state_fv is not None:
                for dotted_path, reason_human in state_v2.field_errors.items():
                    parts = dotted_path.split(".", 1)
                    if len(parts) != 2:
                        continue
                    sec, fld = parts
                    key = (sec, fld, None)
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
                await self._repo.save_state(state_fv, ttl_sec=settings.voice_session_max_sec)

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

    # ── Private: Gemini → client ──────────────────────────────────────────────

    async def _gemini_to_browser(self, session: genai.live.AsyncSession) -> None:
        """Forward Gemini audio and transcript events → client."""
        chunk_count = 0
        turn_started = False
        loop_iter = 0
        agent_transcript_buf: list[str] = []

        try:
            while True:
                loop_iter += 1
                async for msg in session.receive():
                    if self._tools and getattr(msg, "tool_call", None):
                        await self._handle_tool_call(session, msg.tool_call)
                        if self._tools.step_completed:
                            continue

                    sc = msg.server_content

                    if sc:
                        if sc.input_transcription and sc.input_transcription.text:
                            txt = sc.input_transcription.text
                            log.info("USER_SAID %r session=%s", txt, self._session_id)
                            await self._ws.send_text(
                                json.dumps({"type": "user_said", "text": txt})
                            )
                            await self._repo.append_transcript(
                                self._session_id,
                                {"speaker": "user", "text": txt, "turn_id": self._turn_id},
                                ttl_sec=settings.voice_session_max_sec,
                            )

                        if sc.output_transcription and sc.output_transcription.text:
                            agent_transcript_buf.append(sc.output_transcription.text)

                        if sc.model_turn:
                            for part in sc.model_turn.parts:
                                if part.inline_data:
                                    if not turn_started:
                                        await self._ws.send_text(
                                            json.dumps({"type": "turn_start"})
                                        )
                                        turn_started = True
                                        self._gemini_is_speaking = True
                                    await self._ws.send_bytes(part.inline_data.data)
                                    chunk_count += 1

                        if sc.interrupted:
                            log.info(
                                "interrupted turn=%d chunks_before=%d session=%s",
                                self._turn_id,
                                chunk_count,
                                self._session_id,
                            )
                            interrupted_intent: str | None = None
                            if agent_transcript_buf:
                                full_text = "".join(agent_transcript_buf)
                                interrupted_intent = full_text.strip() or None
                                log.info(
                                    "AGENT_SAID(interrupted) %r session=%s",
                                    full_text,
                                    self._session_id,
                                )
                                await self._ws.send_text(
                                    json.dumps({"type": "agent_said", "text": full_text})
                                )
                                await self._repo.append_transcript(
                                    self._session_id,
                                    {
                                        "speaker": "agent",
                                        "text": full_text,
                                        "turn_id": self._turn_id,
                                    },
                                    ttl_sec=settings.voice_session_max_sec,
                                )
                                agent_transcript_buf.clear()
                            await self._ws.send_text(json.dumps({"type": "interrupted"}))
                            turn_started = False
                            chunk_count = 0
                            self._gemini_is_speaking = False
                            self._last_audio_at = time.monotonic()

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

                        if sc.turn_complete:
                            if agent_transcript_buf:
                                full_text = "".join(agent_transcript_buf)
                                log.info(
                                    "AGENT_SAID %r session=%s", full_text, self._session_id
                                )
                                await self._ws.send_text(
                                    json.dumps({"type": "agent_said", "text": full_text})
                                )
                                await self._repo.append_transcript(
                                    self._session_id,
                                    {
                                        "speaker": "agent",
                                        "text": full_text,
                                        "turn_id": self._turn_id,
                                    },
                                    ttl_sec=settings.voice_session_max_sec,
                                )
                                agent_transcript_buf.clear()
                            await self._ws.send_text(json.dumps({"type": "turn_complete"}))
                            log.info(
                                "turn_complete chunks=%d turn=%d session=%s",
                                chunk_count,
                                self._turn_id,
                                self._session_id,
                            )
                            self._turn_id += 1
                            chunk_count = 0
                            turn_started = False
                            self._gemini_is_speaking = False
                            self._last_audio_at = time.monotonic()
                            if self._tools:
                                self._tools.set_turn_id(self._turn_id)
                            if self._tools and self._tools.step_completed:
                                return

                    resumption_update = getattr(msg, "session_resumption_update", None)
                    if resumption_update:
                        gemini_handle = getattr(
                            resumption_update, "resumable_session_handle", None
                        )
                        if gemini_handle:
                            log.debug(
                                "gemini_session_handle_updated session=%s handle=%.12s…",
                                self._session_id,
                                gemini_handle,
                            )

                    if msg.go_away:
                        time_left = msg.go_away.time_left
                        log.warning(
                            "go_away time_left=%s session=%s", time_left, self._session_id
                        )
                        with contextlib.suppress(Exception):
                            ms: int = 0
                            if time_left is not None:
                                with contextlib.suppress(Exception):
                                    ms = int(time_left.total_seconds() * 1000)
                            await self._ws.send_text(
                                json.dumps({"type": "go_away", "time_left_ms": ms})
                            )

                log.debug(
                    "g2b_recv_iter_end loop=%d session=%s", loop_iter, self._session_id
                )
                await asyncio.sleep(0.01)
                continue

        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        except Exception:
            log.exception("g2b_error session=%s", self._session_id)

    # ── Private: silence monitor ──────────────────────────────────────────────

    async def _silence_monitor(self, session: genai.live.AsyncSession) -> None:
        """
        Two-step silence watchdog.
        Set SENA_AI_VOICE_SILENCE_TIMEOUT_SEC=0 to disable.
        """
        if settings.voice_silence_timeout_sec <= 0:
            return
        try:
            while True:
                await asyncio.sleep(_SILENCE_POLL_SEC)
                elapsed = time.monotonic() - self._last_audio_at
                if (
                    elapsed < settings.voice_silence_timeout_sec
                    or self._gemini_is_speaking
                    or self._silence_exhausted
                ):
                    continue

                if not self._silence_warned:
                    log.info(
                        "silence_watchdog fired threshold=%.0fs step=warn session=%s",
                        elapsed,
                        self._session_id,
                    )
                    cue = (
                        "[SILENCE TIMEOUT] The worker has been silent. "
                        "Check in warmly in Australian English, e.g. "
                        "'Hey, just checking — are you still there? No rush at all, "
                        "take your time.'"
                    )
                    self._silence_warned = True
                else:
                    pending_labels = await self._collect_pending_required_labels()
                    log.info(
                        "silence_watchdog fired threshold=%.0fs step=summary "
                        "pending=%d session=%s",
                        elapsed,
                        len(pending_labels),
                        self._session_id,
                    )
                    if pending_labels:
                        joined = ", ".join(pending_labels[:6])
                        cue = (
                            "[SILENCE TIMEOUT — SUMMARY] The worker is still "
                            "silent. Gently summarise what's left, then offer to "
                            "continue. For example: 'When you're ready, we still "
                            f"need: {joined}. No rush — just let me know when you "
                            "want to keep going.'"
                        )
                    else:
                        cue = (
                            "[SILENCE TIMEOUT — SUMMARY] The worker is still "
                            "silent. Reassure them you're here whenever they're "
                            "ready, in Australian English."
                        )
                    self._silence_exhausted = True
                with contextlib.suppress(Exception):
                    await session.send_realtime_input(text=cue)
                self._last_audio_at = time.monotonic()
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("silence_monitor_error session=%s", self._session_id)

    async def _collect_pending_required_labels(self) -> list[str]:
        """Return labels of required fields still empty — used by silence summary."""
        try:
            state = await self._repo.get_state(self._session_id)
            schema = await self._repo.get_schema(self._session_id)
            if state is None or schema is None:
                return []
            pending: list[str] = []
            for section in schema.sections:
                default_val = {} if not section.is_repeatable else []
                section_values = state.values.get(section.id) or default_val
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

    # ── Private: tool_call handling ───────────────────────────────────────────

    async def _handle_tool_call(
        self,
        session: genai.live.AsyncSession,
        tool_call: types.LiveServerToolCall,
    ) -> None:
        """Dispatch every function call in a tool_call batch and send tool response."""
        assert self._tools is not None

        function_calls = getattr(tool_call, "function_calls", None) or []
        if not function_calls:
            return

        responses: list[types.FunctionResponse] = []
        for call in function_calls:
            args_dict = dict(call.args) if call.args else {}
            try:
                result = await self._tools.dispatch(call.name, args_dict)
            except PolicyBlockSignal as exc:
                log.info(
                    "policy_block_signal question=%r session=%s",
                    exc.question,
                    self._session_id,
                )
                await self._ws.send_text(
                    json.dumps(
                        {
                            "type": "error",
                            "code": "policy_block",
                            "message": (
                                "This question requires current policy data. "
                                "Please re-ask with Google Search grounding enabled."
                            ),
                        }
                    )
                )
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
