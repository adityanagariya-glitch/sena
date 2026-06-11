"""Step 7 — LangGraph pipeline wiring.

Graph topology (core chain only — summary/incident_draft orchestrated outside):
  START → triage_step
  triage_step → [flagged=False] → END
  triage_step → [flagged=True]  → rag_step → evaluator_step → cross_check_step → END

run_pipeline() parallelism:
  - run_summary() fires as asyncio.create_task() at request start (Opt A)
  - run_incident_draft() joins via asyncio.gather() with summary when incident needed (Opt B)
  - fire_webhook() detaches via asyncio.create_task() to not block response (Opt C)
"""

import asyncio
import logging
import time
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

# GC anchor — prevents detached asyncio tasks from being garbage collected mid-flight
_bg_tasks: set[asyncio.Task] = set()


# ── State ─────────────────────────────────────────────────────────────────────

class PipelineState(TypedDict):
    note: CaseNoteInput
    db: AsyncSession
    start_ms: float
    triage: TriageResult | None
    chunks: list[PolicyChunk]
    evaluator: EvaluatorOutput | None
    cross_check: CrossCheckResult | None
    # per-step instrumentation (ms)
    triage_ms: int | None
    rag_ms: int | None
    evaluator_ms: int | None
    cross_check_ms: int | None


# ── Nodes ─────────────────────────────────────────────────────────────────────

async def triage_node(state: PipelineState) -> dict:
    t0 = time.monotonic()
    result = await run_triage(state["note"])
    return {"triage": result, "triage_ms": int((time.monotonic() - t0) * 1000)}


async def rag_node(state: PipelineState) -> dict:
    t0 = time.monotonic()
    chunks = await retrieve_policy_chunks(state["note"], state["triage"], state["db"])
    return {"chunks": chunks, "rag_ms": int((time.monotonic() - t0) * 1000)}


async def evaluator_node(state: PipelineState) -> dict:
    t0 = time.monotonic()
    result = await run_evaluator(state["note"], state["triage"], state["chunks"])
    return {"evaluator": result, "evaluator_ms": int((time.monotonic() - t0) * 1000)}


async def cross_check_node(state: PipelineState) -> dict:
    t0 = time.monotonic()
    result = await run_cross_check(state["note"], state["evaluator"], state["db"])
    return {"cross_check": result, "cross_check_ms": int((time.monotonic() - t0) * 1000)}


# ── Routing ───────────────────────────────────────────────────────────────────

def _route_after_triage(state: PipelineState) -> str:
    """Skip the expensive RAG+eval path entirely for clean notes."""
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


# ── Parallel helpers ──────────────────────────────────────────────────────────

async def _run_summary_timed(note: CaseNoteInput) -> tuple[SummaryOutput, int]:
    t0 = time.monotonic()
    result = await run_summary(note)
    return result, int((time.monotonic() - t0) * 1000)


async def _run_incident_draft_timed(
    note: CaseNoteInput, evaluator: EvaluatorOutput | None
) -> tuple[IncidentDraftOutput, int]:
    t0 = time.monotonic()
    result = await run_incident_draft(note, evaluator)
    return result, int((time.monotonic() - t0) * 1000)


# ── Public entry point ────────────────────────────────────────────────────────

async def run_pipeline(note: CaseNoteInput, db: AsyncSession) -> PipelineResult:
    """Execute the full detection pipeline and persist an audit record.

    Parallelism:
    - run_summary fires immediately at request start (depends only on note)
    - run_incident_draft joins via asyncio.gather with the summary task
    - fire_webhook detaches so the caller gets the response without waiting
    """
    start_ms = time.monotonic() * 1000

    logger.info("pipeline start case_note_id=%s client=%s", note.case_note_id, note.client_id)

    # Opt A: summary depends only on note — start parallel with graph traversal
    summary_task: asyncio.Task[tuple[SummaryOutput, int]] = asyncio.create_task(
        _run_summary_timed(note)
    )

    final: PipelineState = await _graph.ainvoke({
        "note": note,
        "db": db,
        "start_ms": start_ms,
        "triage": None,
        "chunks": [],
        "evaluator": None,
        "cross_check": None,
        "triage_ms": None,
        "rag_ms": None,
        "evaluator_ms": None,
        "cross_check_ms": None,
    })

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

    needs_incident = note.incident_occurred or (
        evaluator is not None
        and evaluator.incident_detected
        and evaluator.confidence != ConfidenceLevel.LOW
        and cross_check is not None
        and cross_check.authorisation_status == AuthorisationStatus.UNAUTHORISED
    )

    # Opt B: join summary + incident_draft in parallel when incident needed
    incident_draft: IncidentDraftOutput | None = None
    incident_ms: int | None = None

    if needs_incident:
        (summary, summary_ms), (incident_draft, incident_ms) = await asyncio.gather(
            summary_task,
            _run_incident_draft_timed(note, evaluator),
        )
    else:
        summary, summary_ms = await summary_task

    elapsed_ms = int(time.monotonic() * 1000 - start_ms)

    # Persist audit record — DB session is open until get_db() context exits after return
    run = CaseNoteRun(
        case_note_id=str(note.case_note_id),
        client_id=note.client_id,
        worker_id=note.worker_id,
        triage_flagged=triage.flagged,
        evaluator_output=evaluator.model_dump() if evaluator else None,
        authorisation_status=cross_check.authorisation_status.value if cross_check else None,
        alert_required=alert_required,
        processing_time_ms=elapsed_ms,
        triage_ms=final.get("triage_ms"),
        rag_ms=final.get("rag_ms"),
        evaluator_ms=final.get("evaluator_ms"),
        cross_check_ms=final.get("cross_check_ms"),
        summary_ms=summary_ms,
        incident_draft_ms=incident_ms,
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

    # Opt C: detach webhook — errors swallowed inside fire_webhook; don't block response
    if alert_required:
        webhook_task = asyncio.create_task(fire_webhook(pipeline_result))
        _bg_tasks.add(webhook_task)
        webhook_task.add_done_callback(_bg_tasks.discard)

    logger.info(
        "pipeline done case_note_id=%s flagged=%s alert=%s elapsed_ms=%d "
        "triage_ms=%s rag_ms=%s eval_ms=%s cc_ms=%s summary_ms=%d incident_ms=%s",
        note.case_note_id,
        triage.flagged,
        alert_required,
        elapsed_ms,
        final.get("triage_ms"),
        final.get("rag_ms"),
        final.get("evaluator_ms"),
        final.get("cross_check_ms"),
        summary_ms,
        incident_ms,
    )

    return pipeline_result
