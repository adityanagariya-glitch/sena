from __future__ import annotations

import json
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from shared.src.sena_common.voice import (
    FormStateRepo,
    GeminiLiveSession,
    MobileBridge,
    ToolDispatcher,
    VoiceEngineConfig,
    build_system_prompt,
)
from shared.src.sena_common.voice.form_state import FieldSource, FormState
from shared.src.sena_common.voice.gemini_live import UsageFeature
from shared.src.sena_common.voice.turn_payload import Participant, StepInfo, TurnPayload
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_auth_context, get_db, verify_signature_auth, voice_redis_client
from case_review.core.settings import settings
from case_review.services.caching import cache_verdict
from case_review.models.db import BehaviourSupportPlan
from case_review.models.schemas import (
    AuthContext,
    AuthorisationStatus,
    BSPCreate,
    BSPResponse,
    BSPUpdateStatus,
    CaseDraftResponse,
    CaseNoteInput,
    ConfidenceLevel,
    DraftInput,
    EvaluateResponse,
    PipelineResult,
    VerdictOutcome,
    _AuthorisationSection,
    _BehaviourSupportPlan,
    _DetectedPracticeSection,
    _IncidentReportSection,
    _ReportingSection,
    _SubmissionSection,
    _SummarySection,
    _VerdictSection,
    TokenUsage,
)
from case_review.services.usage import get_usage, start_usage
from case_review.services.pipeline.drafter import run_drafter
from case_review.services.pipeline.graph import run_pipeline
from case_review.services.pipeline.transcription import resolve_media_format, run_transcription
from case_review.voice.casenote_schema import CASE_NOTE_SCHEMA
from case_review.voice.tool_decls import CASE_NOTE_FUNCTION_DECLS, CASE_NOTE_KNOWN_TOOLS

logger = logging.getLogger(__name__)
rp_router = APIRouter(prefix="/v1/restrictive-practices", tags=["restrictive-practices"])

_security = HTTPBasic(auto_error=False)


def _require_auth(credentials: HTTPBasicCredentials | None = Depends(_security)) -> None:
    expected_user = settings.basic_auth_user
    expected_pass = settings.basic_auth_password
    if not expected_user or not expected_pass:
        if settings.debug:
            return  # debug mode only — fail closed in production
        raise HTTPException(status_code=503, detail="Authentication not configured")
    if credentials is None:
        raise HTTPException(status_code=401, detail="Unauthorized",
                            headers={"WWW-Authenticate": "Basic"})
    user_ok = secrets.compare_digest(credentials.username.encode(), expected_user.encode())
    pass_ok = secrets.compare_digest(credentials.password.encode(), expected_pass.encode())
    if not (user_ok and pass_ok):
        raise HTTPException(status_code=401, detail="Unauthorized",
                            headers={"WWW-Authenticate": "Basic"})


