from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from case_review.models.db import IncidentDraft, ReviewAuditLog, ReviewSession, RollingSummary


class ReviewRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    # ── RollingSummary ────────────────────────────────────────────────────────

    async def get_rolling_summary(
        self,
        tenant_id: uuid.UUID,
        staff_id: uuid.UUID,
        client_id: uuid.UUID,
    ) -> RollingSummary | None:
        result = await self._s.execute(
            select(RollingSummary).where(
                RollingSummary.tenant_id == tenant_id,
                RollingSummary.staff_id == staff_id,
                RollingSummary.client_id == client_id,
            )
        )
        return result.scalar_one_or_none()

    async def upsert_rolling_summary(
        self,
        tenant_id: uuid.UUID,
        staff_id: uuid.UUID,
        client_id: uuid.UUID,
        summary_text: str,
        metadata_json: dict,
        processed_note_ids: list[str],
    ) -> RollingSummary:
        """Insert or update rolling summary for a staff-client pair."""
        now = datetime.now(timezone.utc)
        stmt = (
            pg_insert(RollingSummary)
            .values(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                staff_id=staff_id,
                client_id=client_id,
                summary_text=summary_text,
                metadata=metadata_json,
                processed_note_ids=processed_note_ids,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                constraint="uq_rolling_summary_pair",
                set_={
                    "summary_text": summary_text,
                    "metadata": metadata_json,
                    "processed_note_ids": processed_note_ids,
                    "updated_at": now,
                },
            )
            .returning(RollingSummary)
        )
        result = await self._s.execute(stmt)
        await self._s.commit()
        return result.scalar_one()

    # ── ReviewSession ─────────────────────────────────────────────────────────

    async def get_review_session(self, session_id: uuid.UUID) -> ReviewSession | None:
        result = await self._s.execute(
            select(ReviewSession).where(ReviewSession.id == session_id)
        )
        return result.scalar_one_or_none()

    async def create_review_session(
        self,
        tenant_id: uuid.UUID,
        staff_id: uuid.UUID | None,
        client_id: uuid.UUID | None,
        raw_paragraph: str = "",
        drafted_case_note_id: str | None = None,
    ) -> ReviewSession:
        row = ReviewSession(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            staff_id=staff_id,
            client_id=client_id,
            raw_paragraph=raw_paragraph,
            drafted_case_note_id=drafted_case_note_id,
        )
        self._s.add(row)
        await self._s.commit()
        await self._s.refresh(row)
        return row

    async def update_review_session(
        self,
        session_id: uuid.UUID,
        **kwargs,
    ) -> ReviewSession | None:
        await self._s.execute(
            update(ReviewSession)
            .where(ReviewSession.id == session_id)
            .values(**kwargs, updated_at=datetime.now(timezone.utc))
        )
        await self._s.commit()
        return await self.get_review_session(session_id)

    # ── IncidentDraft ─────────────────────────────────────────────────────────

    async def create_incident_draft(
        self,
        tenant_id: uuid.UUID,
        review_session_id: uuid.UUID | None,
        autofill_source: dict,
        draft_fields: dict,
    ) -> IncidentDraft:
        row = IncidentDraft(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            review_session_id=review_session_id,
            autofill_source=autofill_source,
            draft_fields=draft_fields,
        )
        self._s.add(row)
        await self._s.commit()
        await self._s.refresh(row)
        return row

    async def get_incident_draft(self, draft_id: uuid.UUID) -> IncidentDraft | None:
        result = await self._s.execute(
            select(IncidentDraft).where(IncidentDraft.id == draft_id)
        )
        return result.scalar_one_or_none()

    async def confirm_incident_draft(self, draft_id: uuid.UUID) -> IncidentDraft | None:
        await self._s.execute(
            update(IncidentDraft)
            .where(IncidentDraft.id == draft_id)
            .values(staff_confirmed=True, status="confirmed")
        )
        await self._s.commit()
        return await self.get_incident_draft(draft_id)

    # ── ReviewAuditLog ────────────────────────────────────────────────────────

    async def append_audit(
        self,
        tenant_id: uuid.UUID,
        review_session_id: uuid.UUID,
        action: str,
        payload: dict,
        actor_user_id: uuid.UUID | None = None,
    ) -> ReviewAuditLog:
        row = ReviewAuditLog(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            review_session_id=review_session_id,
            actor_user_id=actor_user_id,
            action=action,
            payload=payload,
        )
        self._s.add(row)
        await self._s.commit()
        await self._s.refresh(row)
        return row

    async def list_audit(self, review_session_id: uuid.UUID) -> list[ReviewAuditLog]:
        result = await self._s.execute(
            select(ReviewAuditLog)
            .where(ReviewAuditLog.review_session_id == review_session_id)
            .order_by(ReviewAuditLog.created_at)
        )
        return list(result.scalars().all())
