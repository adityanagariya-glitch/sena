from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from voice.api.deps import get_ai_db, get_shared_db, redis_client
from voice.models.schemas import (
    ApprovalDecisionRequest,
    ApprovalDecisionResponse,
    EndSessionRequest,
    EndSessionResponse,
    SessionStatusResponse,
    StartSessionRequest,
    StartSessionResponse,
    TurnRequest,
    TurnResponse,
)
from voice.repositories.voice_repo import VoiceRepository
from voice.services.approval_service import ApprovalService
from voice.services.auth_service import AuthContext, auth_context_dependency, require_roles
from voice.services.bedrock_service import BedrockService
from voice.services.dictation_service import DictationService
from voice.services.event_service import EventService
from voice.services.livekit_service import generate_livekit_access
from voice.services.redis_service import RedisService
from voice.services.transcribe_service import TranscribeService
from voice.core.settings import settings
from voice.utils.idempotency import build_idempotency_key

router = APIRouter()
repo = VoiceRepository()
redis_service = RedisService(redis_client)
dictation_service = DictationService(repo, redis_service, BedrockService(), TranscribeService())
approval_service = ApprovalService(repo)
event_service = EventService()


@router.get("/health/live")
async def health_live() -> dict:
    return {
        "status": "alive",
        "service": settings.service_name,
        "version": settings.service_version,
    }


@router.get("/health/ready")
async def health_ready(
    ai_db: AsyncSession = Depends(get_ai_db), shared_db: AsyncSession = Depends(get_shared_db)
) -> dict:
    checks = {
        "ai_database": "healthy",
        "shared_database": "healthy",
        "redis": "healthy",
        "bedrock": "healthy",
        "sns": "healthy",
    }
    overall = "healthy"
    try:
        await ai_db.execute("SELECT 1")
    except Exception:
        checks["ai_database"] = "unhealthy"
    try:
        await shared_db.execute("SELECT 1")
    except Exception:
        checks["shared_database"] = "unhealthy"
    try:
        await redis_client.ping()
    except Exception:
        checks["redis"] = "unhealthy"
    try:
        event_service.sns.get_topic_attributes(TopicArn=settings.sns_case_note_topic_arn)
    except Exception:
        checks["sns"] = "unhealthy"
    if "unhealthy" in checks.values():
        overall = "degraded"
    return {"status": overall, "checks": checks}


@router.post("/v1/voice/session", status_code=201, response_model=StartSessionResponse)
async def start_session(
    req: StartSessionRequest,
    auth: AuthContext = Depends(auth_context_dependency),
    ai_db: AsyncSession = Depends(get_ai_db),
):
    require_roles(auth, {"support_worker", "manager", "admin"})
    await redis_service.increment_rate_limit(
        f"start:{auth.tenant_id}", settings.rate_limit_start_per_minute
    )

    lock_ok = await redis_service.acquire_participant_lock(
        str(auth.tenant_id), str(req.participant_id), "pending"
    )
    if not lock_ok:
        existing = await redis_service.get_existing_session(
            str(auth.tenant_id), str(req.participant_id)
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "Active session exists", "existing_session_id": existing},
        )

    session = await dictation_service.start_session(
        db=ai_db,
        tenant_id=auth.tenant_id,
        participant_id=req.participant_id,
        staff_id=req.staff_id,
        shift_id=req.shift_id,
        objective=req.objective,
    )
    await ai_db.commit()

    await redis_service.release_participant_lock(str(auth.tenant_id), str(req.participant_id))
    await redis_service.acquire_participant_lock(
        str(auth.tenant_id), str(req.participant_id), str(session.id)
    )

    livekit = generate_livekit_access(
        session_id=str(session.id), participant_name=str(auth.user_id)
    )

    return StartSessionResponse(
        session_id=session.id,
        status=session.status,
        objective=session.objective,
        lock_acquired=True,
        livekit=livekit,
    )


@router.post("/v1/voice/session/turn", response_model=TurnResponse)
async def process_turn(
    req: TurnRequest,
    auth: AuthContext = Depends(auth_context_dependency),
    ai_db: AsyncSession = Depends(get_ai_db),
):
    require_roles(auth, {"support_worker", "manager", "admin"})
    await redis_service.increment_rate_limit(
        f"turn:{auth.tenant_id}:{req.session_id}", settings.rate_limit_turn_per_minute
    )

    result = await dictation_service.process_turn(
        db=ai_db,
        session_id=req.session_id,
        transcript=req.transcript,
        transcript_confidence=req.transcript_confidence,
        sequence_number=req.sequence_number,
    )
    await ai_db.commit()

    return TurnResponse(
        session_id=req.session_id,
        sequence_number=req.sequence_number,
        agent_reply=result["agent_reply"],
        draft_preview=result["draft_preview"],
        completeness_score=result["completeness_score"],
        missing_topics=result["missing_topics"],
        model=settings.bedrock_model_id,
        latency_ms=result["latency_ms"],
    )


