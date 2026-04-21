"""
WebSocket route — Phase B: Gemini Live voice session for onboarding.

Endpoint: WSS /ws/onboarding/{session_id}

Protocol summary:
  Client → Server:
    Binary frames       — raw PCM16 16 kHz mono audio (continuous stream)
    {"type":"start"}    — first text frame; opens the Gemini connection
    {"type":"user_text","text":"..."} — typed input alternative
    {"type":"audio_end"}              — signal end-of-utterance (flush)
    {"type":"stop"}                   — client-initiated graceful close

  Server → Client:
    {"type":"ready","state":{...},"prompt_version":"v1"}  — session live
    Binary frames       — raw PCM16 24 kHz mono audio from Gemini
    {"type":"turn_start"}             — Gemini began speaking
    {"type":"turn_complete"}          — Gemini finished turn
    {"type":"interrupted"}            — user interrupted agent
    {"type":"user_said","text":"..."}  — input transcription
    {"type":"agent_said","text":"..."} — output transcription
    {"type":"error","code":"...","message":"..."} — errors

WS lock semantics: exactly one active WS per session_id at a time.
A second connection attempt receives {"type":"error","code":"session_locked"} + close 4009.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from onboarding.api.deps import get_repo
from onboarding.core.settings import settings
from onboarding.repositories.state_repo import FormStateRepo
from onboarding.services.gemini_live import GeminiLiveSession
from onboarding.services.prompt_builder import build_system_prompt
from onboarding.services.tools import ToolDispatcher

log = logging.getLogger(__name__)

ws_router = APIRouter()


@ws_router.websocket("/ws/onboarding/{session_id}")
async def onboarding_ws(
    websocket: WebSocket,
    session_id: str,
    repo: FormStateRepo = Depends(get_repo),
) -> None:
    await websocket.accept()
    log.info("ws_connect session=%s", session_id)

    # ── 1. Load state + schema from Redis ─────────────────────────────────────
    state = await repo.get_state(session_id)
    if state is None:
        await _close_with_error(websocket, "session_not_found", "Session not found or expired", 4004)
        return

    schema = await repo.get_schema(session_id)
    if schema is None:
        await _close_with_error(websocket, "schema_not_found",
                                "Session schema missing — recreate the session", 4004)
        return

    # ── 2. Acquire single-writer WS lock ──────────────────────────────────────
    acquired = await repo.acquire_ws_lock(session_id, ttl_sec=settings.session_max_sec)
    if not acquired:
        await _close_with_error(websocket, "session_locked",
                                "Another voice connection is already active for this session", 4009)
        return

    try:
        # ── 3. Wait for the "start" handshake ─────────────────────────────────
        # The client must send {"type":"start"} before streaming any audio.
        # This allows it to optionally include a resumption_handle (Phase E).
        try:
            raw = await websocket.receive_text()
            start_msg = json.loads(raw)
        except WebSocketDisconnect:
            return
        except json.JSONDecodeError:
            await _close_with_error(websocket, "protocol_error",
                                    'Expected {"type":"start"} as first message', 4008)
            return

        if start_msg.get("type") != "start":
            await _close_with_error(websocket, "protocol_error",
                                    'Expected {"type":"start"} as first message', 4008)
            return

        # ── 4. Send "ready" with current form state ────────────────────────────
        await websocket.send_text(json.dumps({
            "type": "ready",
            "state": json.loads(state.model_dump_json()),
            "prompt_version": "v1",
        }))

        # ── 5. Build system prompt + tool dispatcher + run Gemini bridge ─────
        system_instruction = build_system_prompt(schema, state)

        tool_dispatcher = ToolDispatcher(
            websocket=websocket,
            session_id=session_id,
            repo=repo,
            schema=schema,
        )

        live_session = GeminiLiveSession(
            websocket=websocket,
            session_id=session_id,
            system_instruction=system_instruction,
            repo=repo,
            tool_dispatcher=tool_dispatcher,
        )
        await live_session.run()

    except WebSocketDisconnect:
        log.info("ws_disconnect session=%s", session_id)
    except Exception:
        log.exception("ws_unhandled_error session=%s", session_id)
        try:
            await websocket.send_text(json.dumps({
                "type": "error",
                "code": "internal_error",
                "message": "Internal server error",
            }))
        except Exception:
            pass
    finally:
        # Always release the WS lock so the session can be resumed
        await repo.release_ws_lock(session_id)
        log.info("ws_lock_released session=%s", session_id)
        try:
            await websocket.close()
        except Exception:
            pass


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _close_with_error(
    websocket: WebSocket,
    code: str,
    message: str,
    ws_code: int,
) -> None:
    try:
        await websocket.send_text(json.dumps({"type": "error", "code": code, "message": message}))
        await websocket.close(code=ws_code)
    except Exception:
        pass
