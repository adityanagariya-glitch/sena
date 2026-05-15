"""Step 7 — LangGraph pipeline wiring.

Graph topology:
  START → triage_step
  triage_step → [flagged=False] → summary_step → END
  triage_step → [flagged=True]  → rag_step → evaluator_step → cross_check_step → summary_step
  summary_step → [worker/pipeline flagged] → incident_draft_step → END
  summary_step → [not triggered]           → END

Each node receives the full PipelineState and returns only the fields it updates.
The DB session is threaded through state (in-memory graph, no serialisation needed).
An audit CaseNoteRun row is persisted at completion regardless of outcome.
"""

import time
import logging
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import CaseNoteRun
from models.schemas import (
    AuthorisationStatus,
    CaseNoteInput,
    ConfidenceLevel,
    CrossCheckResult,
    EvaluatorOutput,
    IncidentDraftOutput,
    PipelineResult,
    PolicyChunk,
    SummaryOutput,
    TriageResult,
)
from pipeline.cross_check import run_cross_check
from pipeline.evaluator import run_evaluator
from pipeline.incident_draft import run_incident_draft
from pipeline.rag import retrieve_policy_chunks
from pipeline.summary import run_summary
from pipeline.triage import run_triage
from pipeline.webhook import fire_webhook

logger = logging.getLogger(__name__)


# ── State ─────────────────────────────────────────────────────────────────────

class PipelineState(TypedDict):
    note: CaseNoteInput
    db: AsyncSession
    start_ms: float
    triage: TriageResult | None
    chunks: list[PolicyChunk]
    evaluator: EvaluatorOutput | None
    cross_check: CrossCheckResult | None
    summary: SummaryOutput | None
    incident_draft: IncidentDraftOutput | None


# ── Nodes ─────────────────────────────────────────────────────────────────────

async def triage_node(state: PipelineState) -> dict:
    result = await run_triage(state["note"])
    return {"triage": result}


async def rag_node(state: PipelineState) -> dict:
    chunks = await retrieve_policy_chunks(state["note"], state["triage"], state["db"])
    return {"chunks": chunks}


async def evaluator_node(state: PipelineState) -> dict:
    result = await run_evaluator(state["note"], state["triage"], state["chunks"])
    return {"evaluator": result}


async def cross_check_node(state: PipelineState) -> dict:
    result = await run_cross_check(state["note"], state["evaluator"], state["db"])
    return {"cross_check": result}


async def summary_node(state: PipelineState) -> dict:
    result = await run_summary(state["note"])
    return {"summary": result}


async def incident_draft_node(state: PipelineState) -> dict:
    result = await run_incident_draft(state["note"], state.get("evaluator"))
    return {"incident_draft": result}


# ── Routing ───────────────────────────────────────────────────────────────────

def _route_after_triage(state: PipelineState) -> str:
    """Skip the expensive path entirely for clean notes; both paths converge at summary_step."""
    return "rag_step" if state["triage"].flagged else "summary_step"


def _route_after_summary(state: PipelineState) -> str:
    """Trigger incident draft when worker flagged an incident OR pipeline found UNAUTHORISED."""
    note = state["note"]
    evaluator = state.get("evaluator")
    cross_check = state.get("cross_check")

    worker_flagged = note.incident_occurred

    pipeline_flagged = (
        evaluator is not None
        and evaluator.incident_detected
        and evaluator.confidence != ConfidenceLevel.LOW
        and cross_check is not None
        and cross_check.authorisation_status == AuthorisationStatus.UNAUTHORISED
    )

    return "incident_draft_step" if (worker_flagged or pipeline_flagged) else END


# ── Graph assembly ────────────────────────────────────────────────────────────

def _build_graph() -> StateGraph:
    builder = StateGraph(PipelineState)

    builder.add_node("triage_step", triage_node)
    builder.add_node("rag_step", rag_node)
    builder.add_node("evaluator_step", evaluator_node)
    builder.add_node("cross_check_step", cross_check_node)
    builder.add_node("summary_step", summary_node)
    builder.add_node("incident_draft_step", incident_draft_node)

    builder.add_edge(START, "triage_step")
    builder.add_conditional_edges(
        "triage_step",
        _route_after_triage,
        {"rag_step": "rag_step", "summary_step": "summary_step"},
    )
    builder.add_edge("rag_step", "evaluator_step")
    builder.add_edge("evaluator_step", "cross_check_step")
    builder.add_edge("cross_check_step", "summary_step")
    builder.add_conditional_edges(
        "summary_step",
        _route_after_summary,
        {"incident_draft_step": "incident_draft_step", END: END},
    )
    builder.add_edge("incident_draft_step", END)

    return builder.compile()


_graph = _build_graph()


# ── Public entry point ────────────────────────────────────────────────────────

async def run_pipeline(note: CaseNoteInput, db: AsyncSession) -> PipelineResult:
    """Execute the full detection pipeline and persist an audit record."""
    start_ms = time.monotonic() * 1000

    logger.info("pipeline start case_note_id=%s client=%s", note.case_note_id, note.client_id)

    final: PipelineState = await _graph.ainvoke({
        "note": note,
        "db": db,
        "start_ms": start_ms,
        "triage": None,
        "chunks": [],
        "evaluator": None,
        "cross_check": None,
        "summary": None,
        "incident_draft": None,
    })

    elapsed_ms = int(time.monotonic() * 1000 - start_ms)

    triage: TriageResult = final["triage"]
    evaluator: EvaluatorOutput | None = final.get("evaluator")
    cross_check: CrossCheckResult | None = final.get("cross_check")
    summary: SummaryOutput | None = final.get("summary")
    incident_draft: IncidentDraftOutput | None = final.get("incident_draft")

    alert_required = (
        cross_check is not None
        and cross_check.authorisation_status == AuthorisationStatus.UNAUTHORISED
        and evaluator is not None
        and evaluator.incident_detected
        and evaluator.confidence != ConfidenceLevel.LOW
    )

    # Persist audit record — every run is logged regardless of outcome
    run = CaseNoteRun(
        case_note_id=str(note.case_note_id),
        client_id=note.client_id,
        worker_id=note.worker_id,
        triage_flagged=triage.flagged,
        evaluator_output=evaluator.model_dump() if evaluator else None,
        authorisation_status=cross_check.authorisation_status.value if cross_check else None,
        alert_required=alert_required,
        processing_time_ms=elapsed_ms,
    )
    db.add(run)
    await db.commit()

    pipeline_result = PipelineResult(
        case_note_id=note.case_note_id,
        client_id=note.client_id,
        triage=triage,
        evaluator=evaluator,
        cross_check=cross_check,
        alert_required=alert_required,
        summary=summary,
        incident_draft=incident_draft,
    )

    if alert_required:
        await fire_webhook(pipeline_result)

    logger.info(
        "pipeline done case_note_id=%s flagged=%s alert=%s elapsed_ms=%d",
        note.case_note_id,
        triage.flagged,
        alert_required,
        elapsed_ms,
    )

    return pipeline_result
