"""
Per-(tenant_id, participant_id) cross-screen context repository.

Owns the only Redis surface for cross-step shared context. Two key shapes,
both tenant-prefixed by construction so a guessed `participant_id` cannot
read another tenant's bucket:

  sena:onboarding:user_ctx:{tenant_id}:{participant_id}    Hash of step_summaries
      field "step:{N}" -> JSON StepSummary
  sena:onboarding:user_idx:{tenant_id}:{participant_id}    Set of session_ids

Both keys carry a 7-day TTL refreshed on every write. Anything longer-horizon
is the application backend's responsibility — this repo holds ephemeral
shared context only.

`tenant_id` is a required positional argument on every method; there is no
overload that omits it. The caller's tenant identity comes from the auth
context, never from a request body — that prevents tenant-spoofing via
crafted JSON.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from onboarding.models.cross_screen_summary import CrossScreenContext, StepSummary

if TYPE_CHECKING:
    from redis.asyncio import Redis

log = structlog.get_logger(__name__)

# Redis key templates — tenant + participant prefixed by construction.
_KEY_USER_CTX = "sena:onboarding:user_ctx:{tenant_id}:{participant_id}"
_KEY_USER_IDX = "sena:onboarding:user_idx:{tenant_id}:{participant_id}"

# 7-day TTL covers a multi-day onboarding journey while still letting stale
# buckets age out naturally. Documented in the PRD.
DEFAULT_BUCKET_TTL_SEC = 7 * 24 * 60 * 60


class UserContextRepo:
    """Redis-backed repository for (tenant, participant) shared context."""

    def __init__(self, redis: "Redis") -> None:
        self._r = redis

    # ── Bucket I/O ────────────────────────────────────────────────────────────

    async def put_step_summary(
        self,
        tenant_id: str,
        participant_id: str,
        summary: StepSummary,
        *,
        ttl_sec: int = DEFAULT_BUCKET_TTL_SEC,
    ) -> None:
        """Idempotent write of a step summary.

        Subsequent calls with the same `summary.step_number` overwrite the
        previous value — this is the property that lets the WS-close flush
        path safely race against POST /complete without double-writing.
        """
        key = _KEY_USER_CTX.format(tenant_id=tenant_id, participant_id=participant_id)
        field = f"step:{summary.step_number}"
        async with self._r.pipeline() as pipe:
            pipe.hset(key, field, summary.model_dump_json())
            pipe.expire(key, ttl_sec)
            await pipe.execute()
        log.debug(
            "user_ctx_step_written",
            tenant_id=tenant_id,
            participant_id=participant_id,
            step=summary.step_number,
        )

    async def get_bucket(
        self,
        tenant_id: str,
        participant_id: str,
    ) -> CrossScreenContext:
        """Return the bucket as a `CrossScreenContext` (empty if no key).

        Summaries are returned sorted by `step_number` ascending so the
        renderer can rely on stable ordering.
        """
        key = _KEY_USER_CTX.format(tenant_id=tenant_id, participant_id=participant_id)
        raw_map = await self._r.hgetall(key)
        if not raw_map:
            return CrossScreenContext()
        summaries: list[StepSummary] = []
        for _field, raw in raw_map.items():
            try:
                summaries.append(StepSummary.model_validate_json(raw))
            except Exception:
                # Tolerate a single corrupt field — never crash a fresh session
                # because of stale data in the bucket.
                log.warning(
                    "user_ctx_corrupt_field",
                    tenant_id=tenant_id,
                    participant_id=participant_id,
                )
        summaries.sort(key=lambda s: s.step_number)
        return CrossScreenContext(summaries=summaries)

    # ── Session-id index ──────────────────────────────────────────────────────

    async def add_session_to_index(
        self,
        tenant_id: str,
        participant_id: str,
        session_id: str,
        *,
        ttl_sec: int = DEFAULT_BUCKET_TTL_SEC,
    ) -> None:
        """Add a session_id to the per-participant index. Set TTL refreshed."""
        key = _KEY_USER_IDX.format(tenant_id=tenant_id, participant_id=participant_id)
        async with self._r.pipeline() as pipe:
            pipe.sadd(key, session_id)
            pipe.expire(key, ttl_sec)
            await pipe.execute()

    async def list_sessions_for_participant(
        self,
        tenant_id: str,
        participant_id: str,
    ) -> list[str]:
        key = _KEY_USER_IDX.format(tenant_id=tenant_id, participant_id=participant_id)
        members = await self._r.smembers(key)
        return sorted(str(m) for m in members)
