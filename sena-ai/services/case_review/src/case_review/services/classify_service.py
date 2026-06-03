from __future__ import annotations

"""
Classify service — orchestrates paragraph classification and session persistence.

Flow:
  1. Create or update review_session
  2. Call LLM classifier
  3. Persist classified_fields + missing_fields to review_session (status → classified)
  4. Append audit log entry
  5. Return ClassifyResponse
"""

import uuid

import structlog

from case_review.core.settings import settings
from case_review.models.case_note_field_schema import FIELD_BY_ID
from case_review.models.schemas import ClassifyRequest, ClassifyResponse, ReaskPrompt
from case_review.repositories.review_repo import ReviewRepo
from case_review.services.llm.classifier import classify

log = structlog.get_logger(__name__)


async def classify_paragraph(
    *,
    repo: ReviewRepo,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    req: ClassifyRequest,
) -> ClassifyResponse:
    # ── 1. Resolve or create review_session ───────────────────────────────────
    if req.review_session_id:
        session = await repo.get_review_session(req.review_session_id)
        if session is None:
            raise ValueError(f"review_session {req.review_session_id} not found")
        session = await repo.update_review_session(
            req.review_session_id,
            raw_paragraph=req.raw_paragraph,
            status="input",
        )
    else:
        session = await repo.create_review_session(
            tenant_id=tenant_id,
            staff_id=req.staff_id,
            client_id=req.client_id,
            raw_paragraph=req.raw_paragraph,
            drafted_case_note_id=req.drafted_case_note_id,
        )

    assert session is not None
    log.info("classify_service.start", session_id=str(session.id))

    # ── 2. Call LLM classifier ────────────────────────────────────────────────
    result = await classify(
        raw_paragraph=req.raw_paragraph,
        api_key=settings.gemini_api_key,
        model_id=settings.gemini_model_id,
        tenant_id=str(tenant_id),
        user_id=str(user_id),
        session_id=str(session.id),
    )

    # ── 3. Persist results ────────────────────────────────────────────────────
    missing_fields_payload = [
        {
            "field_id": fid,
            "label": FIELD_BY_ID.get(fid, {}).get("label", fid),
        }
        for fid in result.missing_required
    ]

    session = await repo.update_review_session(
        session.id,
        classified_fields=result.classified_fields,
        missing_fields=missing_fields_payload,
        status="classified",
    )
    assert session is not None

    # ── 4. Audit log ──────────────────────────────────────────────────────────
    await repo.append_audit(
        tenant_id=tenant_id,
        review_session_id=session.id,
        action="ai_classify_complete",
        payload={
            "missing_required": result.missing_required,
            "reask_count": len(result.reask_prompts),
            "confidence": result.confidence,
        },
        actor_user_id=user_id,
    )

    # ── 5. Build response ─────────────────────────────────────────────────────
    return ClassifyResponse(
        review_session_id=session.id,
        classified_fields=result.classified_fields,
        missing_fields=missing_fields_payload,
        reask_prompts=[ReaskPrompt(**rp) for rp in result.reask_prompts],
        status=session.status,
    )
