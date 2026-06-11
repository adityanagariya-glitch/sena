from __future__ import annotations

import json
from redis.asyncio import Redis
from fastapi import HTTPException, status
from voice.core.settings import settings


class RedisService:
    def __init__(self, redis: Redis):
        self.redis = redis

    async def acquire_participant_lock(
        self, tenant_id: str, participant_id: str, session_id: str
    ) -> bool:
        key = f"participant_session:{tenant_id}:{participant_id}"
        ok = await self.redis.set(key, session_id, ex=settings.redis_lock_ttl_seconds, nx=True)
        return bool(ok)

    async def release_participant_lock(self, tenant_id: str, participant_id: str) -> None:
        key = f"participant_session:{tenant_id}:{participant_id}"
        await self.redis.delete(key)

    async def get_existing_session(self, tenant_id: str, participant_id: str) -> str | None:
        key = f"participant_session:{tenant_id}:{participant_id}"
        value = await self.redis.get(key)
        return value.decode() if isinstance(value, bytes) else value

    async def load_session_state(self, session_id: str) -> dict:
        key = f"voice_session_state:{session_id}"
        value = await self.redis.get(key)
        if value is None:
            return {}
        raw = value.decode() if isinstance(value, bytes) else value
        return json.loads(raw)

    async def save_session_state(self, session_id: str, payload: dict) -> None:
        key = f"voice_session_state:{session_id}"
        await self.redis.setex(key, settings.redis_session_ttl_seconds, json.dumps(payload))

    async def increment_rate_limit(self, scope: str, max_per_minute: int) -> None:
        key = f"rate_limit:{scope}"
        count = await self.redis.incr(key)
        if count == 1:
            await self.redis.expire(key, 60)
        if count > max_per_minute:
            ttl = await self.redis.ttl(key)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"error": "Rate limit exceeded", "retry_after": max(1, ttl)},
            )
