"""Tests for POST /v1/onboarding/session/{session_id}/errors.

Endpoint records mobile-client-reported validation errors (telemetry only,
7-day TTL). Behaviour mirrors Agent 03B's flutterhandoffdev.md section 12:
strict schema, 204 on success, 404 on missing session, 7-day TTL.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

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
                {"id": "email", "type": "email", "label": "Email Address", "required": True},
            ],
        },
    ],
}


def _personal_schema_payload() -> dict:
    return _MINIMAL_SCHEMA


def _valid_body() -> dict:
    return {
        "error_type": "email_invalid",
        "error_message": "Enter a valid email",
        "input_method": "typed",
        "field_id": "basics.email",
        "attempted_value": "not-an-email",
        "ts": datetime.now(UTC).isoformat(),
    }


async def _create_session(async_client) -> str:
    resp = await async_client.post(
        "/v1/onboarding/session",
        json={
            "participant_id": "part-001",
            "step": "personal_information",
            "schema": _personal_schema_payload(),
        },
    )
    assert resp.status_code == 201
    return resp.json()["session_id"]


class TestErrorsEndpoint:
    async def test_happy_path_returns_204(self, async_client, fake_redis):
        sid = await _create_session(async_client)

        resp = await async_client.post(
            f"/v1/onboarding/session/{sid}/errors",
            json=_valid_body(),
        )
        assert resp.status_code == 204
        # Body is empty on 204
        assert resp.content == b""

        # Redis list populated with the entry
        items = await fake_redis.lrange(f"sena:onboarding:errors:{sid}", 0, -1)
        assert len(items) == 1
        parsed = json.loads(items[0])
        assert parsed["error_type"] == "email_invalid"
        assert parsed["input_method"] == "typed"
        assert parsed["field_id"] == "basics.email"

    async def test_ttl_is_about_seven_days(self, async_client, fake_redis):
        sid = await _create_session(async_client)
        resp = await async_client.post(
            f"/v1/onboarding/session/{sid}/errors",
            json=_valid_body(),
        )
        assert resp.status_code == 204
        ttl = await fake_redis.ttl(f"sena:onboarding:errors:{sid}")
        # 7 days in seconds = 604800. Allow some slack for fake_redis timing.
        assert 600_000 < ttl <= 604_800

    async def test_missing_input_method_returns_422(self, async_client):
        sid = await _create_session(async_client)
        body = _valid_body()
        body.pop("input_method")

        resp = await async_client.post(
            f"/v1/onboarding/session/{sid}/errors", json=body,
        )
        assert resp.status_code == 422

    async def test_extra_field_rejected_with_422(self, async_client):
        sid = await _create_session(async_client)
        body = _valid_body()
        body["unexpected_extra_field"] = "x"

        resp = await async_client.post(
            f"/v1/onboarding/session/{sid}/errors", json=body,
        )
        assert resp.status_code == 422

    async def test_invalid_input_method_value_returns_422(self, async_client):
        sid = await _create_session(async_client)
        body = _valid_body()
        body["input_method"] = "telepathy"  # not in Literal["typed", "voice"]

        resp = await async_client.post(
            f"/v1/onboarding/session/{sid}/errors", json=body,
        )
        assert resp.status_code == 422

    async def test_missing_session_returns_404(self, async_client):
        resp = await async_client.post(
            "/v1/onboarding/session/does-not-exist/errors",
            json=_valid_body(),
        )
        assert resp.status_code == 404

    async def test_wrong_tenant_returns_403(self, async_client):
        """Cross-tenant isolation: a caller from another tenant cannot
        report errors against this session. assert_session_owner raises
        403; we only validate the route honours the guard.
        """
        # Create session with a fixed tenant via the underlying repo by
        # using create-session route's tenant_id field, then POST as a
        # caller carrying a different tenant in the headers.
        schema = _personal_schema_payload()
        resp = await async_client.post(
            "/v1/onboarding/session",
            json={
                "participant_id": "part-tenant-a",
                "step": "personal_information",
                "schema": schema,
                "tenant_id": "tenant-a",
            },
        )
        assert resp.status_code == 201
        sid = resp.json()["session_id"]

        resp = await async_client.post(
            f"/v1/onboarding/session/{sid}/errors",
            json=_valid_body(),
            headers={
                "X-Tenant-Id": "tenant-b",
                "X-Participant-Id": "part-tenant-a",
            },
        )
        assert resp.status_code == 403

    async def test_voice_input_method_accepted(self, async_client, fake_redis):
        sid = await _create_session(async_client)
        body = _valid_body()
        body["input_method"] = "voice"

        resp = await async_client.post(
            f"/v1/onboarding/session/{sid}/errors", json=body,
        )
        assert resp.status_code == 204
        items = await fake_redis.lrange(f"sena:onboarding:errors:{sid}", 0, -1)
        assert json.loads(items[0])["input_method"] == "voice"

    async def test_attempted_value_optional(self, async_client, fake_redis):
        sid = await _create_session(async_client)
        body = _valid_body()
        body.pop("attempted_value")

        resp = await async_client.post(
            f"/v1/onboarding/session/{sid}/errors", json=body,
        )
        assert resp.status_code == 204

    async def test_multiple_errors_accumulate(self, async_client, fake_redis):
        sid = await _create_session(async_client)

        for _ in range(3):
            resp = await async_client.post(
                f"/v1/onboarding/session/{sid}/errors", json=_valid_body(),
            )
            assert resp.status_code == 204

        items = await fake_redis.lrange(f"sena:onboarding:errors:{sid}", 0, -1)
        assert len(items) == 3


class TestErrorsRepoCompanion:
    """Repository-level coverage for the unexposed read companion."""

    async def test_read_client_validation_errors_returns_list(
        self, repo, fake_redis,
    ):
        sid = "sess-readback"
        await repo.append_client_validation_error(
            sid,
            {
                "error_type": "phone_invalid",
                "error_message": "Enter a valid Australian phone number",
                "input_method": "voice",
                "field_id": "basics.phone",
                "attempted_value": "0",
                "ts": datetime.now(UTC).isoformat(),
            },
        )
        read = await repo.read_client_validation_errors(sid)
        assert len(read) == 1
        assert read[0]["error_type"] == "phone_invalid"

    async def test_read_empty_when_no_errors(self, repo):
        assert await repo.read_client_validation_errors("nope") == []
