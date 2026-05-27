from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport

from onboarding.api.deps import get_repo
from onboarding.main import create_app
from onboarding.repositories.state_repo import FormStateRepo

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def personal_info_schema() -> dict:
    return json.loads((FIXTURES_DIR / "schema_personal_information.json").read_text())


@pytest.fixture
def medical_schema() -> dict:
    return json.loads((FIXTURES_DIR / "schema_medical_information.json").read_text())


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
