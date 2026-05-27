from __future__ import annotations

"""
Phase B tests — context service + /context route.

All LLM calls are mocked — tests verify orchestration logic:
  - cold start (no prior summary) → LLM called, row upserted
  - incremental (new notes since last call) → LLM called, IDs merged
  - replay guard (same notes twice) → LLM NOT called, cached result returned
  - route wires correctly (200 response shape)
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from case_review.clients.case_note_client import CaseNoteClient
from case_review.models.schemas import CaseNoteDTO, ContextResponse
from case_review.repositories.review_repo import ReviewRepo
from case_review.services.context_service import get_context
from tests.conftest import CLIENT_ID, STAFF_ID, TENANT_ID


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_note(note_id: str, date: str = "2026-04-10") -> CaseNoteDTO:
    return CaseNoteDTO(
        note_id=note_id,
        date=date,
        staff_id=str(STAFF_ID),
        client_id=str(CLIENT_ID),
        transcript="Participant worked on daily living skills.",
        drafted_note="Support provided for daily living skills.",
    )


def _mock_summary_result():
    from case_review.services.llm.summarizer import SummaryResult
    return SummaryResult(
        summary_text="Participant has been progressing with daily living skills over the past 3 sessions.",
        metadata={"note_count": 2, "last_dates": ["2026-04-10"], "incident_count": 0, "risk_flags": []},
    )


def _make_existing_summary(processed_ids: list[str]) -> MagicMock:
    row = MagicMock()
    row.id = uuid.uuid4()
    row.summary_text = "Previous summary text."
    row.metadata_json = {"note_count": 1, "last_dates": ["2026-04-01"], "incident_count": 0, "risk_flags": []}
    row.processed_note_ids = processed_ids
    return row


def _make_upserted_row(summary_text: str, processed_ids: list[str]) -> MagicMock:
    row = MagicMock()
    row.id = uuid.uuid4()
    row.summary_text = summary_text
    row.metadata_json = {"note_count": len(processed_ids), "last_dates": ["2026-04-10"], "incident_count": 0, "risk_flags": []}
    row.processed_note_ids = processed_ids
    return row


# ── context_service unit tests ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cold_start_calls_llm_and_upserts() -> None:
    """No prior summary → LLM called, summary upserted."""
    repo = MagicMock(spec=ReviewRepo)
    repo.get_rolling_summary = AsyncMock(return_value=None)
    upserted = _make_upserted_row("New summary.", ["note-001", "note-002"])
    repo.upsert_rolling_summary = AsyncMock(return_value=upserted)

    client = MagicMock(spec=CaseNoteClient)
    client.get_notes = AsyncMock(return_value=[_make_note("note-001"), _make_note("note-002")])

    mock_result = _mock_summary_result()

    with patch("case_review.services.context_service.summarise", AsyncMock(return_value=mock_result)):
        result = await get_context(
            repo=repo, client=client,
            tenant_id=TENANT_ID, staff_id=STAFF_ID, client_id=CLIENT_ID,
        )

    assert isinstance(result, ContextResponse)
    assert result.notes_included == 2
    repo.upsert_rolling_summary.assert_called_once()


@pytest.mark.asyncio
async def test_replay_guard_skips_llm() -> None:
    """Same notes already processed → LLM NOT called, cached result returned."""
    existing = _make_existing_summary(["note-001", "note-002"])
    repo = MagicMock(spec=ReviewRepo)
    repo.get_rolling_summary = AsyncMock(return_value=existing)

    client = MagicMock(spec=CaseNoteClient)
    # Returns same notes already in processed_note_ids
    client.get_notes = AsyncMock(return_value=[_make_note("note-001"), _make_note("note-002")])

    with patch("case_review.services.context_service.summarise", AsyncMock()) as mock_llm:
        result = await get_context(
            repo=repo, client=client,
            tenant_id=TENANT_ID, staff_id=STAFF_ID, client_id=CLIENT_ID,
        )
        mock_llm.assert_not_called()

    assert result.summary_text == existing.summary_text
    assert result.notes_included == 2


@pytest.mark.asyncio
async def test_incremental_update_only_passes_new_notes() -> None:
    """One existing note + one new note → LLM called with only the new note."""
    existing = _make_existing_summary(["note-001"])
    repo = MagicMock(spec=ReviewRepo)
    repo.get_rolling_summary = AsyncMock(return_value=existing)
    upserted = _make_upserted_row("Updated summary.", ["note-001", "note-002"])
    repo.upsert_rolling_summary = AsyncMock(return_value=upserted)

    client = MagicMock(spec=CaseNoteClient)
    client.get_notes = AsyncMock(return_value=[_make_note("note-001"), _make_note("note-002")])

    captured_new_notes = []

    async def _capture_summarise(past_summary, new_notes, **kwargs):
        captured_new_notes.extend(new_notes)
        return _mock_summary_result()

    with patch("case_review.services.context_service.summarise", _capture_summarise):
        result = await get_context(
            repo=repo, client=client,
            tenant_id=TENANT_ID, staff_id=STAFF_ID, client_id=CLIENT_ID,
        )

    # LLM only received note-002 (note-001 already processed)
    assert len(captured_new_notes) == 1
    assert captured_new_notes[0].note_id == "note-002"
    assert result.notes_included == 2


@pytest.mark.asyncio
async def test_processed_ids_merged_correctly() -> None:
    """Upsert receives union of old + new IDs (no duplicates)."""
    existing = _make_existing_summary(["note-001"])
    repo = MagicMock(spec=ReviewRepo)
    repo.get_rolling_summary = AsyncMock(return_value=existing)
    upserted = _make_upserted_row("Summary.", ["note-001", "note-002"])
    repo.upsert_rolling_summary = AsyncMock(return_value=upserted)

    client = MagicMock(spec=CaseNoteClient)
    client.get_notes = AsyncMock(return_value=[_make_note("note-001"), _make_note("note-002")])

    with patch("case_review.services.context_service.summarise", AsyncMock(return_value=_mock_summary_result())):
        await get_context(
            repo=repo, client=client,
            tenant_id=TENANT_ID, staff_id=STAFF_ID, client_id=CLIENT_ID,
        )

    call_kwargs = repo.upsert_rolling_summary.call_args.kwargs
    ids = call_kwargs["processed_note_ids"]
    assert sorted(ids) == ["note-001", "note-002"]
    assert len(ids) == len(set(ids))  # no duplicates


# ── Route integration tests ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_context_route_returns_200(client: TestClient) -> None:
    """Route returns 200 with correct shape when service layer is mocked."""
    mock_response = ContextResponse(
        summary_text="Participant progressing well.",
        metadata={"note_count": 3, "last_dates": ["2026-04-10"], "incident_count": 0, "risk_flags": []},
        notes_included=3,
        rolling_summary_id=uuid.uuid4(),
    )

    with patch("case_review.api.routes.svc_get_context", AsyncMock(return_value=mock_response)):
        resp = client.post(
            "/v1/case-review/context",
            json={"staff_id": str(STAFF_ID), "client_id": str(CLIENT_ID), "limit": 5},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "summary_text" in data
    assert "metadata" in data
    assert data["notes_included"] == 3
    assert "rolling_summary_id" in data


@pytest.mark.asyncio
async def test_context_route_limit_validation(client: TestClient) -> None:
    """limit > 50 → 422 validation error."""
    resp = client.post(
        "/v1/case-review/context",
        json={"staff_id": str(STAFF_ID), "client_id": str(CLIENT_ID), "limit": 999},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_context_route_missing_client_id(client: TestClient) -> None:
    """Missing required field → 422."""
    resp = client.post(
        "/v1/case-review/context",
        json={"staff_id": str(STAFF_ID)},
    )
    assert resp.status_code == 422
