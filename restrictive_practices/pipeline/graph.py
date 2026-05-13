"""Step 7 — LangGraph pipeline wiring.

Graph topology:
  START → triage → [flagged=False] → END
                 → [flagged=True]  → rag → evaluator → cross_check → END

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
    PipelineResult,
    PolicyChunk,
    TriageResult,
)
from pipeline.cross_check import run_cross_check
from pipeline.evaluator import run_evaluator
from pipeline.rag import retrieve_policy_chunks
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


# ── Routing ───────────────────────────────────────────────────────────────────

def _route_after_triage(state: PipelineState) -> str:
    """Skip the expensive path entirely for clean notes."""
    return "rag_step" if state["triage"].flagged else END


# ── Graph assembly ────────────────────────────────────────────────────────────

def _build_graph() -> StateGraph:
    builder = StateGraph(PipelineState)

    builder.add_node("triage_step", triage_node)
    builder.add_node("rag_step", rag_node)
    builder.add_node("evaluator_step", evaluator_node)
    builder.add_node("cross_check_step", cross_check_node)

    builder.add_edge(START, "triage_step")
    builder.add_conditional_edges(
        "triage_step",
        _route_after_triage,
        {"rag_step": "rag_step", END: END},
    )
    builder.add_edge("rag_step", "evaluator_step")
    builder.add_edge("evaluator_step", "cross_check_step")
    builder.add_edge("cross_check_step", END)

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
    })

    elapsed_ms = int(time.monotonic() * 1000 - start_ms)

    triage: TriageResult = final["triage"]
    evaluator: EvaluatorOutput | None = final.get("evaluator")
    cross_check: CrossCheckResult | None = final.get("cross_check")

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
