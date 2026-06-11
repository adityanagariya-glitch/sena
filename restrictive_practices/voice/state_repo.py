from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import structlog

from voice.schema_spec import StepSchema
from voice.session_bootstrap import SessionBootstrap
from voice.state import CaseNoteVoiceState

if TYPE_CHECKING:
    from redis.asyncio import Redis

log = structlog.get_logger(__name__)

# Redis key templates — prefix sena:rp_voice: isolates from sena:onboarding:
_KEY_STATE = "sena:rp_voice:session:{sid}"
_KEY_SCHEMA = "sena:rp_voice:session:{sid}:schema"
_KEY_BOOTSTRAP = "sena:rp_voice:session:{sid}:bootstrap"
_KEY_TOKEN = "sena:rp_voice:session:{sid}:token"
_KEY_TRANSCRIPT = "sena:rp_voice:session:{sid}:transcript"
_KEY_WS_LOCK = "sena:rp_voice:ws_lock:{sid}"
_KEY_RESUMPTION = "sena:rp_voice:resumption:{handle}"


class VoiceStateRepo:
    def __init__(self, redis: "Redis") -> None:
        self._r = redis

    # ── Session creation ──────────────────────────────────────────────────────

    async def create_session(
        self,
        state: CaseNoteVoiceState,
        schema: StepSchema,
        ttl_sec: int,
        bootstrap: SessionBootstrap | None = None,
        token: str | None = None,
    ) -> None:
        sid = state.session_id
        async with self._r.pipeline() as pipe:
            pipe.set(_KEY_STATE.format(sid=sid), state.model_dump_json(), ex=ttl_sec)
            pipe.set(_KEY_SCHEMA.format(sid=sid), schema.model_dump_json(), ex=ttl_sec)
            if bootstrap is not None:
                pipe.set(_KEY_BOOTSTRAP.format(sid=sid), bootstrap.model_dump_json(), ex=ttl_sec)
            if token is not None:
                pipe.set(_KEY_TOKEN.format(sid=sid), token, ex=ttl_sec)
            await pipe.execute()
        log.info("session_created", session_id=sid)

    # ── Token validation ──────────────────────────────────────────────────────

    async def get_token(self, session_id: str) -> str | None:
        raw = await self._r.get(_KEY_TOKEN.format(sid=session_id))
        return raw.decode() if isinstance(raw, bytes) else raw

    # ── Bootstrap ─────────────────────────────────────────────────────────────

    async def get_bootstrap(self, session_id: str) -> SessionBootstrap | None:
        raw = await self._r.get(_KEY_BOOTSTRAP.format(sid=session_id))
        if raw is None:
            return None
        return SessionBootstrap.model_validate_json(raw)

    async def save_bootstrap(self, session_id: str, bootstrap: SessionBootstrap, ttl_sec: int) -> None:
        await self._r.set(
            _KEY_BOOTSTRAP.format(sid=session_id),
            bootstrap.model_dump_json(),
            ex=ttl_sec,
        )

    # ── Session ownership guard ───────────────────────────────────────────────

    async def assert_session_owner(
        self,
        session_id: str,
        tenant_id: str | None,
        worker_id: str,
    ) -> None:
        """Raise HTTP 403 when caller does not own session."""
        from fastapi import HTTPException, status

        state = await self.get_state(session_id)
        if state is None:
            return
        if state.tenant_id is not None and state.tenant_id != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Session does not belong to caller's tenant",
            )
        if state.worker_id != worker_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Session does not belong to caller",
            )

    # ── State ─────────────────────────────────────────────────────────────────

    async def get_state(self, session_id: str) -> CaseNoteVoiceState | None:
        raw = await self._r.get(_KEY_STATE.format(sid=session_id))
        if raw is None:
            return None
        return CaseNoteVoiceState.model_validate_json(raw)

    async def save_state(self, state: CaseNoteVoiceState, ttl_sec: int) -> None:
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

    async def append_transcript(self, session_id: str, entry: dict, ttl_sec: int) -> None:
        key = _KEY_TRANSCRIPT.format(sid=session_id)
        await self._r.rpush(key, json.dumps(entry))
        await self._r.expire(key, ttl_sec)

    async def get_transcript(self, session_id: str) -> list[dict]:
        raw_list = await self._r.lrange(_KEY_TRANSCRIPT.format(sid=session_id), 0, -1)
        return [json.loads(r) for r in raw_list]

    # ── WS lock ───────────────────────────────────────────────────────────────

    async def acquire_ws_lock(self, session_id: str, ttl_sec: int) -> bool:
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

    async def save_resumption_handle(self, handle: str, session_id: str, ttl_sec: int) -> None:
        await self._r.set(_KEY_RESUMPTION.format(handle=handle), session_id, ex=ttl_sec)

    async def get_session_by_handle(self, handle: str) -> str | None:
        return await self._r.get(_KEY_RESUMPTION.format(handle=handle))

    async def delete_resumption_handle(self, handle: str) -> None:
        await self._r.delete(_KEY_RESUMPTION.format(handle=handle))

    async def redeem_resumption_handle(self, handle: str) -> str | None:
        return await self._r.getdel(_KEY_RESUMPTION.format(handle=handle))

    # ── Session deletion ──────────────────────────────────────────────────────

    async def delete_session(self, session_id: str) -> None:
        keys = [
            _KEY_STATE.format(sid=session_id),
            _KEY_SCHEMA.format(sid=session_id),
            _KEY_BOOTSTRAP.format(sid=session_id),
            _KEY_TOKEN.format(sid=session_id),
            _KEY_TRANSCRIPT.format(sid=session_id),
            _KEY_WS_LOCK.format(sid=session_id),
        ]
        await self._r.delete(*keys)
        log.info("session_deleted", session_id=session_id)
