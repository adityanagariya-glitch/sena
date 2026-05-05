"""Integration tests for REST routes."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

FIXTURES = Path(__file__).parent.parent / "fixtures"


def personal_schema_payload() -> dict:
    return json.loads((FIXTURES / "schema_personal_information.json").read_text())


class TestCreateSession:
    async def test_creates_session(self, async_client):
        resp = await async_client.post("/v1/onboarding/session", json={
            "participant_id": "part-001",
            "step": "personal_information",
            "schema": personal_schema_payload(),
        })
        assert resp.status_code == 201
        data = resp.json()
        assert "session_id" in data
        assert "ws_url" in data
        assert data["ws_url"].startswith("ws://")

    async def test_initial_state_accepted(self, async_client):
        resp = await async_client.post("/v1/onboarding/session", json={
            "participant_id": "part-001",
            "step": "personal_information",
            "schema": personal_schema_payload(),
            "initial_state": {"basics": {"full_name": "Alice"}},
        })
        assert resp.status_code == 201


class TestGetState:
    async def test_get_existing_state(self, async_client):
        create = await async_client.post("/v1/onboarding/session", json={
            "participant_id": "part-001",
            "step": "personal_information",
            "schema": personal_schema_payload(),
        })
        sid = create.json()["session_id"]

        resp = await async_client.get(f"/v1/onboarding/session/{sid}/state")
        assert resp.status_code == 200
        assert resp.json()["session_id"] == sid

    async def test_get_missing_returns_404(self, async_client):
        resp = await async_client.get("/v1/onboarding/session/does-not-exist/state")
        assert resp.status_code == 404


class TestUpdateState:
    async def test_update_succeeds_when_ws_unlocked(self, async_client):
        create = await async_client.post("/v1/onboarding/session", json={
            "participant_id": "part-001",
            "step": "personal_information",
            "schema": personal_schema_payload(),
        })
        sid = create.json()["session_id"]

        resp = await async_client.put(
            f"/v1/onboarding/session/{sid}/state",
            json={"values": {"basics": {"full_name": "Updated Alice"}}},
        )
        assert resp.status_code == 200
        assert resp.json()["values"]["basics"]["full_name"]["value"] == "Updated Alice"

    async def test_update_returns_409_when_ws_locked(self, async_client, fake_redis):
        create = await async_client.post("/v1/onboarding/session", json={
            "participant_id": "part-001",
            "step": "personal_information",
            "schema": personal_schema_payload(),
        })
        sid = create.json()["session_id"]

        # Simulate locked WS
        await fake_redis.set(f"sena:onboarding:ws_lock:{sid}", "1", ex=60)

        resp = await async_client.put(
            f"/v1/onboarding/session/{sid}/state",
            json={"values": {"basics": {"full_name": "X"}}},
        )
        assert resp.status_code == 409


class TestCompleteSession:
    async def test_complete_fires_webhook(self, async_client):
        create = await async_client.post("/v1/onboarding/session", json={
            "participant_id": "part-001",
            "step": "personal_information",
            "schema": personal_schema_payload(),
        })
        sid = create.json()["session_id"]

        with patch("onboarding.api.routes.fire_webhook", new_callable=AsyncMock) as mock_wh:
            mock_wh.return_value = True
            resp = await async_client.post(f"/v1/onboarding/session/{sid}/complete")
            assert resp.status_code == 200
            data = resp.json()
            assert data["completed"] is True
            assert data["webhook_delivered"] is True
            mock_wh.assert_awaited_once()

            call_kwargs = mock_wh.call_args.kwargs
            assert call_kwargs["event"] == "onboarding.session.completed"
            payload = call_kwargs["payload"]
            assert payload["step"] == "personal_information"


class TestHealth:
    async def test_live(self, async_client):
        resp = await async_client.get("/health/live")
        assert resp.status_code == 200

    async def test_ready(self, async_client):
        resp = await async_client.get("/health/ready")
        assert resp.status_code == 200
        assert resp.json()["redis"] == "connected"
