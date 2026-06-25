"""Unified Incident Analysis — one call returns all three mobile screens.

Screens (from the Flutter "AI Summary" flow):
  1. AI Summary     → the rolling progress/risk/pattern/highlight summary
  2. Risk Summary   → risk category, why flagged, current level, suggested attention
  3. Incident Draft → the pre-filled incident report

Implementation reuses the EXACT same machinery as POST /evaluate:
``run_pipeline()`` + ``_build_response()``. We then regroup the resulting
``EvaluateResponse`` into the 3-view shape — no detection logic is duplicated, so
field availability and edge cases stay identical to the proven endpoint.

Field availability (mirrors the pipeline, intentionally):
  * verdict + ai_summary — always present
  * risk_summary         — null unless triage flagged the note (no evaluator → no risk)
  * incident_draft        — null unless an incident report was generated
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_auth_context, get_db
from api.rp_routes import _build_response  # reuse the tested PipelineResult → response mapping
from case_review.models.schemas import (
    AuthContext,
    RiskSummaryView,
    TokenUsage,
    UnifiedIncidentRequest,
    UnifiedIncidentResponse,
)
from case_review.services.pipeline.graph import run_pipeline
from case_review.services.usage import get_usage, start_usage

logger = logging.getLogger(__name__)
unified_router = APIRouter(prefix="/v1/restrictive-practices/incidents", tags=["incidents"])


def _build_risk_summary(resp) -> RiskSummaryView | None:
    """Derive the Risk Summary screen from an already-built EvaluateResponse.

    Returns None when no restrictive-practice was detected (clean note) — there
    is nothing to summarise as a risk. ``detected_practice`` is populated by
    _build_response() only when the evaluator flagged an incident.
    """
    dp = resp.detected_practice
    if dp is None:
        return None

    why_flagged: list[str] = list(dp.trigger_phrases)
    if dp.reasoning:
        why_flagged.append(dp.reasoning)

    # Prefer the verdict's ordered next-steps; fall back to the headline action.
    suggested = list(resp.verdict.next_steps) or [resp.verdict.action_required]

    return RiskSummaryView(
        risk_category=dp.category,
        why_flagged=why_flagged,
        current_risk_level=resp.verdict.risk_level,
        suggested_attention=suggested,
    )


@unified_router.post(
    "/analyze",
    response_model=UnifiedIncidentResponse,
    summary="Unified incident analysis — case note form + voice transcript → all three screens",
    description=(
        "Feed the **SENA shift case-note form** (and optionally the **raw voice transcript**). "
        "The structured fields and the transcript are merged and run through the full "
        "restrictive-practice detection pipeline — RAG over the NDIS policy DB (pgvector) + "
        "Bedrock Claude — to generate the data for all three mobile screens:\n\n"
        "1. **AI Summary** — `ai_summary`: progress, potential risks, patterns, flagged highlights, "
        "quality score.\n"
        "2. **Risk Summary** — `risk_summary`: risk category, why flagged, current risk level, "
        "suggested attention. *Null for clean notes (nothing flagged).*\n"
        "3. **Incident Draft** — `incident_draft`: pre-filled incident report. *Null unless an "
        "incident report was generated.*\n\n"
        "Body: `{ case_note_form: {...}, voice_transcript: \"...\" }`. "
        "`worker_id` is taken from the authenticated caller (JWT)."
    ),
)
async def analyze_incident_unified(
    req: UnifiedIncidentRequest,
    auth: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> UnifiedIncidentResponse:
    """Single endpoint feeding the AI Summary / Risk Summary / Incident Draft screens."""
    # Map the form (+ voice transcript) onto the pipeline's CaseNoteInput.
    # worker_id comes from the authenticated staff member, not the form.
    payload = req.to_case_note_input(worker_id=str(auth.user_id))

    start_usage()
    try:
        result = await run_pipeline(payload, db, tenant_id=str(auth.tenant_id))
    except Exception as exc:
        logger.error(
            "unified analyze pipeline error case_note_id=%s: %s",
            payload.case_note_id,
            exc,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="An internal error occurred.") from exc

    # Reuse the same mapping the /evaluate endpoint uses — verdict, summary, incident report.
    resp = _build_response(result, worker_id=payload.worker_id)

    incident_detected = bool(result.evaluator and result.evaluator.incident_detected)

    return UnifiedIncidentResponse(
        case_note_id=result.case_note_id,
        client_id=result.client_id,
        shift_id=req.case_note_form.shiftId,
        incident_detected=incident_detected,
        verdict=resp.verdict,
        ai_summary=resp.summary,
        risk_summary=_build_risk_summary(resp),
        incident_draft=resp.incident_report,
        token_usage=TokenUsage(**get_usage()),
    )