@router.post("/v1/voice/session/end", response_model=EndSessionResponse)
async def end_session(
    req: EndSessionRequest,
    auth: AuthContext = Depends(auth_context_dependency),
    ai_db: AsyncSession = Depends(get_ai_db),
):
    require_roles(auth, {"support_worker", "manager", "admin"})

    session = await repo.get_session_by_id(ai_db, req.session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if session.status != "ACTIVE":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session already ended")

    state = await redis_service.load_session_state(str(req.session_id))
    sections = state.get("draft_sections", {})
    coverage = state.get("section_coverage", {})
    missing = state.get("missing_topics", [])
    safety_category = state.get("safety_category", "normal")

    narrative = " ".join([v for v in sections.values() if isinstance(v, str) and v.strip()]).strip()
    score = float(sum(float(v) for v in coverage.values()) / max(len(coverage), 1))

    case_note_json = {
        "participant_id": str(session.participant_id),
        "staff_id": str(session.staff_id),
        "shift_id": str(session.shift_id),
        "narrative": narrative,
        "sections": sections,
        "section_scores": coverage,
        "overall_completeness_score": score,
        "missing_topics": missing,
        "compiled_at": datetime.now(timezone.utc).isoformat(),
    }

    draft = await repo.create_case_note_draft(
        db=ai_db,
        tenant_id=session.tenant_id,
        session_id=session.id,
        participant_id=session.participant_id,
        staff_id=session.staff_id,
        shift_id=session.shift_id,
        draft_json=case_note_json,
        completeness_score=score,
        missing_topics=missing,
        safety_category=safety_category,
    )
    tier = 3 if safety_category == "urgent" else 2
    approval = await repo.create_approval_item(
        db=ai_db,
        tenant_id=session.tenant_id,
        item_id=draft.id,
        participant_id=session.participant_id,
        note_version=draft.note_version,
        tier=tier,
    )

    event_payload = event_service.build_case_note_submitted_event(
        tenant_id=str(session.tenant_id),
        case_note_id=str(draft.id),
        summary=narrative,
        version=draft.note_version,
    )
    outbox = await repo.insert_outbox(
        db=ai_db,
        tenant_id=session.tenant_id,
        event_type="case_note.submitted",
        payload=event_payload,
        idempotency_key=build_idempotency_key(str(draft.id), draft.note_version),
    )

    event_id = event_service.publish_case_note_event(event_payload)
    await repo.mark_outbox_published(ai_db, outbox.id, datetime.now(timezone.utc))
    await repo.mark_session_completed(ai_db, session.id, req.ended_at)
    await ai_db.commit()

    await redis_service.release_participant_lock(str(auth.tenant_id), str(session.participant_id))

    return EndSessionResponse(
        session_id=session.id,
        draft_id=draft.id,
        approval_item_id=approval.id,
        event_id=UUID(event_id),
        status="PENDING_APPROVAL",
        case_note=case_note_json,
    )


@router.get("/v1/voice/session/{session_id}", response_model=SessionStatusResponse)
async def get_session_status(
    session_id: UUID,
    auth: AuthContext = Depends(auth_context_dependency),
    ai_db: AsyncSession = Depends(get_ai_db),
):
    require_roles(auth, {"support_worker", "manager", "admin"})
    session = await repo.get_session_by_id(ai_db, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    coverage = session.section_coverage or {}
    score = float(sum(float(v) for v in coverage.values()) / max(len(coverage), 1))
    return SessionStatusResponse(
        session_id=session.id,
        status=session.status,
        objective=session.objective,
        turn_count=session.turn_count,
        completeness_score=score,
        missing_topics=session.missing_topics or [],
    )


@router.post("/v1/approval/decision", response_model=ApprovalDecisionResponse)
async def approval_decision(
    req: ApprovalDecisionRequest,
    auth: AuthContext = Depends(auth_context_dependency),
    ai_db: AsyncSession = Depends(get_ai_db),
    shared_db: AsyncSession = Depends(get_shared_db),
):
    require_roles(auth, {"manager", "admin"})
    result = await approval_service.decide(
        ai_db=ai_db,
        shared_db=shared_db,
        approval_item_id=req.approval_item_id,
        decision=req.decision,
        reviewer_id=req.reviewer_id,
        review_notes=req.review_notes,
    )
    await shared_db.commit()
    await ai_db.commit()
    return ApprovalDecisionResponse(**result)
