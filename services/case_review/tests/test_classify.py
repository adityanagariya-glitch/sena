from __future__ import annotations

"""
Phase C tests — classify service + /classify route.

All LLM calls are mocked — tests verify orchestration logic:
  - full paragraph → all required fields populated, no reask prompts
  - thin paragraph → missing_required non-empty, reask_prompts returned
  - existing session → update path used instead of create
  - audit entry appended on every call
  - route returns 200 with correct shape
  - route returns 422 on missing required body fields
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from models.case_note_field_schema import REQUIRED_FIELD_IDS
from models.schemas import ClassifyRequest, ClassifyResponse, ReaskPrompt
from repositories.review_repo import ReviewRepo
from services.classify_service import classify_paragraph
from services.llm.classifier import ClassifyResult
from tests.conftest import CLIENT_ID, STAFF_ID, TENANT_ID, USER_ID

# ── Helpers ───────────────────────────────────────────────────────────────────

SESSION_ID = uuid.uuid4()


def _full_classify_result() -> ClassifyResult:
    """All required fields populated — no reask prompts."""
    classified = {fid: f"value-for-{fid}" for fid in REQUIRED_FIELD_IDS}
    classified.update({
        "time_start": "09:00",
        "time_end": "11:00",
        "participant_goals": None,
        "progress_notes": None,
        "incidents_observed": None,
        "medications_administered": None,
        "next_steps": None,
    })
    return ClassifyResult(
        classified_fields=classified,
        confidence={fid: 0.95 for fid in classified},
        missing_required=[],
        reask_prompts=[],
    )


def _thin_classify_result() -> ClassifyResult:
    """Required fields missing — reask prompts generated."""
    classified = {fid: None for fid in REQUIRED_FIELD_IDS}
    classified.update({
        "time_start": None, "time_end": None, "participant_goals": None,
        "progress_notes": None, "incidents_observed": None,
        "medications_administered": None, "next_steps": None,
    })
    reask_prompts = [
        {
            "field_id": fid,
            "label": fid.replace("_", " ").title(),
            "reason": "Not mentioned in the paragraph.",
            "suggested_question": f"Can you tell me the {fid.replace('_', ' ')} for this session?",
        }
        for fid in REQUIRED_FIELD_IDS
    ]
    return ClassifyResult(
        classified_fields=classified,
        confidence={fid: 0.0 for fid in classified},
        missing_required=list(REQUIRED_FIELD_IDS),
        reask_prompts=reask_prompts,
    )


def _make_session(session_id: uuid.UUID = SESSION_ID, status: str = "classified") -> MagicMock:
    row = MagicMock()
    row.id = session_id
    row.status = status
    row.tenant_id = TENANT_ID
    row.staff_id = STAFF_ID
    row.client_id = CLIENT_ID
    return row


def _make_req(review_session_id: uuid.UUID | None = None) -> ClassifyRequest:
    return ClassifyRequest(
        staff_id=STAFF_ID,
        client_id=CLIENT_ID,
        raw_paragraph="Supported participant with meal prep on 24 April 2026 from 9am to 11am. Daily Activities. Participant was engaged and cooperative. No incidents observed.",
        review_session_id=review_session_id,
    )


# ── classify_service unit tests ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_full_paragraph_no_reask() -> None:
    """Well-formed paragraph → all required fields filled, no reask prompts."""
    repo = MagicMock(spec=ReviewRepo)
    repo.create_review_session = AsyncMock(return_value=_make_session())
    repo.update_review_session = AsyncMock(return_value=_make_session())
    repo.append_audit = AsyncMock()

    with patch("services.classify_service.classify", AsyncMock(return_value=_full_classify_result())):
        result = await classify_paragraph(
            repo=repo,
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            req=_make_req(),
        )

    assert isinstance(result, ClassifyResponse)
    assert result.reask_prompts == []
    assert result.missing_fields == []
    assert result.status == "classified"
    assert all(v is not None for v in result.classified_fields.values() if k in REQUIRED_FIELD_IDS
               for k, v in result.classified_fields.items() if k in REQUIRED_FIELD_IDS)


@pytest.mark.asyncio
async def test_thin_paragraph_returns_reask() -> None:
    """Sparse paragraph → missing_required non-empty, reask_prompts returned."""
    repo = MagicMock(spec=ReviewRepo)
    repo.create_review_session = AsyncMock(return_value=_make_session())
    repo.update_review_session = AsyncMock(return_value=_make_session())
    repo.append_audit = AsyncMock()

    with patch("services.classify_service.classify", AsyncMock(return_value=_thin_classify_result())):
        result = await classify_paragraph(
            repo=repo,
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            req=_make_req(),
        )

    assert len(result.reask_prompts) == len(REQUIRED_FIELD_IDS)
    assert len(result.missing_fields) == len(REQUIRED_FIELD_IDS)
    missing_ids = {mf["field_id"] for mf in result.missing_fields}
    assert missing_ids == set(REQUIRED_FIELD_IDS)
    for rp in result.reask_prompts:
        assert isinstance(rp, ReaskPrompt)
        assert rp.suggested_question


@pytest.mark.asyncio
async def test_existing_session_uses_update_path() -> None:
    """Passing review_session_id → get + update instead of create."""
    existing_session = _make_session(SESSION_ID)
    repo = MagicMock(spec=ReviewRepo)
    repo.get_review_session = AsyncMock(return_value=existing_session)
    repo.update_review_session = AsyncMock(return_value=_make_session())
    repo.append_audit = AsyncMock()

    with patch("services.classify_service.classify", AsyncMock(return_value=_full_classify_result())):
        result = await classify_paragraph(
            repo=repo,
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            req=_make_req(review_session_id=SESSION_ID),
        )

    repo.get_review_session.assert_called_once_with(SESSION_ID)
    repo.create_review_session.assert_not_called()
    assert isinstance(result, ClassifyResponse)


@pytest.mark.asyncio
async def test_audit_appended_on_classify() -> None:
    """Audit log entry is written after every classify call."""
    repo = MagicMock(spec=ReviewRepo)
    repo.create_review_session = AsyncMock(return_value=_make_session())
    repo.update_review_session = AsyncMock(return_value=_make_session())
    repo.append_audit = AsyncMock()

    with patch("services.classify_service.classify", AsyncMock(return_value=_full_classify_result())):
        await classify_paragraph(
            repo=repo,
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            req=_make_req(),
        )

    repo.append_audit.assert_called_once()
    call_kwargs = repo.append_audit.call_args.kwargs
    assert call_kwargs["action"] == "ai_classify_complete"
    assert call_kwargs["actor_user_id"] == USER_ID


# ── Route integration tests ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_classify_route_returns_200(client: TestClient) -> None:
    """Route returns 200 with correct shape when service layer is mocked."""
    mock_response = ClassifyResponse(
        review_session_id=SESSION_ID,
        classified_fields={fid: f"v-{fid}" for fid in REQUIRED_FIELD_IDS},
        missing_fields=[],
        reask_prompts=[],
        status="classified",
    )

    with patch("api.routes.svc_classify_paragraph", AsyncMock(return_value=mock_response)):
        resp = client.post(
            "/v1/case-review/classify",
            json={
                "staff_id": str(STAFF_ID),
                "client_id": str(CLIENT_ID),
                "raw_paragraph": "Supported participant with meal prep today.",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "review_session_id" in data
    assert "classified_fields" in data
    assert "missing_fields" in data
    assert "reask_prompts" in data
    assert data["status"] == "classified"


@pytest.mark.asyncio
async def test_classify_route_missing_paragraph(client: TestClient) -> None:
    """Missing raw_paragraph → 422 validation error."""
    resp = client.post(
        "/v1/case-review/classify",
        json={"staff_id": str(STAFF_ID), "client_id": str(CLIENT_ID)},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_classify_route_reask_response_shape(client: TestClient) -> None:
    """When reask_prompts are present they match ReaskPrompt schema."""
    reask = ReaskPrompt(
        field_id="date_of_support",
        label="Date of Support",
        reason="Not mentioned.",
        suggested_question="What date did you support this participant?",
    )
    mock_response = ClassifyResponse(
        review_session_id=SESSION_ID,
        classified_fields={"date_of_support": None},
        missing_fields=[{"field_id": "date_of_support", "label": "Date of Support"}],
        reask_prompts=[reask],
        status="classified",
    )

    with patch("api.routes.svc_classify_paragraph", AsyncMock(return_value=mock_response)):
        resp = client.post(
            "/v1/case-review/classify",
            json={
                "staff_id": str(STAFF_ID),
                "client_id": str(CLIENT_ID),
                "raw_paragraph": "Visited client.",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["reask_prompts"]) == 1
    rp = data["reask_prompts"][0]
    assert rp["field_id"] == "date_of_support"
    assert rp["suggested_question"]
    assert len(data["missing_fields"]) == 1
