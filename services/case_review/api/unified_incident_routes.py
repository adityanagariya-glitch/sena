"""
Unified Incidents Analysis API — Active endpoint.

This module contains the current active API:
  POST /v1/case-review/incidents/analyze

All other endpoints (context, classify, review, etc.) are archived in
api/archived_routes.py and not registered in the active Swagger schema.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from api.rsa_auth import verify_rsa_auth
from case_review.core.settings import settings
from case_review.services.caching import cache_verdict
from case_review.models.schemas import (
    AuthContext,
    CaseNoteForm,
    PipelineResult,
    RiskSummaryView,
    TokenUsage,
    UnifiedIncidentRequest,
    UnifiedIncidentResponse,
    _SummarySection,
)
from case_review.services.usage import get_usage, log_api_tokens, start_usage
from case_review.services.pipeline.graph import run_pipeline

logger = logging.getLogger(__name__)
unified_router = APIRouter(prefix="/v1/restrictive-practices", tags=["incidents"])


@unified_router.post(
    "/incidents/analyze",
    response_model=UnifiedIncidentResponse,
    summary="Unified incident analysis — case note form + voice transcript → all three screens",
    description=(
        "Single endpoint: feeds the SENA shift case-note form (+ optional raw voice transcript) "
        "through the full restrictive-practice detection pipeline.\n\n"
        "**Input:**\n"
        "- `case_note_form` (required): Structured shift form from the mobile app\n"
        "- `voice_transcript` (optional): Raw voice dictation (merged with form for analysis)\n\n"
        "**Pipeline:**\n"
        "1. Map form + transcript → CaseNoteInput\n"
        "2. Run triage (Haiku gate)\n"
        "3. If flagged → run evaluator (Sonnet) + incident drafter (Sonnet)\n"
        "4. Build response → all three mobile screens\n\n"
        "**Response (all three screens in one):**\n"
        "1. **AI Summary** — progress, potential_risks, patterns, flagged_highlights\n"
        "2. **Risk Summary** — risk_category, why_flagged, current_risk_level (null if no incident)\n"
        "3. **Incident Draft** — pre-filled incident report (null if no incident detected)\n\n"
        "**Performance:**\n"
        "- Latency: 4-5s (full pipeline) or ~10ms (cached by case note hash)\n"
        "- Cache TTL: 24 hours\n"
        "- Models: Haiku (triage) + Sonnet (evaluator + drafter)"
    ),
)
@cache_verdict
async def analyze_incidents(
    payload: UnifiedIncidentRequest,
    response: Response,
    auth: AuthContext = Depends(verify_rsa_auth),
    db: AsyncSession = Depends(get_db),
) -> UnifiedIncidentResponse:
    """
    Unified incident analysis: case-note form + voice transcript → all three screens.

    Maps the SENA shift form onto the restrictive-practice pipeline and returns
    AI Summary + Risk Summary + Incident Draft in one response.
    """
    response.headers["X-Privacy-Classification"] = "Sensitive-Health-Information-APP3"
    response.headers["X-Data-Retention"] = "No-Retention-Session-Only"
    start_usage()

    client_id = payload.case_note_form.clientId
    shift_id = payload.case_note_form.shiftId

    logger.info("incidents-analyze START client=%s shift=%s", client_id, shift_id)
    try:
        # Map form (+ voice transcript) → CaseNoteInput
        case_note_input = payload.to_case_note_input(worker_id=shift_id)

        # Run full pipeline
        logger.info("incidents-analyze running pipeline client=%s shift=%s", client_id, shift_id)
        result = await run_pipeline(case_note_input, db, tenant_id=str(auth.tenant_id))

        # Build unified response (all three screens)
        resp = _build_unified_response(
            result,
            case_note_form=payload.case_note_form,
            worker_id=shift_id,
        )
        resp.token_usage = TokenUsage(**get_usage())

        usage = get_usage()
        logger.info(
            "incidents-analyze DONE client=%s shift=%s input=%d output=%d total=%d",
            client_id, shift_id,
            usage["input_tokens"], usage["output_tokens"], usage["total_tokens"],
        )
        log_api_tokens("/v1/restrictive-practices/incidents/analyze", "POST", client_id, 200)
        return resp

    except Exception as exc:
        logger.error(
            "incidents-analyze error client=%s shift=%s: %s",
            client_id,
            shift_id,
            exc,
            exc_info=True,
        )
        log_api_tokens("/v1/restrictive-practices/incidents/analyze", "POST", client_id, 500)
        raise HTTPException(status_code=500, detail="An internal error occurred.") from exc


def _build_unified_response(
    result: PipelineResult,
    case_note_form: CaseNoteForm,
    worker_id: str,
) -> UnifiedIncidentResponse:
    """Build unified response feeding all three mobile screens.

    Reuses existing pipeline logic, then adds risk_summary and incident_draft
    derived from the pipeline result.
    """
    # AI Summary screen
    ai_summary = _SummarySection(
        quality_score=result.cross_check.final_score if result.cross_check else 0.9,
        progress=result.improved_factors or [],
        risks=result.risks or [],
        anomalies=result.anomalies or [],
        quality_gaps=result.quality_gaps or [],
    )

    # Risk Summary screen (only if evaluator flagged something)
    risk_summary = None
    if result.evaluator:
        risk_summary = RiskSummaryView(
            risk_category=result.evaluator.practice_category or "No Restrictive Practice Detected",
            why_flagged=result.evaluator.trigger_phrases or [],
            current_risk_level=result.evaluator.policy_violation_risk.value if result.evaluator.policy_violation_risk else "Low",
            suggested_attention=(
                [result.evaluator.action_summary] if result.evaluator.action_summary else []
            ),
        )

    # Incident Draft screen (only if incident detected and drafted)
    incident_draft = None
    if result.evaluator and result.evaluator.incident_detected and result.incident_report:
        incident_draft = result.incident_report

    return UnifiedIncidentResponse(
        case_note_id=case_note_form.shiftId,
        client_id=case_note_form.clientId,
        shift_id=case_note_form.shiftId,
        incident_detected=bool(result.evaluator and result.evaluator.incident_detected),
        verdict=result.evaluator,
        ai_summary=ai_summary,
        risk_summary=risk_summary,
        incident_draft=incident_draft,
    )
