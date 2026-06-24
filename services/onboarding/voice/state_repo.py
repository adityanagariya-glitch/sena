from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import structlog

from .form_state import FormState
from .schema_spec import StepSchema
from .session_bootstrap import SessionBootstrap

if TYPE_CHECKING:
    from redis.asyncio import Redis

log = structlog.get_logger(__name__)

# Redis key templates — ``{scope}`` is the per-instance namespace (prefix +
# optional tenant_id), injected by ``_key()``. The default scope
# ``sena:onboarding`` reproduces the original flat keys byte-for-byte;
# case_review passes its own prefix + tenant_id for NDIS-scoped isolation.
_KEY_STATE = "{scope}:session:{sid}"
_KEY_SCHEMA = "{scope}:session:{sid}:schema"
_KEY_BOOTSTRAP = "{scope}:session:{sid}:bootstrap"
_KEY_TRANSCRIPT = "{scope}:session:{sid}:transcript"
_KEY_WS_LOCK = "{scope}:ws_lock:{sid}"
_KEY_RESUMPTION = "{scope}:resumption:{handle}"
_KEY_FRAME_CAMERA = "{scope}:session:{sid}:last_frame:camera"
_KEY_FRAME_SCREEN = "{scope}:session:{sid}:last_frame:screen"
_KEY_CLIENT_ERRORS = "{scope}:errors:{sid}"

# 7-day TTL for client-reported validation errors (telemetry only — not used
# in the live decision path so the longer retention is safe).
_CLIENT_ERRORS_TTL_SEC = 60 * 60 * 24 * 7


