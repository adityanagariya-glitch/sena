from __future__ import annotations

from datetime import datetime
from uuid import UUID
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from voice.models.db import (
    ApprovalQueueItem,
    CaseNoteDraft,
    DictationTurn,
    PersonalDetailsDraft,
    VoiceSession,
    OutboxEvent,
)


class VoiceRepository:
    async def create_voice_session(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        participant_id: UUID,
        staff_id: UUID,
        shift_id: UUID,
        objective: str,
    ) -> VoiceSession:
        row = VoiceSession(
            tenant_id=tenant_id,
            participant_id=participant_id,
            staff_id=staff_id,
            shift_id=shift_id,
            objective=objective,
            status="ACTIVE",
            section_coverage={},
            missing_topics=[],
            draft_preview="",
        )
        db.add(row)
        await db.flush()
        return row

    async def get_session_by_id(self, db: AsyncSession, session_id: UUID) -> VoiceSession | None:
        result = await db.execute(select(VoiceSession).where(VoiceSession.id == session_id))
        return result.scalar_one_or_none()

    async def update_session_progress(
        self,
        db: AsyncSession,
        session_id: UUID,
        draft_preview: str,
        section_coverage: dict,
        missing_topics: list,
    ) -> None:
        await db.execute(
            update(VoiceSession)
            .where(VoiceSession.id == session_id)
            .values(
                draft_preview=draft_preview,
                section_coverage=section_coverage,
                missing_topics=missing_topics,
                turn_count=VoiceSession.turn_count + 1,
            )
        )

    async def update_session_fields(
        self,
        db: AsyncSession,
        session_id: UUID,
        fields_json: dict,
        completeness_score: float,
        missing_fields: list,
    ) -> None:
        """Update session with field extraction results (background task)."""
        await db.execute(
            update(VoiceSession)
            .where(VoiceSession.id == session_id)
            .values(
                draft_preview=str(fields_json),
                section_coverage={"completeness": completeness_score},
                missing_topics=missing_fields,
                turn_count=VoiceSession.turn_count + 1,
            )
        )

    async def mark_session_completed(
        self, db: AsyncSession, session_id: UUID, ended_at: datetime
    ) -> None:
        await db.execute(
            update(VoiceSession)
            .where(VoiceSession.id == session_id)
            .values(status="COMPLETED", ended_at=ended_at)
        )

    async def add_turn(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        session_id: UUID,
        sequence_number: int,
        transcript: str,
        transcript_confidence: float,
        agent_reply: str,
        section_coverage: dict,
        missing_topics: list,
    ) -> None:
        row = DictationTurn(
            tenant_id=tenant_id,
            session_id=session_id,
            sequence_number=sequence_number,
            transcript=transcript,
            transcript_confidence=transcript_confidence,
            agent_reply=agent_reply,
            section_coverage=section_coverage,
            missing_topics=missing_topics,
        )
        db.add(row)

    async def create_case_note_draft(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        session_id: UUID,
        participant_id: UUID,
        staff_id: UUID,
        shift_id: UUID,
        draft_json: dict,
        completeness_score: float,
        missing_topics: list[str],
        safety_category: str,
    ) -> CaseNoteDraft:
        row = CaseNoteDraft(
            tenant_id=tenant_id,
            session_id=session_id,
            participant_id=participant_id,
            staff_id=staff_id,
            shift_id=shift_id,
            draft_json=draft_json,
            completeness_score=completeness_score,
            missing_topics=missing_topics,
            safety_category=safety_category,
            status="PENDING_APPROVAL",
        )
        db.add(row)
        await db.flush()
        return row

    async def create_approval_item(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        item_id: UUID,
        participant_id: UUID,
        note_version: int,
        tier: int,
    ) -> ApprovalQueueItem:
        row = ApprovalQueueItem(
            tenant_id=tenant_id,
            item_type="CASE_NOTE_DRAFT",
            item_id=item_id,
            tier=tier,
            status="PENDING",
            participant_id=participant_id,
            note_version=note_version,
        )
        db.add(row)
        await db.flush()
        return row

    async def insert_outbox(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        event_type: str,
        payload: dict,
        idempotency_key: str,
    ) -> OutboxEvent:
        row = OutboxEvent(
            tenant_id=tenant_id,
            event_type=event_type,
            payload=payload,
            idempotency_key=idempotency_key,
            status="PENDING",
        )
        db.add(row)
        await db.flush()
        return row

    async def mark_outbox_published(
        self, db: AsyncSession, outbox_id: UUID, published_at: datetime
    ) -> None:
        await db.execute(
            update(OutboxEvent)
            .where(OutboxEvent.id == outbox_id)
            .values(status="PUBLISHED", published_at=published_at)
        )

    async def get_approval_item(
        self, db: AsyncSession, approval_item_id: UUID
    ) -> ApprovalQueueItem | None:
        result = await db.execute(
            select(ApprovalQueueItem).where(ApprovalQueueItem.id == approval_item_id)
        )
        return result.scalar_one_or_none()

    async def get_case_note_draft(self, db: AsyncSession, draft_id: UUID) -> CaseNoteDraft | None:
        result = await db.execute(select(CaseNoteDraft).where(CaseNoteDraft.id == draft_id))
        return result.scalar_one_or_none()

    async def mark_approval_rejected(
        self,
        db: AsyncSession,
        approval_item_id: UUID,
        reviewer_id: UUID,
        notes: str,
        reviewed_at: datetime,
    ) -> None:
        await db.execute(
            update(ApprovalQueueItem)
            .where(ApprovalQueueItem.id == approval_item_id)
            .values(
                status="REJECTED",
                decision="REJECTED",
                reviewed_by=reviewer_id,
                decision_notes=notes,
                reviewed_at=reviewed_at,
            )
        )

    async def mark_approval_delivered(
        self,
        db: AsyncSession,
        approval_item_id: UUID,
        reviewer_id: UUID,
        notes: str,
        delivered_at: datetime,
    ) -> None:
        await db.execute(
            update(ApprovalQueueItem)
            .where(ApprovalQueueItem.id == approval_item_id)
            .values(
                status="DELIVERED",
                decision="APPROVED",
                reviewed_by=reviewer_id,
                decision_notes=notes,
                reviewed_at=delivered_at,
                delivered_at=delivered_at,
            )
        )

    async def mark_draft_status(self, db: AsyncSession, draft_id: UUID, status: str) -> None:
        await db.execute(
            update(CaseNoteDraft).where(CaseNoteDraft.id == draft_id).values(status=status)
        )

    async def create_personal_details_draft(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        session_id: UUID,
        participant_id: UUID,
        staff_id: UUID,
        fields_json: dict,
        completeness_score: float,
        missing_fields: list[str],
    ) -> PersonalDetailsDraft:
        row = PersonalDetailsDraft(
            tenant_id=tenant_id,
            session_id=session_id,
            participant_id=participant_id,
            staff_id=staff_id,
            fields_json=fields_json,
            completeness_score=completeness_score,
            missing_fields=missing_fields,
            status="DRAFT",
        )
        db.add(row)
        await db.flush()
        return row

    async def mark_draft_delivered(
        self, db: AsyncSession, draft_id: UUID, delivered_at: datetime
    ) -> None:
        await db.execute(
            update(CaseNoteDraft)
            .where(CaseNoteDraft.id == draft_id)
            .values(status="DELIVERED", delivered_at=delivered_at)
        )
