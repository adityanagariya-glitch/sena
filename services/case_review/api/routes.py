from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_auth_context, get_bearer_token, get_case_note_client, get_db, get_repo
from clients.case_note_client import CaseNoteClient
from services.classify_service import classify_paragraph as svc_classify_paragraph
from services.context_service import get_context as svc_get_context
from services.review_service import review_session_pipeline as svc_review
from services.incident_service import (
    detect_incident as svc_detect_incident,
    draft_incident as svc_draft_incident,
    confirm_incident as svc_confirm_incident,
)
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
    TokenUsage,
)
from repositories.review_repo import ReviewRepo
from core.settings import settings
# Canonical import path (must match every other accumulator import — see usage.py).
from case_review.services.usage import get_usage, start_usage

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

@router.post(
    "/v1/case-review/context",
    response_model=ContextResponse,
    tags=["context"],
    summary="Rolling case-note summary for the calling staff member + client",
    description=(
        "Fetches the most recent case notes for the **authenticated staff member** and a "
        "given client, and returns a rolling summary (pre-meeting brief).\n\n"
        "**Source of case notes** — the SENA org backend (member-scoped `/mobile` "
        "endpoints), fetched in two steps. The caller's JWT is **forwarded** as the "
        "outbound `Authorization`, so the member is the token subject:\n"
        "1. `GET /mobile/organization-member/case-note/get-all-data?clientId=&limit="
        "&page=1&sortByStartTime=d` → newest `(shiftId, clientId)` references for this member.\n"
        "2. `GET /mobile/organization-member/case-note/get-data/{shiftId}/{clientId}` "
        "(one call per note, concurrent) → full structured content, composed into the "
        "note body the summarizer ingests.\n\n"
        "`staff_id` is the caller's own member id (used for storage keying); the fetch "
        "itself is scoped by the JWT. At most `limit` notes are fetched, hard-capped at "
        "the service's `case_note_fetch_limit` (default 10).\n\n"
        "**Idempotent** — re-calling with the same notes returns the cached rolling "
        "summary with no LLM call; only new notes trigger a re-summarise and are merged "
        "into `processed_note_ids`.\n\n"
        "_Dev note: when `SENA_AI_CASE_NOTE_USE_STUB=true` (default) notes come from local "
        "fixtures instead of the org backend._"
    ),
)
async def get_context(
    req: ContextRequest,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
    client: CaseNoteClient = Depends(get_case_note_client),
    bearer_token: str = Depends(get_bearer_token),
) -> ContextResponse:
    """
    Fetch the most recent N case notes for the calling staff member + client and
    return a rolling summary.

    Notes are sourced from the SENA org backend (member-scoped), in two steps,
    authenticated by forwarding the caller's JWT:
      1. GET /mobile/organization-member/case-note/get-all-data?clientId=&limit=
      2. GET /mobile/organization-member/case-note/get-data/{shiftId}/{clientId} per note.

    Idempotent — re-calling with the same notes returns the cached summary (no LLM call).
    Adding new notes updates and compresses the rolling summary.
    """
    repo = get_repo(db)
    start_usage()
    result = await svc_get_context(
        repo=repo,
        client=client,
        tenant_id=auth.tenant_id,
        staff_id=req.staff_id,
        client_id=req.client_id,
        limit=req.limit,
        bearer_token=bearer_token,
    )
    result.token_usage = TokenUsage(**get_usage())
    return result


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
    start_usage()
    try:
        result = await svc_classify_paragraph(
            repo=repo,
            tenant_id=auth.tenant_id,
            user_id=auth.user_id,
            req=req,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    result.token_usage = TokenUsage(**get_usage())
    return result


# ── Review (Phase D) ──────────────────────────────────────────────────────────

@router.post(
    "/v1/case-review/review",
    response_model=ReviewResponse,
    tags=["review"],
    summary="Analyse case note for risks and compliance flags",
    description=(
        "Runs triage (cheap Haiku gate) followed by deep evaluator (Sonnet) analysis "
        "on a review session's classified case note. Returns structured flags categorised as: "
        "risks (policy violations), restrictive_practices (NDIS taxonomy), anomalies (evidence phrases), "
        "and improvements (mitigating factors). All flags are persisted to the session and queryable later. "
        "Pipeline: Triage → (if flagged) Evaluator → FlagItem mapping → DB persist."
    ),
)
async def review_session(
    req: ReviewRequest,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> ReviewResponse:
    """Analyse case note for risks and compliance flags."""
    repo = get_repo(db)
    start_usage()
    try:
        return await svc_review(
            repo=repo,
            tenant_id=auth.tenant_id,
            user_id=auth.user_id,
            req=req,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# ── Incident detect (Phase E) ─────────────────────────────────────────────────

@router.post(
    "/v1/case-review/incident/detect",
    response_model=IncidentDetectResponse,
    tags=["incident"],
    summary="Detect if case note describes a reportable incident",
    description=(
        "Binary classifier using triage + evaluator. Returns incident_detected (bool) and, "
        "if true, creates an empty IncidentDraft placeholder with draft_id for the /draft step. "
        "Also extracts trigger_phrases (evidence) from the evaluator. "
        "Pipeline: Triage → (if flagged) Evaluator → incident_detected? → create IncidentDraft."
    ),
)
async def detect_incident(
    req: IncidentDetectRequest,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> IncidentDetectResponse:
    """Detect if case note describes a reportable incident."""
    repo = get_repo(db)
    start_usage()
    return await svc_detect_incident(
        repo=repo,
        db=db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        req=req,
    )


@router.post(
    "/v1/case-review/incident/draft",
    response_model=IncidentDraftResponse,
    tags=["incident"],
    summary="Autofill NDIS incident report fields from case note",
    description=(
        "Runs the NDIS Incident Drafter LLM (Bedrock Sonnet) on the case note. "
        "Autofills 20+ fields: incident_type, date, location, staff_involved, description, "
        "contributing_factors, risk_assessment, reportable status, notification_timeframe, etc. "
        "Creates or updates the IncidentDraft row (idempotent). Staff must review and confirm "
        "via PATCH /incident/{id}/confirm before submission. NDIS non-negotiable: no auto-submit."
    ),
)
async def draft_incident(
    req: IncidentDraftRequest,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> IncidentDraftResponse:
    """Autofill NDIS incident report fields from case note."""
    repo = get_repo(db)
    start_usage()
    return await svc_draft_incident(
        repo=repo,
        db=db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        req=req,
    )


@router.patch(
    "/v1/case-review/incident/{incident_id}/confirm",
    response_model=IncidentConfirmResponse,
    tags=["incident"],
    summary="Staff confirms AI-drafted incident report",
    description=(
        "Staff explicitly confirms the AI-autofilled incident draft after review. "
        "Sets staff_confirmed=True and status='confirmed'. No auto-submit happens; the confirmed "
        "draft is then passed to submit. NDIS non-negotiable: every incident report requires "
        "human sign-off before reporting to the NDIS Commission."
    ),
)
async def confirm_incident(
    incident_id: uuid.UUID,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> IncidentConfirmResponse:
    """Staff confirms AI-drafted incident report."""
    repo = get_repo(db)
    return await svc_confirm_incident(
        repo=repo,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        incident_id=incident_id,
    )


# ── Submit ──────────────────────────────────────────────────────────

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
        detail= "submit endpoint not yet implemented (blocked: register schema TBD)",
    )
