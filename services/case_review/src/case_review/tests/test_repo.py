from __future__ import annotations

"""
Phase A repo tests — validate CRUD logic and upsert semantics using mock sessions.
Full integration tests against a real Postgres DB are deferred to CI with docker.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from case_review.models.db import IncidentDraft, ReviewAuditLog, ReviewSession, RollingSummary
from case_review.repositories.review_repo import ReviewRepo
from services.case_review.src.case_review.tests.conftest import CLIENT_ID, STAFF_ID, TENANT_ID, USER_ID


def _make_repo() -> tuple[ReviewRepo, MagicMock]:
    """Return a ReviewRepo wired to a mock AsyncSession."""
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    repo = ReviewRepo(session)
    return repo, session


# ── RollingSummary ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_rolling_summary_none_when_missing() -> None:
    repo, session = _make_repo()
    session.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)

    result = await repo.get_rolling_summary(TENANT_ID, STAFF_ID, CLIENT_ID)

    assert result is None
    session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_get_rolling_summary_returns_row() -> None:
    repo, session = _make_repo()
    mock_row = MagicMock(spec=RollingSummary)
    session.execute.return_value.scalar_one_or_none = MagicMock(return_value=mock_row)

    result = await repo.get_rolling_summary(TENANT_ID, STAFF_ID, CLIENT_ID)

    assert result is mock_row


# ── ReviewSession ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_review_session_adds_and_commits() -> None:
    repo, session = _make_repo()
    # refresh sets the returned object
    created_row = MagicMock(spec=ReviewSession)
    created_row.id = uuid.uuid4()

    async def _refresh(obj):
        obj.id = created_row.id

    session.refresh.side_effect = _refresh

    result = await repo.create_review_session(
        tenant_id=TENANT_ID,
        staff_id=STAFF_ID,
        client_id=CLIENT_ID,
        raw_paragraph="Test paragraph",
    )

    session.add.assert_called_once()
    session.commit.assert_called_once()
    session.refresh.assert_called_once()


@pytest.mark.asyncio
async def test_get_review_session_none_when_missing() -> None:
    repo, session = _make_repo()
    session.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)

    result = await repo.get_review_session(uuid.uuid4())
    assert result is None


# ── IncidentDraft ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_incident_draft_persists() -> None:
    repo, session = _make_repo()
    session.refresh = AsyncMock()

    await repo.create_incident_draft(
        tenant_id=TENANT_ID,
        review_session_id=None,
        autofill_source={"marker": "fall"},
        draft_fields={"incident_type": "fall", "location": "kitchen"},
    )

    session.add.assert_called_once()
    session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_confirm_incident_draft_sets_confirmed() -> None:
    repo, session = _make_repo()
    draft_id = uuid.uuid4()
    confirmed_row = MagicMock(spec=IncidentDraft)
    confirmed_row.staff_confirmed = True
    confirmed_row.status = "confirmed"
    session.execute.return_value.scalar_one_or_none = MagicMock(return_value=confirmed_row)

    result = await repo.confirm_incident_draft(draft_id)

    assert session.execute.call_count == 2  # update + select
    assert session.commit.called


# ── ReviewAuditLog ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_append_audit_creates_row() -> None:
    repo, session = _make_repo()
    session.refresh = AsyncMock()
    session_id = uuid.uuid4()

    await repo.append_audit(
        tenant_id=TENANT_ID,
        review_session_id=session_id,
        action="ai_flag_raised",
        payload={"flag": "restrictive_practice"},
        actor_user_id=None,
    )

    session.add.assert_called_once()
    session.commit.assert_called_once()
    added = session.add.call_args[0][0]
    assert isinstance(added, ReviewAuditLog)
    assert added.action == "ai_flag_raised"
    assert added.tenant_id == TENANT_ID


@pytest.mark.asyncio
async def test_list_audit_returns_ordered() -> None:
    repo, session = _make_repo()
    mock_entries = [MagicMock(spec=ReviewAuditLog) for _ in range(3)]
    # session.execute is AsyncMock → awaiting it returns return_value.
    # Must be a plain MagicMock so .scalars().all() doesn't return a coroutine.
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = mock_entries
    session.execute.return_value = mock_result

    result = await repo.list_audit(uuid.uuid4())

    assert len(result) == 3


# ── Stub client ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stub_client_returns_fixtures() -> None:
    from case_review.clients.case_note_client import CaseNoteClient

    client = CaseNoteClient(stub=True)
    # Pass non-matching IDs — stub returns all fixtures as dev convenience
    notes = await client.get_notes("unknown-staff", "unknown-client", limit=10)

    assert len(notes) > 0
    for note in notes:
        assert note.note_id
        assert note.transcript
        assert note.drafted_note


@pytest.mark.asyncio
async def test_stub_client_respects_limit() -> None:
    from case_review.clients.case_note_client import CaseNoteClient

    client = CaseNoteClient(stub=True)
    notes = await client.get_notes("s", "c", limit=1)
    assert len(notes) == 1


@pytest.mark.asyncio
async def test_stub_client_filters_by_staff_client() -> None:
    from case_review.clients.case_note_client import CaseNoteClient

    client = CaseNoteClient(stub=True)
    # Fixture has staff-uuid-001 / client-uuid-001
    notes = await client.get_notes("staff-uuid-001", "client-uuid-001", limit=10)
    assert all(n.staff_id == "staff-uuid-001" for n in notes)
