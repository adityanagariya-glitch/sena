from __future__ import annotations

"""
Context service — pre-meeting brief for a staff-client pair.

Orchestrates:
  1. Fetch last N case notes via CaseNoteClient
  2. Diff against processed_note_ids (replay guard — never double-process)
  3. If no new notes → return existing summary unchanged (idempotent)
  4. Summarise: LLM compresses (past_summary + new_notes) → SummaryResult
  5. Upsert RollingSummary row with merged processed_note_ids
"""

import uuid

import structlog

from case_review.clients.case_note_client import CaseNoteClient
from case_review.core.settings import settings
from case_review.models.schemas import ContextResponse
from case_review.repositories.review_repo import ReviewRepo
from case_review.services.llm.summarizer import summarise

log = structlog.get_logger(__name__)


async def get_context(
    *,
    repo: ReviewRepo,
    client: CaseNoteClient,
    tenant_id: uuid.UUID,
    staff_id: uuid.UUID,
    client_id: uuid.UUID,
    limit: int = 10,
) -> ContextResponse:
    """
    Fetch + summarise case notes for a staff-client pair.
    Idempotent: re-calling with same notes returns cached summary without LLM call.
    """
    # 1. Fetch notes from other engineer's service (or stub)
    raw_notes = await client.get_notes(str(staff_id), str(client_id), limit=limit)

    # 2. Load existing rolling summary
    existing = await repo.get_rolling_summary(tenant_id, staff_id, client_id)
    processed_ids: list[str] = list(existing.processed_note_ids) if existing else []
    past_summary: str = existing.summary_text if existing else ""

    # 3. Diff — only notes not yet incorporated
    new_notes = [n for n in raw_notes if n.note_id not in processed_ids]

    log.info(
        "context_service.diff",
        total_fetched=len(raw_notes),
        new_notes=len(new_notes),
        already_processed=len(processed_ids),
    )

    # 4. Replay guard — nothing new, return cached result
    if not new_notes and existing is not None:
        log.info("context_service.cache_hit")
        return ContextResponse(
            summary_text=existing.summary_text,
            metadata=existing.metadata_json,
            notes_included=len(existing.processed_note_ids),
            rolling_summary_id=existing.id,
        )

    # 5. Summarise (LLM call)
    result = await summarise(
        past_summary=past_summary,
        new_notes=new_notes,
        api_key=settings.gemini_api_key,
        model_id=settings.gemini_model_id,
    )

    # 6. Merge processed IDs (existing + new)
    merged_ids = list(dict.fromkeys(processed_ids + [n.note_id for n in new_notes]))

    # 7. Upsert rolling summary
    updated = await repo.upsert_rolling_summary(
        tenant_id=tenant_id,
        staff_id=staff_id,
        client_id=client_id,
        summary_text=result.summary_text,
        metadata_json=result.metadata,
        processed_note_ids=merged_ids,
    )

    log.info("context_service.updated", rolling_summary_id=str(updated.id))

    return ContextResponse(
        summary_text=updated.summary_text,
        metadata=updated.metadata_json,
        notes_included=len(merged_ids),
        rolling_summary_id=updated.id,
    )
