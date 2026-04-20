from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from voice.api.deps import ai_session_factory, redis_client
from voice.core.settings import settings
from voice.repositories.voice_repo import VoiceRepository
from voice.services.auth_service import (
    AuthContext,
    get_auth_context_from_dev_headers,
    get_auth_context_from_jwt,
    require_roles,
)
from voice.services.gemini_live_service import GeminiLiveService
from voice.services.personal_details_service import (
    ALL_FIELDS,
    _compute_completeness,
    _compute_missing,
)
from voice.services.redis_service import RedisService

logger = logging.getLogger(__name__)

ws_router = APIRouter()
_repo = VoiceRepository()
_redis = RedisService(redis_client)


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------


def _auth_from_websocket(websocket: WebSocket) -> AuthContext:
    """Extract auth from WebSocket headers (preferred) or query params (fallback)."""
    h = websocket.headers
    q = websocket.query_params

    if settings.auth_mode == "jwt":
        raw = h.get("authorization") or q.get("token", "")
        token = raw if raw.startswith("Bearer ") else f"Bearer {raw}"
        return get_auth_context_from_jwt(token)

    return get_auth_context_from_dev_headers(
        x_tenant_id=h.get("x-tenant-id") or q.get("tenant_id"),
        x_user_id=h.get("x-user-id") or q.get("user_id"),
        x_user_role=h.get("x-user-role") or q.get("role"),
        x_staff_id=h.get("x-staff-id") or q.get("staff_id"),
    )


async def _ws_error(websocket: WebSocket, message: str) -> None:
    try:
        await websocket.send_text(json.dumps({"type": "error", "message": message}))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


