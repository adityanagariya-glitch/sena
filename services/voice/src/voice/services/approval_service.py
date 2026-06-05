from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from voice.repositories.voice_repo import VoiceRepository


class ApprovalService:
    def __init__(self, repo: VoiceRepository):
        self.repo = repo

    async def decide(
        self,
        ai_db: AsyncSession,
        shared_db: AsyncSession,
        approval_item_id: UUID,
        decision: str,
        reviewer_id: UUID,
        review_notes: str,
    ) -> dict:
        item = await self.repo.get_approval_item(ai_db, approval_item_id)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Approval item not found"
            )
        if item.status not in {"PENDING", "ASSIGNED", "REVIEWED"}:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already decided")

        draft = await self.repo.get_case_note_draft(ai_db, item.item_id)
        if draft is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Case note draft not found"
            )

        if decision == "REJECTED":
            now = datetime.now(timezone.utc)
            await self.repo.mark_approval_rejected(ai_db, item.id, reviewer_id, review_notes, now)
            await self.repo.mark_draft_status(ai_db, draft.id, "REJECTED")
            return {
                "approval_item_id": item.id,
                "decision": "REJECTED",
                "status": "REJECTED",
                "shared_case_note_id": None,
                "delivered_at": None,
            }

        case_note_id = draft.id
        payload = draft.draft_json
        insert_sql = text(
            """
            INSERT INTO case_notes (
              id, tenant_id, participant_id, staff_id, shift_id, content_json, created_at, updated_at
            ) VALUES (
              :id, :tenant_id, :participant_id, :staff_id, :shift_id, :content_json::jsonb, now(), now()
            )
            ON CONFLICT (id) DO UPDATE SET
              content_json = EXCLUDED.content_json,
              updated_at = now()
            """
        )
        await shared_db.execute(
            insert_sql,
            {
                "id": str(case_note_id),
                "tenant_id": str(draft.tenant_id),
                "participant_id": str(draft.participant_id),
                "staff_id": str(draft.staff_id),
                "shift_id": str(draft.shift_id),
                "content_json": str(payload).replace("'", '"'),
            },
        )

        now = datetime.now(timezone.utc)
        await self.repo.mark_approval_delivered(ai_db, item.id, reviewer_id, review_notes, now)
        await self.repo.mark_draft_delivered(ai_db, draft.id, now)

        return {
            "approval_item_id": item.id,
            "decision": "APPROVED",
            "status": "DELIVERED",
            "shared_case_note_id": case_note_id,
            "delivered_at": now,
        }
