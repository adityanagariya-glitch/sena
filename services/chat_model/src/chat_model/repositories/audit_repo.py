from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from chat_model.models.db import ChatAuditLog


class AuditRepo:
    """Repository for chat audit logs."""

    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def append_audit(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        session_id: str,
        question: str,
        answer: str,
        doc_ids: list[str],
        latency_ms: int,
        tokens_in: int = 0,
        tokens_out: int = 0,
    ) -> ChatAuditLog:
        """Insert audit log entry."""
        row = ChatAuditLog(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            question=question,
            answer=answer,
            doc_ids=doc_ids,
            latency_ms=latency_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            created_at=datetime.now(timezone.utc),
        )
        self._s.add(row)
        await self._s.commit()
        await self._s.refresh(row)
        return row