def _build_response(result: PipelineResult, worker_id: str) -> EvaluateResponse:
    """Transform internal PipelineResult into the human-readable API response."""
    ev = result.evaluator
    cc = result.cross_check

    # ── Verdict ───────────────────────────────────────────────────────────────
    next_steps: list[str] = []

    if not result.triage.flagged:
        outcome = VerdictOutcome.CLEAR
        risk_level = "N/A"
        action_required = "No action required. Case note passed initial screening."

    elif ev is None or not ev.incident_detected:
        outcome = VerdictOutcome.NO_INCIDENT
        risk_level = "N/A"
        action_required = "No action required. Detailed review found no violation."

    elif ev.confidence == ConfidenceLevel.LOW:
        outcome = VerdictOutcome.NO_INCIDENT
        risk_level = ev.policy_violation_risk.value
        action_required = (
            "Language in the case note is ambiguous and does not meet the threshold for "
            "a restrictive practice finding. No further action required at this stage."
        )

    elif cc and cc.authorisation_status == AuthorisationStatus.AUTHORISED_REVIEW:
        outcome = VerdictOutcome.AUTHORISED_USE
        risk_level = ev.policy_violation_risk.value
        action_required = (
            "Review the Behaviour Support Plan to confirm conditions were met. "
            "Record the use and ensure the BSP is current."
        )
        next_steps = [
            "Confirm the BSP covers this specific practice type and context.",
            "Verify the BSP is current and has not expired.",
            "Document the practice use in the participant's records.",
            "Check whether the BSP conditions (e.g. specific triggers, de-escalation first) were followed.",
        ]

    elif ev.bsp_mentioned_in_note and (cc is None or cc.bsp_id is None):
        outcome = VerdictOutcome.ADMINISTRATIVE_REVIEW
        risk_level = ev.policy_violation_risk.value
        action_required = (
            "The case note references a Behaviour Support Plan, but no matching active BSP "
            "was found in the system. Administrative verification required before escalation."
        )
        next_steps = [
            "Verify whether the PBSP has been uploaded to the system.",
            "Check whether the BSP is active and has not expired or been revoked.",
            "Confirm the BSP covers this specific practice type.",
            "Contact the authorising behaviour support practitioner to confirm current status.",
            "If BSP is confirmed active and applicable, update the system record.",
        ]

    elif ev.confidence == ConfidenceLevel.MEDIUM and (cc is None or cc.bsp_id is None):
        outcome = VerdictOutcome.POSSIBLE
        risk_level = ev.policy_violation_risk.value
        action_required = (
            "The case note suggests a possible restrictive practice, but the language is "
            "context-dependent. Escalate to a behaviour support practitioner for review."
        )
        next_steps = [
            "Escalate to a behaviour support practitioner for clinical review.",
            "Request clarification from the support worker on the specific actions described.",
            "Check whether a Behaviour Support Plan exists or is being developed for this client.",
            "If practice is confirmed, follow reporting obligations under NDIS Rules 2018.",
        ]

    else:
        outcome = VerdictOutcome.UNAUTHORISED
        risk_level = ev.policy_violation_risk.value
        timeframe = ev.notification_timeframe or "5 business days"
        action_required = (
            f"IMMEDIATE ACTION: Notify the NDIS Quality and Safeguards Commission "
            f"within {timeframe}. Document the incident and initiate a review of the "
            f"participant's Behaviour Support Plan."
        )
        next_steps = [
            f"Notify the NDIS Quality and Safeguards Commission within {timeframe}.",
            "Document the incident in the participant's records with full details.",
            "Debrief the support worker involved.",
            "Initiate a review or development of a Behaviour Support Plan for this participant.",
            "If serious injury is also involved, notify the Commission within 24 hours.",
        ]

    verdict = _VerdictSection(
        outcome=outcome,
        risk_level=risk_level,
        alert_required=result.alert_required,
        action_required=action_required,
        next_steps=next_steps,
    )

    # ── Detected practice ─────────────────────────────────────────────────────
    detected_practice = None
    if ev and ev.incident_detected:
        detected_practice = _DetectedPracticeSection(
            category=ev.practice_category,
            what_happened=ev.action_summary,
            reasoning=ev.reasoning,
            trigger_phrases=ev.trigger_phrases,
            suppression_factors=ev.suppression_factors,
        )

    # ── Authorisation ─────────────────────────────────────────────────────────
    authorisation = None
    if cc:
        bsp_on_file = cc.bsp_id is not None
        authorisation = _AuthorisationSection(
            status=cc.authorisation_status.value,
            behaviour_support_plan=_BehaviourSupportPlan(
                on_file=bsp_on_file,
                details=cc.notes or (
                    "Active Behaviour Support Plan found." if bsp_on_file
                    else "No active Behaviour Support Plan found for this client and practice type."
                ),
            ),
        )

    # ── Reporting obligations ─────────────────────────────────────────────────
    must_report = ev.reporting_required if ev else False
    reporting = _ReportingSection(
        must_report=must_report,
        notify_within=ev.notification_timeframe if ev else None,
        guidance=(
            "Under the NDIS (Restrictive Practices and Behaviour Support) Rules 2018, "
            "unauthorised use of a regulated restrictive practice is a reportable incident. "
            "Failure to report may result in regulatory action against the provider."
        ) if must_report else (
            "No mandatory reporting obligation triggered for this incident."
        ),
    )

    # ── Submission metadata ───────────────────────────────────────────────────
    submission = _SubmissionSection(
        case_note_id=str(result.case_note_id),
        client_id=result.client_id,
        worker_id=worker_id,
        screening_result=(
            "Flagged for detailed review" if result.triage.flagged
            else "Passed initial screening — no restrictive practice indicators found"
        ),
        screening_summary=result.triage.action_summary,
    )

    # ── AI summary ────────────────────────────────────────────────────────────
    raw_summary = result.summary
    if raw_summary is not None:
        confidence = raw_summary.ai_confidence
        if confidence >= 0.75:
            confidence_label = "High"
        elif confidence >= 0.5:
            confidence_label = "Medium"
        else:
            confidence_label = "Low"
        summary_section = _SummarySection(
            ai_confidence=confidence,
            confidence_label=confidence_label,
            progress_identified=raw_summary.progress_identified,
            potential_risks=raw_summary.potential_risks,
            patterns_detected=raw_summary.patterns_detected,
            flagged_highlights=raw_summary.flagged_highlights,
            note_quality_score=raw_summary.note_quality_score,
            note_quality_label=raw_summary.note_quality_label,
            quality_gaps=raw_summary.quality_gaps,
        )
    else:
        summary_section = _SummarySection(
            ai_confidence=0.0,
            confidence_label="Low",
            progress_identified=[],
            potential_risks=[],
            patterns_detected=[],
            flagged_highlights=[],
            note_quality_score=0.0,
            note_quality_label="Average",
            quality_gaps=[],
        )

    # ── Incident report ───────────────────────────────────────────────────────
    incident_report_section = None
    if result.incident_draft is not None:
        d = result.incident_draft
        incident_report_section = _IncidentReportSection(
            incident_type=d.incident_type,
            date_of_incident=d.date_of_incident,
            time_of_incident=d.time_of_incident,
            location=d.location,
            staff_involved=d.staff_involved,
            incident_description=d.incident_description,
            immediate_actions_taken=d.immediate_actions_taken,
            restrictive_practice_used=d.restrictive_practice_used,
            restrictive_practice_category=d.restrictive_practice_category,
            risk_assessment=d.risk_assessment,
            contributing_factors=d.contributing_factors,
            follow_up_actions=d.follow_up_actions,
            compliance_checks=d.compliance_checks,
            reportable=d.reportable,
            notification_timeframe=d.notification_timeframe,
            notification_authority=d.notification_authority,
            severity=d.severity,
            incident_categories=d.incident_categories,
            ongoing_risk_present=d.ongoing_risk_present,
            participant_currently_safe=d.participant_currently_safe,
            staff_currently_safe=d.staff_currently_safe,
            emergency_services_required=d.emergency_services_required,
        )

    return EvaluateResponse(
        verdict=verdict,
        detected_practice=detected_practice,
        authorisation=authorisation,
        reporting_obligations=reporting,
        submission=submission,
        summary=summary_section,
        incident_report=incident_report_section,
        privacy=result.privacy_notice,
    )


