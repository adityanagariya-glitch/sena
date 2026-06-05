# SQLAlchemy Declarative Base & Mixins (shared/src/sena_common/db/base.py)
#
# Purpose: Provides base classes and mixins for all database models
#
# Classes:
# 1. Base(DeclarativeBase) - Root class for all SQLAlchemy models
#    - Used as base for schema definition
#
# 2. TenantMixin - Adds tenant isolation to models
#    - tenant_id: Foreign key to tenants table
#    - Makes table tenant-scoped (RLS policies reference this column)
#    - Indexed for efficient RLS filtering
#
# 3. TimestampMixin - Adds audit timestamps to models
#    - created_at: Auto-set on insert
#    - updated_at: Auto-set on insert and update
#    - Uses server-side defaults (database time)
#
# 4. Tenant - Core model for multi-tenancy
#    - id: UUID primary key
#    - name: Organization name
#    - slug: URL-friendly identifier (unique)
#    - is_active: Soft delete flag
#    - created_at, updated_at: Timestamps
#
# Usage pattern:
# class OCRJob(Base, TenantMixin, TimestampMixin):
#     __tablename__ = "ocr_jobs"
#     id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
#     # ... other columns
