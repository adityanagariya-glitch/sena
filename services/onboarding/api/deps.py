from __future__ import annotations

from redis.asyncio import from_url as redis_from_url

from onboarding.core.settings import settings
from voice.state_repo import FormStateRepo

redis_client = redis_from_url(settings.redis_url, decode_responses=True)


def get_repo() -> FormStateRepo:
    return FormStateRepo(redis_client)
