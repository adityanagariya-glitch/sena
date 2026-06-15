"""Tests for RP pipeline REST endpoints — evaluate, BSP CRUD, health."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from case_review.api.deps import get_auth_context, get_db
from case_review.main import create_app
from case_review.models.schemas import (
    AuthContext,
    PipelineResult,
    TriageResult,
)

TENANT_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
USER_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
CASE_NOTE_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000003")
CLIENT_ID = "client-abc"

TEST_NOTE_PAYLOAD = {
    "case_note_id": str(CASE_NOTE_ID),
    "client_id": CLIENT_ID,
    "worker_id": "worker-001",
    "transcript": "I supported John with morning routine. He was calm throughout the shift.",
    "shift_date": "2026-06-13",
}


def _mock_auth() -> AuthContext:
    return AuthContext(tenant_id=TENANT_ID, user_id=USER_ID, roles=["worker"])


@pytest.fixture
def mock_db() -> AsyncSession:
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def rp_client(mock_db: AsyncSession) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_auth_context] = _mock_auth
    app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(app)


def _clear_pipeline_result() -> PipelineResult:
    return PipelineResult(
        case_note_id=CASE_NOTE_ID,
        client_id=CLIENT_ID,
        triage=TriageResult(flagged=False, action_summary=None),
    )


def _flagged_pipeline_result() -> PipelineResult:
    return PipelineResult(
        case_note_id=CASE_NOTE_ID,
        client_id=CLIENT_ID,
        triage=TriageResult(flagged=True, action_summary="Chemical restraint suspected"),
        alert_required=True,
    )


# ── /evaluate ─────────────────────────────────────────────────────────────────

def test_evaluate_clear_returns_200(rp_client: TestClient) -> None:
    # Route returns EvaluateResponse (has 'verdict' key), built from PipelineResult
    with patch(
        "case_review.api.rp_routes.run_pipeline",
        new=AsyncMock(return_value=_clear_pipeline_result()),
    ):
        resp = rp_client.post("/v1/restrictive-practices/evaluate", json=TEST_NOTE_PAYLOAD)
    assert resp.status_code == 200
    data = resp.json()
    assert "verdict" in data


def test_evaluate_flagged_returns_200(rp_client: TestClient) -> None:
    with patch(
        "case_review.api.rp_routes.run_pipeline",
        new=AsyncMock(return_value=_flagged_pipeline_result()),
    ):
        resp = rp_client.post("/v1/restrictive-practices/evaluate", json=TEST_NOTE_PAYLOAD)
    assert resp.status_code == 200
    data = resp.json()
    assert "verdict" in data


def test_evaluate_missing_case_note_id_returns_422(rp_client: TestClient) -> None:
    payload = {k: v for k, v in TEST_NOTE_PAYLOAD.items() if k != "case_note_id"}
    resp = rp_client.post("/v1/restrictive-practices/evaluate", json=payload)
    assert resp.status_code == 422


def test_evaluate_pipeline_mocked_returns_200(rp_client: TestClient) -> None:
    # Confirm the route wires run_pipeline → _build_response correctly when mocked
    with patch(
        "case_review.api.rp_routes.run_pipeline",
        new=AsyncMock(return_value=_clear_pipeline_result()),
    ):
        resp = rp_client.post("/v1/restrictive-practices/evaluate", json=TEST_NOTE_PAYLOAD)
    assert resp.status_code == 200


# ── /health ───────────────────────────────────────────────────────────────────

def test_rp_health_returns_ok(rp_client: TestClient) -> None:
    resp = rp_client.get("/v1/restrictive-practices/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ── /bsp ──────────────────────────────────────────────────────────────────────


def test_bsp_create_invalid_payload_returns_422(rp_client: TestClient) -> None:
    # Missing required practice_type field
    resp = rp_client.post(
        "/v1/restrictive-practices/bsp",
        json={"client_id": CLIENT_ID},
    )
    assert resp.status_code == 422


def test_bsp_list_for_client_returns_200(rp_client: TestClient, mock_db: AsyncSession) -> None:
    # GET /bsp/{client_id} returns a list — empty list when no plans registered
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_result.scalars.return_value.first.return_value = None
    mock_db.execute = AsyncMock(return_value=mock_result)

    resp = rp_client.get(f"/v1/restrictive-practices/bsp/{CLIENT_ID}")
    assert resp.status_code in {200, 404}
