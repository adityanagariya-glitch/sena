from __future__ import annotations

"""
Classify service — orchestrates paragraph classification and session persistence.

DUAL CACHING STRATEGY:
  1. Session-level dedup: SHA256 hash of paragraph prevents LLM calls for same text in session
  2. Claude prompt caching: Static field schema + instructions cached by Claude, only dynamic
     paragraph sent on each request → reduced token cost

Flow:
  1. Create or update review_session
  2. Check session cache (same paragraph hash → return cached classification, 0 LLM cost)
  3. Call LLM classifier (Claude caches static schema/instructions, only uses tokens for dynamic paragraph)
  4. Persist classified_fields + missing_fields to review_session (status → classified)
  5. Append audit log entry
  6. Return ClassifyResponse
"""

import hashlib
import uuid

import structlog

from core.settings import settings
from models.case_note_field_schema import FIELD_BY_ID
from models.schemas import ClassifyRequest, ClassifyResponse, ReaskPrompt
from repositories.review_repo import ReviewRepo
from services.llm.classifier import classify

log = structlog.get_logger(__name__)


def _hash_paragraph(paragraph: str) -> str:
    """Generate SHA256 hash of paragraph for deduplication."""
    return hashlib.sha256(paragraph.encode()).hexdigest()


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

    # ── 2. Check cache (paragraph deduplication within session) ────────────────
    para_hash = _hash_paragraph(req.raw_paragraph)
    if session.classified_fields and session.raw_paragraph == req.raw_paragraph:
        # Same paragraph already classified in this session
        log.info("classify_service.cache_hit", session_id=str(session.id), para_hash=para_hash)
        return ClassifyResponse(
            review_session_id=session.id,
            classified_fields=session.classified_fields or {},
            confidence={},
            missing_required=session.missing_fields or [],
            reask_prompts=[],
            status="classified",
        )

    # ── 3. Call LLM classifier ────────────────────────────────────────────────
    result = await classify(
        raw_paragraph=req.raw_paragraph,
        api_key=settings.gemini_api_key,
        model_id=settings.bedrock_model_id,
        tenant_id=str(tenant_id),
        user_id=str(user_id),
        session_id=str(session.id),
    )

    # ── 4. Persist results ────────────────────────────────────────────────────
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

    # ── 5. Audit log ──────────────────────────────────────────────────────────
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

    # ── 6. Build response ─────────────────────────────────────────────────────
    return ClassifyResponse(
        review_session_id=session.id,
        classified_fields=result.classified_fields,
        missing_fields=missing_fields_payload,
        reask_prompts=[ReaskPrompt(**rp) for rp in result.reask_prompts],
        status=session.status,
    )
