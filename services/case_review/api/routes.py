from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from deps import get_auth_context, get_case_note_client, get_db, get_repo
from clients.case_note_client import CaseNoteClient
from services.classify_service import classify_paragraph as svc_classify_paragraph
from services.context_service import get_context as svc_get_context
from models.schemas import (
    AuthContext,
    ClassifyRequest,
    ClassifyResponse,
    ContextRequest,
    ContextResponse,
    HealthResponse,
    IncidentConfirmResponse,
    IncidentDetectRequest,
    IncidentDetectResponse,
    IncidentDraftRequest,
    IncidentDraftResponse,
    ReviewRequest,
    ReviewResponse,
    SubmitRequest,
    SubmitResponse,
)
from repositories.review_repo import ReviewRepo
from core.settings import settings

router = APIRouter()


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/health/live", response_model=HealthResponse, tags=["health"])
async def health_live() -> HealthResponse:
    return HealthResponse(status="ok", version=settings.service_version)


@router.get("/health/ready", response_model=HealthResponse, tags=["health"])
async def health_ready() -> HealthResponse:
    # Phase A: DB check deferred — returns ok if service is up
    return HealthResponse(status="ok", version=settings.service_version)


# ── Context (Phase B) ─────────────────────────────────────────────────────────

@router.post("/v1/case-review/context", response_model=ContextResponse, tags=["context"])
async def get_context(
    req: ContextRequest,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
    client: CaseNoteClient = Depends(get_case_note_client),
) -> ContextResponse:
    """
    Fetch the last N case notes for a staff-client pair and return a rolling summary.
    Idempotent — re-calling with same notes returns cached summary (no LLM call).
    Adding new notes updates and compresses the rolling summary.
    """
    repo = get_repo(db)
    return await svc_get_context(
        repo=repo,
        client=client,
        tenant_id=auth.tenant_id,
        staff_id=req.staff_id,
        client_id=req.client_id,
        limit=req.limit,
    )


# ── Classify (Phase C) ────────────────────────────────────────────────────────

@router.post("/v1/case-review/classify", response_model=ClassifyResponse, tags=["classify"])
async def classify_paragraph(
    req: ClassifyRequest,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> ClassifyResponse:
    """
    Classify a free-text paragraph into structured case note fields.
    Returns missing required fields and re-ask prompts if paragraph is thin.
    """
    repo = get_repo(db)
    try:
        return await svc_classify_paragraph(
            repo=repo,
            tenant_id=auth.tenant_id,
            user_id=auth.user_id,
            req=req,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# ── Review (Phase D) ──────────────────────────────────────────────────────────

@router.post("/v1/case-review/review", response_model=ReviewResponse, tags=["review"])
async def review_session(
    req: ReviewRequest,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> ReviewResponse:
    """
    Analyse classified fields against rolling history.
    Returns risk flags, restrictive-practice categories (NDIS taxonomy),
    anomalies vs history, and improvement suggestions.
    Implemented in Phase D.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Phase D — review endpoint not yet implemented",
    )


# ── Incident detect (Phase E) ─────────────────────────────────────────────────

@router.post(
    "/v1/case-review/incident/detect",
    response_model=IncidentDetectResponse,
    tags=["incident"],
)
async def detect_incident(
    req: IncidentDetectRequest,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> IncidentDetectResponse:
    """
    Binary classifier: does this case note describe a reportable incident?
    If yes, creates an IncidentDraft and returns draft_id for the autofill step.
    Implemented in Phase E.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Phase E — incident/detect endpoint not yet implemented",
    )


@router.post(
    "/v1/case-review/incident/draft",
    response_model=IncidentDraftResponse,
    tags=["incident"],
)
async def draft_incident(
    req: IncidentDraftRequest,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> IncidentDraftResponse:
    """
    Autofill incident form fields from case note text.
    Staff must review and confirm (PATCH /incident/{id}/confirm) before submit.
    Implemented in Phase E.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Phase E — incident/draft endpoint not yet implemented",
    )


@router.patch(
    "/v1/case-review/incident/{incident_id}/confirm",
    response_model=IncidentConfirmResponse,
    tags=["incident"],
)
async def confirm_incident(
    incident_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> IncidentConfirmResponse:
    """
    Staff explicitly confirms the AI-autofilled incident draft.
    NDIS non-negotiable: no auto-submit without human confirmation.
    Implemented in Phase E.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Phase E — incident confirm endpoint not yet implemented",
    )


# ── Submit (Phase F) ──────────────────────────────────────────────────────────

@router.post("/v1/case-review/submit", response_model=SubmitResponse, tags=["submit"])
async def submit_review(
    req: SubmitRequest,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> SubmitResponse:
    """
    Final submit gate. Validates all flags acknowledged by staff, then writes
    to the case note register and routes any confirmed incident separately.
    BLOCKED on other engineer's register schema (Phase F).
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Phase F — submit endpoint not yet implemented (blocked: register schema TBD)",
    )