@ws_router.websocket("/ws/personal-details/{session_id}")
async def personal_details_live(websocket: WebSocket, session_id: UUID) -> None:
    """
    Gemini Live audio WebSocket for the NDIS participant onboarding flow.

    Start a session first via ``POST /v1/voice/personal-details/session`` to get a
    ``session_id``, then connect here to stream audio.

    Client → Server frames:
      - **Binary**: raw PCM16 audio at 16 kHz mono
      - **Text JSON**: ``{"type": "end_session"}`` — gracefully end the session

    Server → Client frames:
      - **Binary**: raw PCM16 audio at 24 kHz from Gemini (play immediately)
      - **Text JSON** ``{"type": "fields_update", "fields": {...}, "missing_fields": [...], "completeness_score": 0.0}``
      - **Text JSON** ``{"type": "complete", "draft_id": "...", "fields": {...}, "completeness_score": 0.0, "missing_fields": [...]}``
      - **Text JSON** ``{"type": "error", "message": "..."}``

    Auth (dev_header mode): pass ``X-Tenant-ID``, ``X-User-ID``, ``X-User-Role`` headers
    or ``tenant_id``, ``user_id``, ``role`` query params.
    """
    await websocket.accept()

    # -- Auth --
    try:
        auth = _auth_from_websocket(websocket)
        require_roles(auth, {"support_worker", "manager", "admin"})
    except Exception:
        await _ws_error(websocket, "Unauthorized")
        await websocket.close(code=4001)
        return

    # -- Validate session --
    async with ai_session_factory() as db:
        session = await _repo.get_session_by_id(db, session_id)

    if session is None or session.status != "ACTIVE" or session.objective != "PERSONAL_DETAILS":
        await _ws_error(websocket, "Invalid or inactive session")
        await websocket.close(code=4004)
        return

    if str(session.tenant_id) != str(auth.tenant_id):
        await _ws_error(websocket, "Forbidden")
        await websocket.close(code=4003)
        return

    # -- Restore field state from Redis (supports reconnect mid-session) --
    redis_state = await _redis.load_session_state(str(session_id))
    initial_fields = redis_state.get("fields", dict(ALL_FIELDS))

    final_fields: dict = dict(initial_fields)

    # -- Run bidirectional Gemini Live pipeline --
    try:
        async with GeminiLiveService(initial_fields=initial_fields) as live:
            client_task = asyncio.create_task(
                _receive_from_client(websocket, live),
                name=f"ws_client_{session_id}",
            )
            gemini_task = asyncio.create_task(
                _send_from_gemini(websocket, live, session_id, redis_state),
                name=f"ws_gemini_{session_id}",
            )

            _done, pending = await asyncio.wait(
                [client_task, gemini_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

            final_fields = live.current_fields
            logger.info(
                "live_session_ended session_id=%s completeness=%.2f",
                session_id,
                _compute_completeness(final_fields),
            )

    except Exception:
        logger.exception("live_pipeline_error session_id=%s", session_id)
        await _ws_error(websocket, "Internal pipeline error")
        try:
            await websocket.close()
        except Exception:
            pass
        return

    # -- Persist final state + create personal details draft --
    try:
        result = await _finalize_session(session, session_id, final_fields)
        await websocket.send_text(
            json.dumps(
                {
                    "type": "complete",
                    "draft_id": str(result["draft_id"]),
                    "fields": result["fields"],
                    "completeness_score": result["completeness_score"],
                    "missing_fields": result["missing_fields"],
                }
            )
        )
    except Exception:
        logger.exception("finalize_error session_id=%s", session_id)
        await _ws_error(websocket, "Failed to save session data")

    try:
        await websocket.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _receive_from_client(websocket: WebSocket, live: GeminiLiveService) -> None:
    """Read binary audio frames from the client and forward to Gemini Live.
    Returns when the client sends ``end_session`` or disconnects."""
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            raw_bytes: bytes | None = message.get("bytes")
            if raw_bytes:
                await live.send_audio(raw_bytes)
            elif message.get("text"):
                data = json.loads(message["text"])
                if data.get("type") == "end_session":
                    return
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except Exception:
        logger.exception("ws_client_receive_error")


async def _send_from_gemini(
    websocket: WebSocket,
    live: GeminiLiveService,
    session_id: UUID,
    redis_state: dict,
) -> None:
    """Forward Gemini Live events to the client WebSocket.
    Persists field updates to Redis after each extraction."""
    try:
        async for event in live.receive_events():
            match event["type"]:
                case "audio":
                    await websocket.send_bytes(event["data"])
                case "fields_update":
                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "fields_update",
                                "fields": event["fields"],
                                "missing_fields": event["missing_fields"],
                                "completeness_score": event["completeness_score"],
                            }
                        )
                    )
                    # Persist incrementally so reconnects resume with latest state
                    await _redis.save_session_state(
                        str(session_id),
                        {
                            **redis_state,
                            "fields": event["fields"],
                            "missing_fields": event["missing_fields"],
                            "completeness_score": event["completeness_score"],
                        },
                    )
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except Exception:
        logger.exception("gemini_receive_error session_id=%s", session_id)


async def _finalize_session(session: object, session_id: UUID, final_fields: dict) -> dict:
    """Write personal details draft to DB and mark session complete."""
    missing = _compute_missing(final_fields)
    score = _compute_completeness(final_fields)
    ended_at = datetime.now(timezone.utc)

    async with ai_session_factory() as db:
        draft = await _repo.create_personal_details_draft(
            db=db,
            tenant_id=session.tenant_id,  # type: ignore[attr-defined]
            session_id=session.id,  # type: ignore[attr-defined]
            participant_id=session.participant_id,  # type: ignore[attr-defined]
            staff_id=session.staff_id,  # type: ignore[attr-defined]
            fields_json=final_fields,
            completeness_score=score,
            missing_fields=missing,
        )
        await _repo.mark_session_completed(db, session.id, ended_at)  # type: ignore[attr-defined]
        await db.commit()

    return {
        "draft_id": draft.id,
        "fields": final_fields,
        "completeness_score": score,
        "missing_fields": missing,
    }
