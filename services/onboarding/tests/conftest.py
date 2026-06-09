from __future__ import annotations

import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport, AsyncClient

from onboarding.api.deps import get_repo
from onboarding.main import create_app
from sena_common.voice.state_repo import FormStateRepo


@pytest_asyncio.fixture
async def fake_redis():
    r = FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


@pytest_asyncio.fixture
async def repo(fake_redis):
    return FormStateRepo(fake_redis)


@pytest_asyncio.fixture
async def async_client(fake_redis):
    app = create_app()
    fake_repo = FormStateRepo(fake_redis)
    app.dependency_overrides[get_repo] = lambda: fake_repo
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
