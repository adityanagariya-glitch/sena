"""SQLAlchemy ORM models for the restrictive practice detection module."""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class NDISPolicyChunk(Base):
    """Stores embedded NDIS policy document chunks for RAG retrieval."""

    __tablename__ = "rp_ndis_policy_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chunk_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    document_source: Mapped[str] = mapped_column(String(200), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(50), nullable=False)
    document_type: Mapped[str] = mapped_column(String(100), nullable=False, server_default="Regulatory")
    embedding: Mapped[list[float]] = mapped_column(HALFVEC(1024), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class BehaviourSupportPlan(Base):
    """Client behaviour support plans — source of truth for authorised practices."""

    __tablename__ = "behaviour_support_plans"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    client_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    practice_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="Active")
    approved_dosage: Mapped[str | None] = mapped_column(String(200))
    approved_conditions: Mapped[str | None] = mapped_column(Text)
    authorised_by: Mapped[str | None] = mapped_column(String(200))
    valid_from: Mapped[datetime | None] = mapped_column(DateTime)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CaseNoteRun(Base):
    """Audit log for every case note processed through the pipeline."""

    __tablename__ = "rp_case_note_runs"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    case_note_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    client_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    worker_id: Mapped[str] = mapped_column(String(100), nullable=False)
    triage_flagged: Mapped[bool] = mapped_column(Boolean, nullable=False)
    evaluator_output: Mapped[dict | None] = mapped_column(JSONB)
    authorisation_status: Mapped[str | None] = mapped_column(String(100))
    alert_required: Mapped[bool] = mapped_column(Boolean, default=False)
    processing_time_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
