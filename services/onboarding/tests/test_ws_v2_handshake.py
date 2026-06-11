"""WS v2 hello-gate tests.

Strategy: create a real session using FormStateRepo.create_session inside
asyncio.run() (isolated event loop, no conflict with TestClient), backed by
a shared FakeServer. The TestClient gets an async FakeRedis on the same
FakeServer so the WS handler finds the seeded state.
"""
from __future__ import annotations

import asyncio
import json

import fakeredis
import pytest
from fakeredis.aioredis import FakeRedis as AsyncFakeRedis
from fastapi.testclient import TestClient

from onboarding.api.deps import get_repo
from onboarding.main import create_app
from voice.form_state import FormState
from voice.schema_spec import StepSchema
from voice.state_repo import FormStateRepo

_SESSION_ID = "test-hello-gate-session"

_MINIMAL_SCHEMA: dict = {
    "step_id": "personal_information",
    "step_label": "Personal Information",
    "progress_percent": 20,
    "sections": [
        {
            "id": "basics",
            "label": "About you",
            "fields": [
                {"id": "full_name", "type": "text", "label": "Full Name", "required": True},
            ],
        },
    ],
}


def _personal_schema() -> dict:
    return _MINIMAL_SCHEMA


@pytest.fixture
def ws_client():
    """TestClient with a seeded session in fake-Redis.

    Seeding happens synchronously via asyncio.run() BEFORE the TestClient
    is created — the TestClient's internal event loop doesn't exist yet,
    so there's no conflict.
    """
    schema_data = _personal_schema()
    server = fakeredis.FakeServer()

    # Seed inside a fresh, short-lived event loop (no TestClient loop yet).
    async def _seed() -> None:
        r = AsyncFakeRedis(server=server, decode_responses=True)
        repo = FormStateRepo(r)
        state = FormState(
            session_id=_SESSION_ID,
            step_id=schema_data["step_id"],
            participant_id="p-test",
            tenant_id="t-test",
        )
        schema = StepSchema.model_validate(schema_data)
        await repo.create_session(state, schema, ttl_sec=3600)
        await r.aclose()

    asyncio.run(_seed())

    # Now create the TestClient — its loop is started AFTER seeding is done.
    # The async FakeRedis here shares the same FakeServer, so it sees the data.
    async_r = AsyncFakeRedis(server=server, decode_responses=True)
    fake_repo = FormStateRepo(async_r)
    app = create_app()
    app.dependency_overrides[get_repo] = lambda: fake_repo
    return TestClient(app)


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_ws_rejects_v1_hello(ws_client) -> None:
    with ws_client.websocket_connect(f"/ws/onboarding/{_SESSION_ID}") as ws:
        ws.send_text(json.dumps({"type": "hello", "client_proto": "v1"}))
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert msg["code"] == "unsupported_proto"


def test_ws_rejects_non_hello_first_frame(ws_client) -> None:
    with ws_client.websocket_connect(f"/ws/onboarding/{_SESSION_ID}") as ws:
        ws.send_text(json.dumps({"type": "start"}))
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert msg["code"] == "unsupported_proto"


def test_ws_rejects_invalid_json_first_frame(ws_client) -> None:
    with ws_client.websocket_connect(f"/ws/onboarding/{_SESSION_ID}") as ws:
        ws.send_text("not-json{{")
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert msg["code"] == "protocol_error"
