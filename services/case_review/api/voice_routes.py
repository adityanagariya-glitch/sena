"""
Voice assistant routes for the restrictive-practices case-note form.

POST /v1/restrictive-practices/voice/session  — create a session
WSS  /v1/restrictive-practices/voice/ws/{session_id}?token=<token> — bridge
"""
from __future__ import annotations

import contextlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket
from pydantic import BaseModel

from config import settings
from voice.gemini_live import GeminiLiveSession
from voice.prompt_builder import build_system_prompt
from voice.resumption import build_replay_context as _build_replay_context
from voice.schema import build_case_note_schema
from voice.session_bootstrap import SessionBootstrap
from voice.state import CaseNoteVoiceState
from voice.state_repo import VoiceStateRepo
from voice.tools import ToolDispatcher

log = structlog.get_logger(__name__)

voice_router = APIRouter(prefix="/v1/restrictive-practices/voice", tags=["voice"])

# ── Dependency: Redis repo ────────────────────────────────────────────────────

_repo: VoiceStateRepo | None = None


def get_voice_repo() -> VoiceStateRepo:
    if _repo is None:
        raise HTTPException(status_code=503, detail="Voice Redis repo not initialised")
    return _repo


def set_voice_repo(repo: VoiceStateRepo) -> None:
    global _repo
    _repo = repo


# ── Request / response models ─────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    case_note_id: str
    worker_id: str
    client_id: str
    tenant_id: str | None = None
    initial_values: dict[str, Any] = {}
    readonly_paths: list[str] = []
    worker_display_name: str | None = None


class CreateSessionResponse(BaseModel):
    session_id: str
    ws_url: str
    expires_at: str


# ── Auth helper (reuse Basic-auth logic from routes.py) ───────────────────────

def _require_auth_voice(request: Request) -> None:
    import os
    import secrets as _secrets
    expected_user = os.getenv("SENA_AI_BASIC_AUTH_USER", "")
    expected_pass = os.getenv("SENA_AI_BASIC_AUTH_PASSWORD", "")
    if not expected_user or not expected_pass:
        return
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Basic "):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )
    import base64
    try:
        decoded = base64.b64decode(auth[6:]).decode("utf-8")
        username, _, password = decoded.partition(":")
    except Exception:
        raise HTTPException(status_code=401, detail="Unauthorized",
                            headers={"WWW-Authenticate": "Basic"})
    user_ok = _secrets.compare_digest(username.encode(), expected_user.encode())
    pass_ok = _secrets.compare_digest(password.encode(), expected_pass.encode())
    if not (user_ok and pass_ok):
        raise HTTPException(status_code=401, detail="Unauthorized",
                            headers={"WWW-Authenticate": "Basic"})


# ── POST /voice/session ───────────────────────────────────────────────────────

@voice_router.post("/session", response_model=CreateSessionResponse)
async def create_voice_session(
    body: CreateSessionRequest,
    request: Request,
    repo: VoiceStateRepo = Depends(get_voice_repo),
) -> CreateSessionResponse:
    _require_auth_voice(request)

    session_id = str(uuid.uuid4())
    token = str(uuid.uuid4())

    schema = build_case_note_schema()

    state = CaseNoteVoiceState(
        session_id=session_id,
        case_note_id=body.case_note_id,
        worker_id=body.worker_id,
        client_id=body.client_id,
        tenant_id=body.tenant_id,
    )

    for section_id, fields in body.initial_values.items():
        if not isinstance(fields, dict):
            continue
        for field_id, raw_value in fields.items():
            value = raw_value.get("value") if isinstance(raw_value, dict) else raw_value
            if value is not None:
                state.set_field(
                    section_id,
                    field_id,
                    value,
                    source="prefill",
                    confidence=1.0,
                    turn_id=0,
                )

    state.recompute_completion(schema)

    bootstrap = SessionBootstrap.from_initial_values(
        body.initial_values,
        readonly_paths=body.readonly_paths,
        worker_display_name=body.worker_display_name,
    )

    ttl = settings.voice_session_max_sec
    await repo.create_session(state, schema, ttl, bootstrap=bootstrap, token=token)

    scheme = "wss" if request.url.scheme == "https" else "ws"
    host = request.headers.get("host", request.url.netloc)
    ws_url = f"{scheme}://{host}/v1/restrictive-practices/voice/ws/{session_id}?token={token}"

    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=ttl)
    ).isoformat()

    log.info(
        "voice_session_created session=%s worker=%s client=%s",
        session_id,
        body.worker_id,
        body.client_id,
    )
    return CreateSessionResponse(
        session_id=session_id,
        ws_url=ws_url,
        expires_at=expires_at,
    )


# ── WSS /voice/ws/{session_id} ────────────────────────────────────────────────

@voice_router.websocket("/ws/{session_id}")
async def voice_websocket(
    websocket: WebSocket,
    session_id: str,
    token: str = Query(...),
    repo: VoiceStateRepo = Depends(get_voice_repo),
) -> None:
    await websocket.accept()

    # Token validation
    stored_token = await repo.get_token(session_id)
    if stored_token is None or stored_token != token:
        log.warning("voice_ws_invalid_token session=%s", session_id)
        await websocket.close(4011)
        return

    # WS lock — reject concurrent connections on the same session
    lock_acquired = await repo.acquire_ws_lock(session_id, ttl_sec=settings.voice_session_max_sec)
    if not lock_acquired:
        log.warning("voice_ws_already_connected session=%s", session_id)
        await websocket.close(4009)
        return

    try:
        state = await repo.get_state(session_id)
        schema = await repo.get_schema(session_id)
        bootstrap = await repo.get_bootstrap(session_id)

        if state is None or schema is None:
            log.warning("voice_ws_session_not_found session=%s", session_id)
            await websocket.close(4004)
            return

        transcript = await repo.get_transcript(session_id)
        replay_ctx = _build_replay_context(transcript, last_n=10) or None

        system_prompt = build_system_prompt(
            schema,
            state,
            grounding_enabled=settings.voice_grounding_enabled,
            bootstrap=bootstrap,
        )

        async def _emit(event: dict) -> None:
            import json
            try:
                await websocket.send_text(json.dumps(event))
            except Exception:
                pass

        dispatcher = ToolDispatcher(
            websocket=websocket,
            session_id=session_id,
            repo=repo,
            schema=schema,
            emit=_emit,
        )

        bridge = GeminiLiveSession(
            websocket=websocket,
            session_id=session_id,
            system_instruction=system_prompt,
            repo=repo,
            tool_dispatcher=dispatcher,
            replay_context=replay_ctx,
        )

        log.info("voice_ws_connected session=%s", session_id)
        await bridge.run()

    except Exception as exc:
        log.exception("voice_ws_error session=%s", session_id)
        import json as _json
        import traceback as _tb
        with contextlib.suppress(Exception):
            await websocket.send_text(_json.dumps({
                "type": "error",
                "code": "internal_error",
                "message": str(exc),
                "detail": _tb.format_exc()[-1000:],
            }))
    finally:
        await repo.release_ws_lock(session_id)
        log.info("voice_ws_disconnected session=%s", session_id)
