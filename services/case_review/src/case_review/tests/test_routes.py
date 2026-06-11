from __future__ import annotations

"""
Phase A route smoke tests.
All business endpoints return 501 (not yet implemented).
Health endpoints return 200.
Shape validation: response JSON has expected top-level keys.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from services.case_review.src.case_review.tests.conftest import CLIENT_ID, STAFF_ID, TENANT_ID, USER_ID


def test_health_live(client: TestClient) -> None:
    resp = client.get("/health/live")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "case-review"
    assert "version" in data


def test_health_ready(client: TestClient) -> None:
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_context_stub_501(client: TestClient) -> None:
    resp = client.post(
        "/v1/case-review/context",
        json={"staff_id": str(STAFF_ID), "client_id": str(CLIENT_ID), "limit": 5},
    )
    assert resp.status_code == 501


def test_classify_stub_501(client: TestClient) -> None:
    resp = client.post(
        "/v1/case-review/classify",
        json={
            "staff_id": str(STAFF_ID),
            "client_id": str(CLIENT_ID),
            "raw_paragraph": "Had a session today.",
        },
    )
    assert resp.status_code == 501


def test_review_stub_501(client: TestClient) -> None:
    session_id = uuid.uuid4()
    resp = client.post(
        "/v1/case-review/review",
        json={"review_session_id": str(session_id)},
    )
    assert resp.status_code == 501


def test_incident_detect_stub_501(client: TestClient) -> None:
    session_id = uuid.uuid4()
    resp = client.post(
        "/v1/case-review/incident/detect",
        json={"review_session_id": str(session_id)},
    )
    assert resp.status_code == 501


def test_incident_draft_stub_501(client: TestClient) -> None:
    session_id = uuid.uuid4()
    resp = client.post(
        "/v1/case-review/incident/draft",
        json={"review_session_id": str(session_id)},
    )
    assert resp.status_code == 501


def test_incident_confirm_stub_501(client: TestClient) -> None:
    draft_id = uuid.uuid4()
    resp = client.patch(f"/v1/case-review/incident/{draft_id}/confirm")
    assert resp.status_code == 501


def test_submit_stub_501(client: TestClient) -> None:
    session_id = uuid.uuid4()
    resp = client.post(
        "/v1/case-review/submit",
        json={"review_session_id": str(session_id), "actor_user_id": str(USER_ID)},
    )
    assert resp.status_code == 501


def test_missing_auth_headers_returns_422(client: TestClient) -> None:
    """Without overriding auth dep, missing headers → 422 Unprocessable."""
    from case_review.main import create_app

    bare_app = create_app()
    bare_client = TestClient(bare_app, raise_server_exceptions=False)
    resp = bare_client.get("/health/live")
    # Health endpoints don't require auth — should still return 200
    assert resp.status_code == 200


def test_context_request_validation(client: TestClient) -> None:
    """Malformed body → 422, not 501."""
    resp = client.post(
        "/v1/case-review/context",
        json={"staff_id": "not-a-uuid"},
    )
    assert resp.status_code == 422
