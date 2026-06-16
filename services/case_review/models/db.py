from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class RollingSummary(Base):
    """
    Rolling LLM-compressed summary of past case notes for a staff-client pair.
    One row per (tenant, staff, client) — upserted on each /context call.
    processed_note_ids guards against double-processing.
    """

    __tablename__ = "cr_rolling_summary"
    __table_args__ = (
        UniqueConstraint("tenant_id", "staff_id", "client_id", name="uq_rolling_summary_pair"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    staff_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # {note_count, last_dates[], incident_count, risk_flags[]}
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    # replay-proof: note IDs already incorporated into summary
    processed_note_ids: Mapped[list] = mapped_column(
        ARRAY(String), nullable=False, server_default="{}"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ReviewSession(Base):
    """
    One review session per case note drafting event.
    Tracks the full lifecycle: raw paragraph → classify → review → submit.
    """

    __tablename__ = "cr_review_session"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    staff_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    # FK-by-ID to other engineer's case note (not a real FK — cross-service)
    drafted_case_note_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    raw_paragraph: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # {field_id: value, ...}
    classified_fields: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # [{field_id, label, reason}, ...]
    missing_fields: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # {risks[], restrictive_practices[], anomalies[], improvements[]}
    flags: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    incident_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # input | classified | reviewed | submitted
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="input")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class IncidentDraft(Base):
    """
    AI-autofilled incident form draft. Staff must confirm before submission.
    Human-in-the-loop: staff_confirmed must be True before submit path proceeds.
    """

    __tablename__ = "cr_incident_draft"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    review_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cr_review_session.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # source fields extracted from case note text
    autofill_source: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # final form fields to be submitted
    draft_fields: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # NDIS non-negotiable: staff must explicitly confirm AI draft
    staff_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # draft | confirmed | submitted
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ReviewAuditLog(Base):
    """
    Append-only audit trail. Every AI flag raised + staff action + submit is logged.
    NDIS compliance requirement — do NOT delete rows.
    """

    __tablename__ = "cr_review_audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    review_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cr_review_session.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # ai_flag_raised | staff_acknowledged | submitted | incident_detected | incident_confirmed
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class NDISPolicyChunk(Base):
    """
    NDIS policy document chunks for RAG retrieval.
    Global reference data — shared across all tenants, no RLS needed.
    HALFVEC(1024) matches Cohere Embed English v3 output dimensions.
    """

    __tablename__ = "rp_ndis_policy_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chunk_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    document_source: Mapped[str] = mapped_column(String(200), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(50), nullable=False)
    document_type: Mapped[str] = mapped_column(
        String(100), nullable=False, server_default="Regulatory"
    )
    embedding: Mapped[list[float]] = mapped_column(HALFVEC(1024), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class BehaviourSupportPlan(Base):
    """
    Authorised restrictive practice entries from the BSP.
    Scoped by tenant_id — each provider manages their own client BSPs.
    """

    __tablename__ = "behaviour_support_plans"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
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
    """
    Audit log of every LangGraph pipeline run.
    Per-tenant — tenant_id scopes the row; RLS enforced.
    Timing columns (triage_ms, rag_ms, etc.) feed performance dashboards.
    """

    __tablename__ = "rp_case_note_runs"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    case_note_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    client_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    worker_id: Mapped[str] = mapped_column(String(100), nullable=False)
    triage_flagged: Mapped[bool] = mapped_column(Boolean, nullable=False)
    evaluator_output: Mapped[dict | None] = mapped_column(JSONB)
    authorisation_status: Mapped[str | None] = mapped_column(String(100))
    alert_required: Mapped[bool] = mapped_column(Boolean, default=False)
    processing_time_ms: Mapped[int | None] = mapped_column(Integer)
    triage_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rag_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evaluator_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cross_check_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    incident_draft_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evaluator_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
