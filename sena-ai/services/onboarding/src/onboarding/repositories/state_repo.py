from __future__ import annotations

import json
from typing import TYPE_CHECKING

import structlog

from onboarding.models.form_state import FormState
from onboarding.models.schema_spec import StepSchema

if TYPE_CHECKING:
    from redis.asyncio import Redis

log = structlog.get_logger(__name__)

# Redis key templates
_KEY_STATE = "sena:onboarding:session:{sid}"
_KEY_SCHEMA = "sena:onboarding:session:{sid}:schema"
_KEY_TRANSCRIPT = "sena:onboarding:session:{sid}:transcript"
_KEY_WS_LOCK = "sena:onboarding:ws_lock:{sid}"
_KEY_RESUMPTION = "sena:onboarding:resumption:{handle}"
_KEY_FRAME_CAMERA = "sena:onboarding:session:{sid}:last_frame:camera"
_KEY_FRAME_SCREEN = "sena:onboarding:session:{sid}:last_frame:screen"


class FormStateRepo:
    def __init__(self, redis: "Redis") -> None:
        self._r = redis

    # ── Session creation ──────────────────────────────────────────────────────

    async def create_session(
        self,
        state: FormState,
        schema: StepSchema,
        ttl_sec: int,
    ) -> None:
        sid = state.session_id
        async with self._r.pipeline() as pipe:
            pipe.set(_KEY_STATE.format(sid=sid), state.model_dump_json(), ex=ttl_sec)
            pipe.set(_KEY_SCHEMA.format(sid=sid), schema.model_dump_json(), ex=ttl_sec)
            await pipe.execute()
        log.info("session_created", session_id=sid, step=state.step_id)

    # ── State ─────────────────────────────────────────────────────────────────

    async def get_state(self, session_id: str) -> FormState | None:
        raw = await self._r.get(_KEY_STATE.format(sid=session_id))
        if raw is None:
            return None
        return FormState.model_validate_json(raw)

    async def save_state(self, state: FormState, ttl_sec: int) -> None:
        await self._r.set(
            _KEY_STATE.format(sid=state.session_id),
            state.model_dump_json(),
            ex=ttl_sec,
        )

    # ── Schema ────────────────────────────────────────────────────────────────

    async def get_schema(self, session_id: str) -> StepSchema | None:
        raw = await self._r.get(_KEY_SCHEMA.format(sid=session_id))
        if raw is None:
            return None
        return StepSchema.model_validate_json(raw)

    # ── Transcript ────────────────────────────────────────────────────────────

    async def append_transcript(
        self,
        session_id: str,
        entry: dict,
        ttl_sec: int,
    ) -> None:
        key = _KEY_TRANSCRIPT.format(sid=session_id)
        await self._r.rpush(key, json.dumps(entry))
        await self._r.expire(key, ttl_sec)

    async def get_transcript(self, session_id: str) -> list[dict]:
        raw_list = await self._r.lrange(_KEY_TRANSCRIPT.format(sid=session_id), 0, -1)
        return [json.loads(r) for r in raw_list]

    # ── WS lock (single writer per session) ──────────────────────────────────

    async def acquire_ws_lock(self, session_id: str, ttl_sec: int) -> bool:
        """Returns True if lock acquired (NX — only sets if not exists)."""
        result = await self._r.set(
            _KEY_WS_LOCK.format(sid=session_id),
            "1",
            nx=True,
            ex=ttl_sec,
        )
        return result is not None

    async def release_ws_lock(self, session_id: str) -> None:
        await self._r.delete(_KEY_WS_LOCK.format(sid=session_id))

    async def is_ws_locked(self, session_id: str) -> bool:
        return bool(await self._r.exists(_KEY_WS_LOCK.format(sid=session_id)))

    # ── Session resumption ────────────────────────────────────────────────────

    async def save_resumption_handle(
        self,
        handle: str,
        session_id: str,
        ttl_sec: int,
    ) -> None:
        await self._r.set(
            _KEY_RESUMPTION.format(handle=handle),
            session_id,
            ex=ttl_sec,
        )

    async def get_session_by_handle(self, handle: str) -> str | None:
        return await self._r.get(_KEY_RESUMPTION.format(handle=handle))

    async def delete_resumption_handle(self, handle: str) -> None:
        await self._r.delete(_KEY_RESUMPTION.format(handle=handle))

    async def redeem_resumption_handle(self, handle: str) -> str | None:
        """Atomically get and delete the resumption handle (GETDEL — single-use)."""
        return await self._r.getdel(_KEY_RESUMPTION.format(handle=handle))

    # ── Camera / screen frames (latest only, for debug / Phase D) ─────────────

    async def save_frame(self, session_id: str, frame_type: str, data: bytes) -> None:
        key_map = {
            "camera": _KEY_FRAME_CAMERA.format(sid=session_id),
            "screen": _KEY_FRAME_SCREEN.format(sid=session_id),
        }
        key = key_map.get(frame_type)
        if key:
            await self._r.set(key, data, ex=300)  # 5 min TTL

    # ── Session deletion ──────────────────────────────────────────────────────

    async def delete_session(self, session_id: str) -> None:
        keys = [
            _KEY_STATE.format(sid=session_id),
            _KEY_SCHEMA.format(sid=session_id),
            _KEY_TRANSCRIPT.format(sid=session_id),
            _KEY_WS_LOCK.format(sid=session_id),
            _KEY_FRAME_CAMERA.format(sid=session_id),
            _KEY_FRAME_SCREEN.format(sid=session_id),
        ]
        await self._r.delete(*keys)
        log.info("session_deleted", session_id=session_id)
