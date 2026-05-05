from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
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
    staff_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    client_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
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