class FormStateRepo:
    def __init__(
        self,
        redis: "Redis",
        *,
        key_prefix: str = "sena:onboarding",
        tenant_id: str | None = None,
    ) -> None:
        self._r = redis
        # Per-instance Redis namespace. With tenant_id set, keys are scoped
        # ``{prefix}:{tenant_id}:...`` (NDIS defense-in-depth — case_review);
        # without it, ``{prefix}:...`` (preserves onboarding's existing keys).
        self._scope = f"{key_prefix}:{tenant_id}" if tenant_id else key_prefix

    def _key(self, template: str, **kw: str) -> str:
        return template.format(scope=self._scope, **kw)

    # ── Session creation ──────────────────────────────────────────────────────

    async def create_session(
        self,
        state: FormState,
        schema: StepSchema,
        ttl_sec: int,
        bootstrap: SessionBootstrap | None = None,
    ) -> None:
        sid = state.session_id
        async with self._r.pipeline() as pipe:
            pipe.set(self._key(_KEY_STATE, sid=sid), state.model_dump_json(), ex=ttl_sec)
            pipe.set(self._key(_KEY_SCHEMA, sid=sid), schema.model_dump_json(), ex=ttl_sec)
            if bootstrap is not None:
                pipe.set(
                    self._key(_KEY_BOOTSTRAP, sid=sid),
                    bootstrap.model_dump_json(),
                    ex=ttl_sec,
                )
            await pipe.execute()
        log.info(
            "session_created",
            session_id=sid,
            step=state.step_id,
            bootstrap_mode=(bootstrap.mode if bootstrap else None),
        )

    # ── Bootstrap envelope (Rule 1 / Rule 2 hygiene contract) ─────────────────

    async def get_bootstrap(self, session_id: str) -> SessionBootstrap | None:
        raw = await self._r.get(self._key(_KEY_BOOTSTRAP, sid=session_id))
        if raw is None:
            return None
        return SessionBootstrap.model_validate_json(raw)

    async def save_bootstrap(
        self,
        session_id: str,
        bootstrap: SessionBootstrap,
        ttl_sec: int,
    ) -> None:
        await self._r.set(
            self._key(_KEY_BOOTSTRAP, sid=session_id),
            bootstrap.model_dump_json(),
            ex=ttl_sec,
        )

    # ── Session ownership guard (cross-tenant isolation) ─────────────────────

    async def assert_session_owner(
        self,
        session_id: str,
        tenant_id: str | None,
        participant_id: str,
    ) -> None:
        """Raise HTTP 403 when caller's (tenant, participant) does not own session.

        Closes the latent gap where a guessed UUID4 could read another
        tenant's transcript. Called from GET state, PUT state, and any new
        cross-screen context paths whose authorisation depends on session
        ownership.

        Legacy sessions saved before tenant_id was required may carry
        ``state.tenant_id is None``. We treat those as opt-out from this
        check (matches today's behaviour) while requiring tenant_id on every
        new session created since this guard landed.
        """
        from fastapi import HTTPException, status

        state = await self.get_state(session_id)
        if state is None:
            # Caller will get 404 from their own get_state; we do not leak
            # ownership info on missing sessions.
            return
        if state.tenant_id is not None and state.tenant_id != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Session does not belong to caller's tenant",
            )
        if state.participant_id != participant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Session does not belong to caller's participant",
            )

    # ── State ─────────────────────────────────────────────────────────────────

    async def get_state(self, session_id: str) -> FormState | None:
        raw = await self._r.get(self._key(_KEY_STATE, sid=session_id))
        if raw is None:
            return None
        return FormState.model_validate_json(raw)

    async def save_state(self, state: FormState, ttl_sec: int) -> None:
        await self._r.set(
            self._key(_KEY_STATE, sid=state.session_id),
            state.model_dump_json(),
            ex=ttl_sec,
        )

    # ── Schema ────────────────────────────────────────────────────────────────

    async def get_schema(self, session_id: str) -> StepSchema | None:
        raw = await self._r.get(self._key(_KEY_SCHEMA, sid=session_id))
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
        key = self._key(_KEY_TRANSCRIPT, sid=session_id)
        await self._r.rpush(key, json.dumps(entry))
        await self._r.expire(key, ttl_sec)

    async def get_transcript(self, session_id: str) -> list[dict]:
        raw_list = await self._r.lrange(self._key(_KEY_TRANSCRIPT, sid=session_id), 0, -1)
        return [json.loads(r) for r in raw_list]

    # ── WS lock (single writer per session) ──────────────────────────────────

    async def acquire_ws_lock(self, session_id: str, ttl_sec: int) -> bool:
        """Returns True if lock acquired (NX — only sets if not exists)."""
        result = await self._r.set(
            self._key(_KEY_WS_LOCK, sid=session_id),
            "1",
            nx=True,
            ex=ttl_sec,
        )
        return result is not None

    async def release_ws_lock(self, session_id: str) -> None:
        await self._r.delete(self._key(_KEY_WS_LOCK, sid=session_id))

    async def is_ws_locked(self, session_id: str) -> bool:
        return bool(await self._r.exists(self._key(_KEY_WS_LOCK, sid=session_id)))

    # ── Session resumption ────────────────────────────────────────────────────

    async def save_resumption_handle(
        self,
        handle: str,
        session_id: str,
        ttl_sec: int,
    ) -> None:
        await self._r.set(
            self._key(_KEY_RESUMPTION, handle=handle),
            session_id,
            ex=ttl_sec,
        )

    async def get_session_by_handle(self, handle: str) -> str | None:
        return await self._r.get(self._key(_KEY_RESUMPTION, handle=handle))

    async def delete_resumption_handle(self, handle: str) -> None:
        await self._r.delete(self._key(_KEY_RESUMPTION, handle=handle))

    async def redeem_resumption_handle(self, handle: str) -> str | None:
        """Atomically get and delete the resumption handle (GETDEL — single-use)."""
        return await self._r.getdel(self._key(_KEY_RESUMPTION, handle=handle))

    # ── Camera / screen frames (latest only, for debug / Phase D) ─────────────

    async def save_frame(self, session_id: str, frame_type: str, data: bytes) -> None:
        key_map = {
            "camera": self._key(_KEY_FRAME_CAMERA, sid=session_id),
            "screen": self._key(_KEY_FRAME_SCREEN, sid=session_id),
        }
        key = key_map.get(frame_type)
        if key:
            await self._r.set(key, data, ex=300)  # 5 min TTL

    # ── Client-side validation error reporting (telemetry) ───────────────────

    async def append_client_validation_error(
        self,
        session_id: str,
        error: dict[str, Any],
    ) -> None:
        """Persist a client-reported validation error for later analysis.

        Stored as a Redis list (RPUSH) under
        ``sena:onboarding:errors:{session_id}`` with a 7-day TTL refreshed on
        every write. Telemetry-only — the live decision path never reads
        these. The companion ``read_client_validation_errors`` returns the
        list for debugging or a future internal endpoint.
        """
        key = self._key(_KEY_CLIENT_ERRORS, sid=session_id)
        payload = json.dumps(error, default=str, separators=(",", ":"))
        async with self._r.pipeline(transaction=False) as p:
            p.rpush(key, payload)
            p.expire(key, _CLIENT_ERRORS_TTL_SEC)
            await p.execute()

    async def read_client_validation_errors(
        self,
        session_id: str,
    ) -> list[dict[str, Any]]:
        """Return all client-reported validation errors for the session.

        Intentionally unexposed via REST — call from debug tooling or future
        internal telemetry endpoint. Order matches insertion order.
        """
        raw_list = await self._r.lrange(
            self._key(_KEY_CLIENT_ERRORS, sid=session_id), 0, -1,
        )
        return [json.loads(r) for r in raw_list]

    async def save_session_state_with_metrics(
        self,
        session_id: str,
        engagement: dict | None = None,
        sentiment: str | None = None,
        ttl_sec: int = 86400,
    ) -> None:
        """Save session metrics using PIPELINE (3x faster).

        Single network round-trip for multiple Redis operations:
        - Engagement level + progress (60s TTL)
        - Sentiment assessment (30s TTL)
        """
        pipe = self._r.pipeline()

        if engagement is not None:
            engagement_key = self._key(f"{{scope}}:engagement:{{sid}}", sid=session_id)
            pipe.setex(
                engagement_key,
                60,
                json.dumps(engagement),
            )

        if sentiment is not None:
            sentiment_key = self._key(f"{{scope}}:sentiment:{{sid}}", sid=session_id)
            pipe.setex(
                sentiment_key,
                30,
                json.dumps({"sentiment": sentiment}),
            )

        await pipe.execute()
        log.debug(
            "session_metrics_pipeline_saved",
            session_id=session_id,
            with_engagement=engagement is not None,
            with_sentiment=sentiment is not None,
        )

    async def save_session_state_with_context(
        self,
        session_id: str,
        values: dict | None = None,
        completeness: float | None = None,
        missing_fields: list[str] | None = None,
    ) -> None:
        """Save session context metadata (background operation).

        Non-blocking cache for session completeness and missing fields.
        """
        try:
            pipe = self._r.pipeline()

            if values is not None:
                context_key = self._key(f"{{scope}}:context:{{sid}}", sid=session_id)
                context_data = {
                    "values": values,
                    "completeness": completeness or 0,
                    "missing_fields": missing_fields or [],
                }
                pipe.setex(
                    context_key,
                    3600,  # 1 hour TTL
                    json.dumps(context_data),
                )

            await pipe.execute()
            log.debug(
                "session_context_saved session=%s completeness=%s",
                session_id,
                completeness or 0,
            )
        except Exception:
            log.exception("session_context_save_failed session=%s", session_id)

    # ── Session deletion ──────────────────────────────────────────────────────

    async def delete_session(self, session_id: str) -> None:
        keys = [
            self._key(_KEY_STATE, sid=session_id),
            self._key(_KEY_SCHEMA, sid=session_id),
            self._key(_KEY_BOOTSTRAP, sid=session_id),
            self._key(_KEY_TRANSCRIPT, sid=session_id),
            self._key(_KEY_WS_LOCK, sid=session_id),
            self._key(_KEY_FRAME_CAMERA, sid=session_id),
            self._key(_KEY_FRAME_SCREEN, sid=session_id),
            self._key(_KEY_CLIENT_ERRORS, sid=session_id),
        ]
        await self._r.delete(*keys)
        log.info("session_deleted", session_id=session_id)