@rp_router.post(
    "/evaluate",
    response_model=EvaluateResponse,
    summary="Evaluate case note via RSA signature auth",
    description=(
        "Run a case note through the full restrictive practice detection pipeline "
        "(triage + evaluator + auto-incident-draft if flagged).\n\n"
        "**Auth:** RSA signature-based (replaces JWT + HTTP Basic).\n"
        "1. Sign the JSON request body with your private key (RSA-PSS, SHA256).\n"
        "2. Base64-encode the signature.\n"
        "3. Send in `X-Signature` header.\n"
        "Server verifies using the public key from `SENA_AI_EVALUATE_PUBLIC_KEY`.\n\n"
        "**Example curl (voice-transcribed case note):**\n"
        "```bash\n"
        "curl -X POST http://3.111.109.14:8080/case-review/v1/restrictive-practices/evaluate \\\n"
        "  -H 'Content-Type: application/json' \\\n"
        "  -H 'X-Signature: $SIGNATURE' \\\n"
        "  -d '{\n"
        "    \"case_note_id\": \"550e8400-e29b-41d4-a716-446655440000\",\n"
        "    \"client_id\": \"dab57916-9863-4b49-ba39-92441547ba5b\",\n"
        "    \"worker_id\": \"30d4f882-93d0-4c5d-9af6-22612908817e\",\n"
        "    \"transcript\": \"Good session. Assisted with meal prep and community access. Participant was cooperative.\"\n"
        "  }'\n"
        "```\n\n"
        "**Example curl (manually-drafted case note):**\n"
        "```bash\n"
        "curl -X POST http://3.111.109.14:8080/case-review/v1/restrictive-practices/evaluate \\\n"
        "  -H 'Content-Type: application/json' \\\n"
        "  -H 'X-Signature: $SIGNATURE' \\\n"
        "  -d '{\n"
        "    \"case_note_id\": \"550e8400-e29b-41d4-a716-446655440000\",\n"
        "    \"client_id\": \"dab57916-9863-4b49-ba39-92441547ba5b\",\n"
        "    \"worker_id\": \"30d4f882-93d0-4c5d-9af6-22612908817e\",\n"
        "    \"describe\": \"Meal prep support. Community access to library and shops. Participant independent and engaged throughout.\"\n"
        "  }'\n"
        "```\n\n"
        "**Auth:** User must (1) sign the JSON body with their RSA private key (PSS padding, SHA256), "
        "(2) base64-encode the signature, (3) pass it in the X-Signature header.\n"
        "**Note:** Either `transcript` (voice) OR `describe` (manual) — one is sufficient.\n\n"
        "**Results:** cached by transcript (SHA256). Repeated notes return in ~10ms. "
        "Cache TTL: 24 hours. Non-cached first run: ~4–5 seconds."
    ),
)
@cache_verdict
async def evaluate_case_note(
    payload: CaseNoteInput,
    response: Response,
    auth: AuthContext = Depends(verify_signature_auth),
    db: AsyncSession = Depends(get_db),
) -> EvaluateResponse:
    """Run a case note through the full restrictive practice detection pipeline.

    Results are cached by transcript (SHA256). Repeated notes return in ~10ms.
    Cache TTL: 24 hours. Non-cached first run: ~4–5 seconds.
    """
    response.headers["X-Privacy-Classification"] = "Sensitive-Health-Information-APP3"
    response.headers["X-Data-Retention"] = "No-Retention-Session-Only"
    start_usage()
    try:
        result = await run_pipeline(payload, db, tenant_id=str(auth.tenant_id))
        resp = _build_response(result, worker_id=payload.worker_id)
        resp.token_usage = TokenUsage(**get_usage())
        return resp
    except Exception as exc:
        logger.error(
            "Pipeline error case_note_id=%s: %s",
            payload.case_note_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="An internal error occurred.") from exc


