from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_auth_context, get_case_note_client, get_db, get_repo
from clients.case_note_client import CaseNoteClient
from main import create_app
from models.schemas import AuthContext
from repositories.review_repo import ReviewRepo

# ── Shared test IDs ───────────────────────────────────────────────────────────

TENANT_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
USER_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
STAFF_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000003")
CLIENT_ID = uuid.UUID("dddddddd-0000-0000-0000-000000000004")

TEST_AUTH_HEADERS = {
    "X-Tenant-Id": str(TENANT_ID),
    "X-User-Id": str(USER_ID),
    "X-User-Roles": "worker",
}


# ── Mock auth ─────────────────────────────────────────────────────────────────

def _mock_auth() -> AuthContext:
    return AuthContext(tenant_id=TENANT_ID, user_id=USER_ID, roles=["worker"])


# ── Mock repo ─────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_repo() -> ReviewRepo:
    repo = MagicMock(spec=ReviewRepo)
    repo.get_rolling_summary = AsyncMock(return_value=None)
    repo.upsert_rolling_summary = AsyncMock()
    repo.get_review_session = AsyncMock(return_value=None)
    repo.create_review_session = AsyncMock()
    repo.update_review_session = AsyncMock()
    repo.create_incident_draft = AsyncMock()
    repo.get_incident_draft = AsyncMock(return_value=None)
    repo.confirm_incident_draft = AsyncMock()
    repo.append_audit = AsyncMock()
    repo.list_audit = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_db() -> AsyncSession:
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def stub_client() -> CaseNoteClient:
    return CaseNoteClient(stub=True)


# ── TestClient with dependency overrides ──────────────────────────────────────

@pytest.fixture
def client(mock_repo: ReviewRepo, mock_db: AsyncSession, stub_client: CaseNoteClient) -> TestClient:
    app = create_app()

    app.dependency_overrides[get_auth_context] = _mock_auth
    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_repo] = lambda: mock_repo
    app.dependency_overrides[get_case_note_client] = lambda: stub_client

    return TestClient(app)
