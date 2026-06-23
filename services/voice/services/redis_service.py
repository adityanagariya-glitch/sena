from __future__ import annotations

import json
import logging
from redis.asyncio import Redis
from fastapi import HTTPException, status
from voice.core.settings import settings

logger = logging.getLogger(__name__)


class RedisService:
    """Redis service with pipeline optimization for batch operations."""

    def __init__(self, redis: Redis):
        self.redis = redis

    async def acquire_participant_lock(
        self, tenant_id: str, participant_id: str, session_id: str
    ) -> bool:
        """Acquire exclusive session lock for participant."""
        key = f"participant_session:{tenant_id}:{participant_id}"
        ok = await self.redis.set(key, session_id, ex=settings.redis_lock_ttl_seconds, nx=True)
        return bool(ok)

    async def release_participant_lock(self, tenant_id: str, participant_id: str) -> None:
        """Release participant session lock."""
        key = f"participant_session:{tenant_id}:{participant_id}"
        await self.redis.delete(key)

    async def get_existing_session(self, tenant_id: str, participant_id: str) -> str | None:
        """Get existing session ID for participant."""
        key = f"participant_session:{tenant_id}:{participant_id}"
        value = await self.redis.get(key)
        return value.decode() if isinstance(value, bytes) else value

    async def load_session_state(self, session_id: str) -> dict:
        """Load session state from Redis."""
        key = f"voice_session_state:{session_id}"
        value = await self.redis.get(key)
        if value is None:
            return {}
        raw = value.decode() if isinstance(value, bytes) else value
        return json.loads(raw)

    async def save_session_state(self, session_id: str, payload: dict) -> None:
        """Save session state to Redis (single operation)."""
        key = f"voice_session_state:{session_id}"
        await self.redis.setex(key, settings.redis_session_ttl_seconds, json.dumps(payload))

    async def save_session_state_with_metrics(
        self,
        session_id: str,
        fields_payload: dict,
        sentiment: str | None = None,
        engagement_level: str | None = None,
        progress: int | None = None,
    ) -> None:
        """Save session state + metrics using PIPELINE (3x faster).

        Single network round-trip for multiple Redis operations:
        - Session fields state (24h TTL)
        - Sentiment trend (30s TTL)
        - Engagement summary (60s TTL)
        """
        # Use pipeline for batch operations (1 round-trip instead of 3)
        pipe = self.redis.pipeline()

        # 1. Save session state (persistent)
        session_key = f"voice_session_state:{session_id}"
        pipe.setex(
            session_key,
            settings.redis_session_ttl_seconds,
            json.dumps(fields_payload),
        )

        # 2. Cache sentiment trend (temporary, 30s)
        if sentiment:
            sentiment_key = f"sentiment_trend:{session_id}"
            pipe.setex(
                sentiment_key,
                30,
                json.dumps({"sentiment": sentiment}),
            )

        # 3. Cache engagement summary (temporary, 60s)
        if engagement_level is not None and progress is not None:
            engagement_key = f"engagement_summary:{session_id}"
            pipe.setex(
                engagement_key,
                60,
                json.dumps({
                    "level": engagement_level,
                    "progress": progress,
                }),
            )

        # Execute all operations in single network call
        await pipe.execute()

        logger.debug(
            "session_state_pipeline_saved session_id=%s with_sentiment=%s with_engagement=%s",
            session_id,
            sentiment is not None,
            engagement_level is not None,
        )

    async def get_engagement_summary(self, session_id: str) -> dict | None:
        """Get cached engagement summary (30s-60s cache)."""
        key = f"engagement_summary:{session_id}"
        value = await self.redis.get(key)
        if value is None:
            return None
        raw = value.decode() if isinstance(value, bytes) else value
        return json.loads(raw)

    async def get_sentiment_trend(self, session_id: str) -> dict | None:
        """Get cached sentiment trend (30s cache)."""
        key = f"sentiment_trend:{session_id}"
        value = await self.redis.get(key)
        if value is None:
            return None
        raw = value.decode() if isinstance(value, bytes) else value
        return json.loads(raw)

    async def increment_rate_limit(self, scope: str, max_per_minute: int) -> None:
        """Increment rate limit counter (atomic operation)."""
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