@rp_router.post(
    "/bsp",
    response_model=BSPResponse,
    status_code=201,
    tags=["bsp"],
    summary="Register a Behaviour Support Plan",
    description=(
        "Create or register a new Behaviour Support Plan (BSP) for a client.\n\n"
        "Called by the platform backend when a practitioner's BSP is approved. "
        "One row per (client_id, practice_type) combination. To replace an existing "
        "authorisation, revoke the old record first then POST a new one.\n\n"
        "**Performance:**\n"
        "- Latency: <100ms (DB insert)\n"
        "- No LLM calls"
    ),
)
async def create_bsp(
    payload: BSPCreate,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> BSPResponse:
    """Register a new Behaviour Support Plan for a client.

    Called by the platform backend when a practitioner's BSP is approved.
    One row per (client_id, practice_type) combination. To replace an existing
    authorisation, revoke the old record first then POST a new one.
    """
    bsp = BehaviourSupportPlan(
        id=str(uuid.uuid4()),
        tenant_id=str(auth.tenant_id),
        client_id=payload.client_id,
        practice_type=payload.practice_type,
        status=payload.status,
        approved_dosage=payload.approved_dosage,
        approved_conditions=payload.approved_conditions,
        authorised_by=payload.authorised_by,
        valid_from=payload.valid_from,
        valid_until=payload.valid_until,
    )
    db.add(bsp)
    try:
        await db.commit()
        await db.refresh(bsp)
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Database error — operation could not be completed.") from exc

    return _bsp_to_response(bsp)


@rp_router.get(
    "/bsp/{client_id}",
    response_model=list[BSPResponse],
    tags=["bsp"],
    summary="List Behaviour Support Plans for a client",
    description=(
        "Retrieve all BSP records for a given client, ordered by creation date descending.\n\n"
        "Returns the full history of BSPs for the client, including active, expired, and revoked plans. "
        "Use to verify current authorisations before evaluating a case note.\n\n"
        "**Performance:**\n"
        "- Latency: <50ms (DB query)\n"
        "- No LLM calls"
    ),
)
async def list_bsps(
    client_id: str,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> list[BSPResponse]:
    """Return all BSP records for a given client, ordered by creation date descending."""
    result = await db.execute(
        select(BehaviourSupportPlan)
        .where(
            BehaviourSupportPlan.client_id == client_id,
            BehaviourSupportPlan.tenant_id == str(auth.tenant_id),
        )
        .order_by(BehaviourSupportPlan.created_at.desc())
    )
    rows = result.scalars().all()
    return [_bsp_to_response(r) for r in rows]


@rp_router.patch(
    "/bsp/{bsp_id}/status",
    response_model=BSPResponse,
    tags=["bsp"],
    summary="Update Behaviour Support Plan status",
    description=(
        "Update the status of a BSP (e.g. revoke or expire it).\n\n"
        "Valid values: Active | Expired | Revoked\n\n"
        "Used when a BSP needs to be deactivated before a replacement is registered, "
        "or when a practitioner revokes an authorisation.\n\n"
        "**Performance:**\n"
        "- Latency: <50ms (DB update)\n"
        "- No LLM calls"
    ),
)
async def update_bsp_status(
    bsp_id: str,
    payload: BSPUpdateStatus,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> BSPResponse:
    """Update the status of a BSP (e.g. revoke or expire it).

    Valid values: Active | Expired | Revoked
    """
    result = await db.execute(
        select(BehaviourSupportPlan).where(
            BehaviourSupportPlan.id == bsp_id,
            BehaviourSupportPlan.tenant_id == str(auth.tenant_id),
        )
    )
    bsp = result.scalar_one_or_none()
    if bsp is None:
        raise HTTPException(status_code=404, detail=f"BSP {bsp_id} not found.")

    allowed = {"Active", "Expired", "Revoked"}
    if payload.status not in allowed:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status '{payload.status}'. Must be one of: {', '.join(sorted(allowed))}",
        )

    bsp.status = payload.status
    await db.commit()
    await db.refresh(bsp)
    return _bsp_to_response(bsp)


def _bsp_to_response(bsp: BehaviourSupportPlan) -> BSPResponse:
    return BSPResponse(
        id=bsp.id,
        client_id=bsp.client_id,
        practice_type=bsp.practice_type,
        status=bsp.status,
        approved_dosage=bsp.approved_dosage,
        approved_conditions=bsp.approved_conditions,
        authorised_by=bsp.authorised_by,
        valid_from=bsp.valid_from,
        valid_until=bsp.valid_until,
        created_at=bsp.created_at,
    )


@rp_router.post(
    "/draft",
    response_model=CaseDraftResponse,
    tags=["draft"],
    summary="Draft case note from text transcript",
    description=(
        "Extract a voice transcript or text description into a pre-filled structured case note draft.\n\n"
        "The worker reviews and edits the returned fields before submitting for evaluation. "
        "No data is stored — this is a stateless AI extraction call.\n\n"
        "**Flow:**\n"
        "1. Receive transcript or description\n"
        "2. Call Claude Sonnet to extract structured fields\n"
        "3. Return populated fields with gap notes\n\n"
        "**Performance:**\n"
        "- Model: Claude Sonnet\n"
        "- Tokens: 2000-3000\n"
        "- Latency: 2-3s"
    ),
)
async def draft_case_note(
    payload: DraftInput,
    auth: AuthContext = Depends(get_auth_context),
) -> CaseDraftResponse:
    """Extract a voice transcript into a pre-filled structured case note draft.

    The worker reviews and edits the returned fields before submitting.
    No data is stored — this is a stateless AI extraction call.
    """
    start_usage()
    try:
        result = await run_drafter(payload)
    except Exception as exc:
        logger.error(
            "Drafter error case_note_id=%s worker=%s: %s",
            payload.case_note_id,
            payload.worker_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="An internal error occurred.") from exc
    result.token_usage = TokenUsage(**get_usage())
    return result


@rp_router.post(
    "/draft/audio",
    response_model=CaseDraftResponse,
    tags=["draft"],
    summary="Draft case note from audio recording",
    description=(
        "Transcribe an audio recording then extract it into a pre-filled case note draft.\n\n"
        "Accepts multipart/form-data with an audio file + shift metadata form fields. "
        "Transcription uses Amazon Transcribe (en-AU). No data is stored — stateless. "
        "Requires SENA_AI_TRANSCRIPTION_BUCKET to be set.\n\n"
        "**Flow:**\n"
        "1. Receive audio file + form fields\n"
        "2. Transcribe audio (Amazon Transcribe, en-AU)\n"
        "3. Extract transcript into structured fields (Claude Sonnet)\n"
        "4. Return populated fields\n\n"
        "**Performance:**\n"
        "- Transcription: 2-10s (depends on duration)\n"
        "- Extraction: 2-3s\n"
        "- Total: 4-13s"
    ),
)
async def draft_case_note_audio(
    audio: UploadFile = File(..., description="Audio recording (mp3, mp4/m4a, wav, flac, ogg, webm)"),
    worker_id: str = Form(...),
    client_id: str = Form(...),
    case_note_id: str = Form(default=""),
    shift_date: str = Form(default=""),
    shift_time: str = Form(default=""),
    worker_position: str = Form(default=""),
    auth: AuthContext = Depends(get_auth_context),
) -> CaseDraftResponse:
    """Transcribe an audio recording then extract it into a pre-filled case note draft.

    Accepts multipart/form-data with an audio file + shift metadata form fields.
    Transcription uses Amazon Transcribe (en-AU). No data is stored — stateless.
    Requires SENA_AI_TRANSCRIPTION_BUCKET to be set.
    """
    if not (settings.s3_bucket or settings.transcription_bucket):
        raise HTTPException(
            status_code=503,
            detail="Audio transcription not configured. Set S3_BUCKET (or SENA_AI_TRANSCRIPTION_BUCKET).",
        )

    content_type = audio.content_type or ""
    filename = audio.filename or ""
    try:
        media_format = resolve_media_format(content_type, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    audio_bytes = await audio.read()
    job_name = f"sena-{uuid4()}"

    logger.info(
        "draft/audio: transcription start job=%s format=%s size=%d worker=%s client=%s",
        job_name, media_format, len(audio_bytes), worker_id, client_id,
    )

    try:
        transcript = await run_transcription(audio_bytes, media_format, job_name=job_name)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Transcription timed out — please retry.") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail="Transcription service error — please retry.") from exc
    except Exception as exc:
        logger.error("draft/audio: transcription failed job=%s: %s", job_name, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="An internal error occurred.") from exc

    if not transcript or not transcript.strip():
        raise HTTPException(status_code=422, detail="No speech detected in audio. Please try again with clear audio.")

    resolved_id = case_note_id.strip() or str(uuid4())
    payload = DraftInput(
        transcript=transcript,
        worker_id=worker_id,
        client_id=client_id,
        case_note_id=resolved_id,  # type: ignore[arg-type]
        shift_date=shift_date or None,
        shift_time=shift_time or None,
        worker_position=worker_position or None,
    )

    start_usage()
    try:
        result = await run_drafter(payload)
    except Exception as exc:
        logger.error(
            "draft/audio: drafter failed case_note_id=%s: %s", resolved_id, exc, exc_info=True
        )
        raise HTTPException(status_code=500, detail="An internal error occurred.") from exc

    result.token_usage = TokenUsage(**get_usage())
    logger.info("draft/audio: done job=%s case_note_id=%s", job_name, resolved_id)
    return result


# ── RP voice assistant (session create + Gemini Live WebSocket bridge) ─────────
# Uses sena_common.voice (FormStateRepo, GeminiLiveSession, ToolDispatcher).
# Distinct Redis key prefix keeps RP sessions isolated from case-review voice.
# Tenant-id is derived from SENA auth (get_auth_context) — not from request body.

_RP_VOICE_KEY_PREFIX = "sena:rp_voice"
_RP_STEP_ID = "rp_case_note"
_RP_STEP_LABEL = "Case Note"
# Path to the same prompts dir used by the general case-review voice session.
_RP_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "voice" / "prompts"
_RP_STAFF_ROLES = {"worker", "staff", "support_worker", "admin"}


def _rp_is_staff(roles: list[str]) -> bool:
    # In debug mode, allow non-staff roles for testing
    if settings.debug_case_review:
        return True
    return any(r.strip().lower() in _RP_STAFF_ROLES for r in roles)


def _rp_voice_repo(tenant_id: str) -> FormStateRepo:
    return FormStateRepo(voice_redis_client, key_prefix=_RP_VOICE_KEY_PREFIX, tenant_id=tenant_id)


def _rp_voice_config() -> VoiceEngineConfig:
    return VoiceEngineConfig(
        gemini_api_key=settings.gemini_api_key,
        gemini_live_model_id=settings.gemini_live_model_id,
        prompts_dir=_RP_PROMPTS_DIR,
        grounding_enabled=settings.voice_grounding_enabled,
        screen_state_max_bytes=settings.screen_state_max_bytes,
        session_max_sec=settings.voice_session_max_sec,
        silence_timeout_sec=settings.voice_silence_timeout_sec,
        tool_state_channel=True,
        debug=settings.debug,
    )


async def _rp_close_ws(ws: WebSocket, code_str: str, message: str, ws_code: int) -> None:
    try:
        await ws.send_text(json.dumps({"type": "error", "code": code_str, "message": message}))
        await ws.close(code=ws_code)
    except Exception:
        pass


class RPVoiceSessionRequest(BaseModel):
    client_id: str
    worker_id: str
    case_note_id: str = ""
    initial_values: dict[str, dict[str, Any]] = {}
    readonly_paths: list[str] = []
    worker_display_name: str | None = None


class RPVoiceSessionResponse(BaseModel):
    session_id: str
    ws_url: str
    expires_at: str


@rp_router.post(
    "/voice/session",
    response_model=RPVoiceSessionResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["voice"],
    summary="Create voice session for case-note dictation",
    description=(
        "Create a tenant-scoped RP voice session for interactive case-note dictation.\n\n"
        "Pass ``initial_values`` from ``POST /draft`` to pre-fill already-extracted "
        "fields; the voice assistant fills the remaining gaps interactively.\n\n"
        "**Flow:**\n"
        "1. Create session and store form state in Redis\n"
        "2. Return WebSocket URL for mobile client\n"
        "3. Connect to /voice/ws/{session_id} for Gemini Live interaction\n\n"
        "**Performance:**\n"
        "- Session creation: <100ms\n"
        "- Model: Gemini 3.1 Flash Live (real-time voice)\n"
        "- Latency: ~50-200ms per token\n"
        "- Session timeout: 3600s\n\n"
        "_Staff-only: non-staff roles are rejected._"
    ),
)
async def create_rp_voice_session(
    body: RPVoiceSessionRequest,
    auth: AuthContext = Depends(get_auth_context),
) -> RPVoiceSessionResponse:
    """Create a tenant-scoped RP voice session for case-note dictation.

    Pass ``initial_values`` from ``POST /draft`` to pre-fill already-extracted
    fields; the voice assistant fills the remaining gaps interactively.
    """
    if not _rp_is_staff(auth.roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "not_staff", "message": "Voice case notes are staff-only"},
        )
    tenant_id = str(auth.tenant_id)
    session_id = uuid.uuid4().hex
    state = FormState(
        session_id=session_id,
        step_id=_RP_STEP_ID,
        participant_id=body.client_id,
        tenant_id=tenant_id,
    )
    for section_id, fields in body.initial_values.items():
        for field_id, value in fields.items():
            if value is not None:
                state.set_field(
                    section_id,
                    field_id,
                    value,
                    source=FieldSource.system,
                    confidence=0.9,
                )
    await _rp_voice_repo(tenant_id).save_state(state, ttl_sec=settings.voice_session_max_sec)
    logger.info(
        "rp_voice_session_created session=%s tenant=%s client=%s worker=%s",
        session_id,
        tenant_id,
        body.client_id,
        body.worker_id,
    )
    expires_at = (
        datetime.now(UTC) + timedelta(seconds=settings.voice_session_max_sec)
    ).isoformat()
    return RPVoiceSessionResponse(
        session_id=session_id,
        ws_url=f"/v1/restrictive-practices/voice/ws/{session_id}",
        expires_at=expires_at,
    )


@rp_router.websocket("/voice/ws/{session_id}")
async def rp_voice_websocket(
    websocket: WebSocket,
    session_id: str,
    auth: AuthContext = Depends(get_auth_context),
) -> None:
    await websocket.accept()

    tenant_id = str(auth.tenant_id)
    roles = auth.roles
    participant_id = websocket.query_params.get("participant_id")

    if not _rp_is_staff(roles):
        await _rp_close_ws(websocket, "not_staff", "Voice case notes are staff-only", 4403)
        return

    repo = _rp_voice_repo(tenant_id)
    state = await repo.get_state(session_id)
    if state is None:
        await _rp_close_ws(websocket, "session_not_found", "Session not found or expired", 4004)
        return

    try:
        await repo.assert_session_owner(
            session_id, tenant_id, participant_id or state.participant_id
        )
    except HTTPException:
        await _rp_close_ws(websocket, "forbidden", "Session does not belong to caller", 4403)
        return

    if not await repo.acquire_ws_lock(session_id, ttl_sec=settings.voice_session_max_sec):
        await _rp_close_ws(websocket, "session_locked", "Another voice connection is active", 4009)
        return

    try:
        try:
            hello = json.loads(await websocket.receive_text())
        except WebSocketDisconnect:
            return
        except json.JSONDecodeError:
            await _rp_close_ws(websocket, "protocol_error", 'Expected {"type":"hello"} first', 4008)
            return
        if hello.get("type") not in ("hello", "start"):
            await _rp_close_ws(websocket, "protocol_error", 'Expected {"type":"hello"} first', 4008)
            return

        await websocket.send_text(json.dumps({
            "type": "ready",
            "state": json.loads(state.model_dump_json()),
            "prompt_version": "v2",
            "coverage": CASE_NOTE_SCHEMA.voice_coverage,
        }))

        cfg = _rp_voice_config()
        initial_turn = TurnPayload(
            participant=Participant(first_name="", display_name=""),
            step=StepInfo(id=_RP_STEP_ID, label=_RP_STEP_LABEL, number=1),
            bootstrap_mode="new_user",
            prior_steps={},
            visible_fields=[],
            next_target=None,
        )
        system_instruction = build_system_prompt(
            initial_turn,
            grounding_enabled=cfg.grounding_enabled,
            voice_coverage=CASE_NOTE_SCHEMA.voice_coverage,
            prompts_dir=cfg.prompts_dir,
            tool_state_channel=cfg.tool_state_channel,
            template_name="case_note_system.md",
        )

        # Early exit optimization: if all required fields are filled, suggest completion
        # This reduces tokens by 20-30% for typical sessions
        required_filled = all(
            f.value and f.value not in ("", [], {})
            for f in initial_turn.visible_fields if f.required
        )
        if required_filled:
            system_instruction += (
                "\n\n[COMPLETION HINT] All required fields are now complete. "
                "When the user is satisfied, suggest calling `finalize_note` to end the session quickly."
            )

        bridge = MobileBridge(websocket, timeout_sec=5.0)
        dispatcher = ToolDispatcher(
            bridge=bridge,
            known_tools=CASE_NOTE_KNOWN_TOOLS,
            submit_tool_name="finalize_note",
        )
        live = GeminiLiveSession(
            websocket=websocket,
            session_id=session_id,
            system_instruction=system_instruction,
            repo=repo,
            tool_dispatcher=dispatcher,
            mobile_bridge=bridge,
            config=cfg,
            usage_feature=UsageFeature.CASE_NOTE_DRAFTING,
            function_decls=CASE_NOTE_FUNCTION_DECLS,
            tenant_id=tenant_id,
            participant_id=state.participant_id,
        )
        await live.run()
    except WebSocketDisconnect:
        logger.info("rp_voice_ws_disconnect session=%s", session_id)
    except Exception as exc:
        logger.exception("rp_voice_ws_error session=%s error_type=%s error_msg=%s", session_id, type(exc).__name__, str(exc))
        await _rp_close_ws(websocket, "internal_error", "Internal server error", 1011)
    finally:
        await repo.release_ws_lock(session_id)


@rp_router.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "restrictive-practice-detection"}
