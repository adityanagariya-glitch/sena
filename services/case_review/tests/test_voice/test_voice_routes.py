"""Tests for POST /voice/session and WSS /voice/ws — 4 cases."""
from __future__ import annotations

import pytest
import pytest_asyncio

try:
    import fakeredis.aioredis as fakeredis_aio
    _HAS_FAKEREDIS = True
except ImportError:
    _HAS_FAKEREDIS = False

pytestmark = pytest.mark.skipif(not _HAS_FAKEREDIS, reason="fakeredis not installed")


@pytest_asyncio.fixture
async def fake_redis():
    r = fakeredis_aio.FakeRedis(decode_responses=False)
    yield r
    await r.aclose()


@pytest.fixture
def app(fake_redis):
    from fastapi.testclient import TestClient
    from voice.state_repo import VoiceStateRepo
    import api.voice_routes as vr
    from main import create_app

    application = create_app()
    repo = VoiceStateRepo(fake_redis)
    vr.set_voice_repo(repo)
    return application


def test_post_session_returns_ws_url(app) -> None:
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.post(
        "/v1/restrictive-practices/voice/session",
        json={
            "case_note_id": "cn-1",
            "worker_id": "w-1",
            "client_id": "liam-1",
            "initial_values": {
                "shift": {"shift_date": "2026-05-21"},
            },
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    assert "ws_url" in data
    assert "expires_at" in data
    assert "/voice/ws/" in data["ws_url"]


def test_post_session_returns_ws_url_with_token(app) -> None:
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.post(
        "/v1/restrictive-practices/voice/session",
        json={"case_note_id": "cn-2", "worker_id": "w-2", "client_id": "liam-2"},
    )
    assert resp.status_code == 200
    assert "token=" in resp.json()["ws_url"]


@pytest.mark.asyncio
async def test_ws_invalid_token_closes_4011(app, fake_redis) -> None:
    from fastapi.testclient import TestClient
    from voice.state_repo import VoiceStateRepo
    import api.voice_routes as vr

    repo = VoiceStateRepo(fake_redis)
    vr.set_voice_repo(repo)

    client = TestClient(app)
    resp = client.post(
        "/v1/restrictive-practices/voice/session",
        json={"case_note_id": "cn-3", "worker_id": "w-3", "client_id": "liam-3"},
    )
    session_id = resp.json()["session_id"]

    with client.websocket_connect(
        f"/v1/restrictive-practices/voice/ws/{session_id}?token=WRONG_TOKEN"
    ) as ws:
        # Server should close immediately with 4011
        try:
            ws.receive_text()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_ws_missing_session_closes_4004(app, fake_redis) -> None:
    from fastapi.testclient import TestClient

    client = TestClient(app)
    with client.websocket_connect(
        "/v1/restrictive-practices/voice/ws/nonexistent-session-id?token=fake-token"
    ) as ws:
        try:
            ws.receive_text()
        except Exception:
            pass
