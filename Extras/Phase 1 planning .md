Phase 1 is now locked with your defaults, and I will generate Phase 2 focused only on Flow B with production-ready AI-layer details aligned to revised_plan.md and the existing workspace structure. I will quickly inspect the current backend files so the implementation guide and code blocks match your repo conventions exactly.

Context reads:
- Read sena-ai/services
- Read README.md
- Read sena-ai/services/ocr/pyproject.toml
- Read sena-ai/pyproject.toml

I confirmed this is still an early scaffold, so I will now base Flow B on the shared package conventions already present and map everything into the existing sena-ai workspace layout. Next I am reading the shared modules to keep naming, config, and middleware consistent.

Shared module reads:
- Read sena-ai/shared/src/sena_common/config/settings.py
- Read sena-ai/shared/src/sena_common/middleware/tenant_context.py
- Read sena-ai/shared/src/sena_common/schemas/responses.py
- Read sena-ai/shared/src/sena_common/db/session.py
- Read memory: /memories/repo/sena-ai-phase-gates.md

I found repo memory notes confirming there is no real voice implementation yet, so I will produce the full Flow B implementation guide from scratch in the existing monorepo pattern. I am now pulling the current voice prototype and existing contracts to keep endpoint naming and payloads compatible.

Prototype and contract reads:
- Read api_contracts.py
- Read sena-ai/services/ocr/src/ocr/main.py
- Read poc_onboarding.py
- Read sena-ai/services/ocr/src/ocr/api/routes.py

Phase 1 complete. Generating full implementation plan now.

# AI Layer Implementation Guide — SENA Flow B Voice Case Note Dictation

## SECTION 1 — AI Layer Overview
Flow B delivers a real-time voice dictation AI pipeline for support workers after shift completion. The mobile app initiates a CASE_NOTE voice session, streams audio through LiveKit, gets transcription from AWS Transcribe, sends transcript turns into a DictationAgent powered by Bedrock Claude Sonnet, receives natural language responses plus structured drafting signals, and on session end compiles a structured case note JSON, stores a draft in AI DB, enqueues manager approval, and emits a case_note.submitted event for downstream risk analysis. Final approved notes are written from AI layer into the client shared case_notes table with idempotent upsert.

Technology and model decisions
- Cloud and runtime: AWS aligned with client platform, lower integration friction.
- API framework: Python FastAPI for async I/O, schema-first APIs, OpenAPI generation.
- LLM provider: Bedrock Claude Sonnet as primary for clinical narrative quality.
- Voice stack: AWS Transcribe plus AWS Polly plus LiveKit for low-complexity AWS-native MVP.
- Session memory: Redis for turn-state and session locks, sub-millisecond access.
- Durable storage: Dual Postgres pattern, AI DB for AI-owned artifacts and queue state, shared DB for approved case notes.
- Messaging: SNS plus SQS event envelope with idempotency for risk chain trigger.
- Approval gate: Human-in-the-loop queue before shared DB publication.
- Observability: structlog plus OpenTelemetry fields in JSON logs.

Boundary with broader system
- Mobile frontend responsibility: WebRTC media UX and rendering, not in this implementation.
- Main backend responsibility: user auth issuance and app orchestration.
- AI service responsibility: all dictation intelligence, prompting, model calls, session-state, AI data persistence, event emission, approval transition logic, and write-through to shared DB after approval.
- Contract boundary: REST endpoints from main backend to AI service and LiveKit token endpoint for client media session bootstrap.

Flow B endpoint list
- POST /v1/voice/session: start CASE_NOTE session and acquire LiveKit credentials.
- POST /v1/voice/session/turn: process one transcribed turn with DictationAgent.
- POST /v1/voice/session/end: compile case note, write draft, emit risk event, enqueue approval.
- POST /v1/approval/decision: manager approves or rejects draft.
- GET /v1/voice/session/{session_id}: session status and completeness.
- GET /health/live: process liveness.
- GET /health/ready: dependency readiness.

## SECTION 2 — Architecture Diagram (text)
Component topology
1. Mobile App
2. Main Backend
3. AI Voice Service (this layer)
4. LiveKit (EC2)
5. AWS Transcribe streaming
6. AWS Polly
7. Bedrock Claude Sonnet
8. ElastiCache Redis
9. AI Dedicated Postgres
10. Client Shared Postgres
11. SNS topic case-note-events
12. SQS subscribers for risk pipeline

Text architecture
Mobile App sends authenticated request to Main Backend.
Main Backend calls AI Voice Service REST endpoint to create CASE_NOTE session.
AI Voice Service validates JWT and tenant context, acquires Redis NX lock by participant_id, persists voice session row in AI DB, returns LiveKit token metadata.
Mobile audio flows via WebRTC through LiveKit. Transcription arrives from Transcribe pipeline to backend turn endpoint.
Turn endpoint loads session context from Redis, injects structured prompt with last turns and template coverage, calls Bedrock Sonnet, receives response text and structured extraction, updates draft context in Redis and DictationTurn table.
On end endpoint, service compiles structured case note JSON, computes section scores and missing topics, writes CaseNoteDraft in AI DB as PENDING_APPROVAL, inserts ApprovalQueue item (Tier 2 by default), writes outbox record and publishes case_note.submitted event to SNS with version and idempotency_key.
Risk service consumes via SQS and refetches full note data as required by design.
Manager action calls approval decision endpoint. If approved, service writes to shared case_notes with idempotent upsert and marks AI records DELIVERED. If rejected, marks REJECTED with reason.

Flow B data flow steps
- Session start
1. Request POST /v1/voice/session objective CASE_NOTE.
2. JWT parsed, tenant_id, staff_id, role enforced.
3. Redis lock key participant_session:{participant_id} set NX EX 3600.
4. AI DB voice_sessions row created ACTIVE.
5. LiveKit JWT created and returned.

- Turn processing
1. Request POST /v1/voice/session/turn with transcript text.
2. Context loaded from Redis and recent turns from AI DB fallback.
3. Dictation prompt built with clinical style constraints and template coverage.
4. Bedrock called with retry budget 2.
5. Response parsed into agent_reply, coverage updates, missing topics.
6. State persisted in Redis and AI DB dictation_turns.

- Session end
1. Request POST /v1/voice/session/end.
2. Compile structured case note JSON and completeness score.
3. Insert ai_case_note_drafts status PENDING_APPROVAL.
4. Insert approval_queue status PENDING tier 2.
5. Publish case_note.submitted event to SNS topic case-note-events.
6. Release Redis lock and close session status COMPLETED.

- Approval decision
1. POST /v1/approval/decision with item_id and decision.
2. If approved, write to shared case_notes with ON CONFLICT upsert.
3. Mark approval DELIVERED and draft DELIVERED.
4. Emit approval.decided event optional for notification.

## SECTION 3 — Folder Structure and File Inventory

Target structure aligned to existing monorepo
- sena-ai/
  - services/
    - voice/
      - pyproject.toml
      - Dockerfile
      - src/
        - voice/
          - __init__.py
          - main.py
          - core/
            - __init__.py
            - settings.py
            - logging.py
          - api/
            - __init__.py
            - routes.py
            - deps.py
          - models/
            - __init__.py
            - db.py
            - schemas.py
          - services/
            - __init__.py
            - auth_service.py
            - livekit_service.py
            - redis_service.py
            - transcribe_service.py
            - bedrock_service.py
            - dictation_service.py
            - approval_service.py
            - event_service.py
          - repositories/
            - __init__.py
            - voice_repo.py
          - prompts/
            - dictation_prompt.py
          - utils/
            - __init__.py
            - idempotency.py
      - tests/
        - conftest.py
        - test_session_start.py
        - test_turn_processing.py
        - test_session_end.py
        - test_approval.py
        - test_health.py
      - openapi/
        - voice_flow_b_openapi.yaml
      - postman/
        - voice_flow_b.postman_collection.json
  - .github/
    - workflows/
      - voice-service-ci-cd.yml
  - docker-compose.yml
  - .env.example

## SECTION 4 — Environment Variables

- SENA_AI_SERVICE_NAME
  - Purpose: service identifier in responses and logs
  - Example: sena-voice
  - Required: yes

- SENA_AI_SERVICE_VERSION
  - Purpose: semantic version
  - Example: 0.1.0
  - Required: yes

- SENA_AI_ENVIRONMENT
  - Purpose: runtime mode development, staging, production
  - Example: development
  - Required: yes

- SENA_AI_DEBUG
  - Purpose: verbose diagnostics and docs exposure
  - Example: true
  - Required: yes

- SENA_AI_HOST
  - Purpose: bind host
  - Example: 0.0.0.0
  - Required: yes

- SENA_AI_PORT
  - Purpose: bind port
  - Example: 8082
  - Required: yes

- SENA_AI_LOG_LEVEL
  - Purpose: logger level
  - Example: INFO
  - Required: yes

- SENA_AI_AUTH_MODE
  - Purpose: dev_header or jwt
  - Example: dev_header
  - Required: yes

- SENA_AI_JWT_ISSUER
  - Purpose: expected JWT issuer
  - Example: https://main-backend.internal
  - Required: optional in dev, required in jwt mode

- SENA_AI_JWT_AUDIENCE
  - Purpose: expected JWT audience
  - Example: sena-ai-voice
  - Required: optional in dev, required in jwt mode

- SENA_AI_JWT_PUBLIC_KEY_PEM
  - Purpose: RS256 signature verification key
  - Example: -----BEGIN PUBLIC KEY-----...
  - Required: optional in dev, required in jwt mode

- SENA_AI_AI_DB_URL
  - Purpose: async SQLAlchemy URL for AI DB
  - Example: postgresql+asyncpg://sena_ai:pass@ai-db:5432/sena_ai
  - Required: yes

- SENA_AI_SHARED_DB_URL
  - Purpose: async SQLAlchemy URL for client shared DB
  - Example: postgresql+asyncpg://client_rw:pass@shared-db:5432/platform
  - Required: yes

- SENA_AI_REDIS_URL
  - Purpose: Redis connection for sessions and locks
  - Example: redis://redis:6379/0
  - Required: yes

- SENA_AI_REDIS_LOCK_TTL_SECONDS
  - Purpose: participant lock TTL
  - Example: 3600
  - Required: yes

- SENA_AI_REDIS_SESSION_TTL_SECONDS
  - Purpose: session state TTL
  - Example: 86400
  - Required: yes

- SENA_AI_AWS_REGION
  - Purpose: AWS region
  - Example: ap-southeast-2
  - Required: yes

- SENA_AI_BEDROCK_MODEL_ID
  - Purpose: primary model id
  - Example: anthropic.claude-3-5-sonnet-20240620-v1:0
  - Required: yes

- SENA_AI_BEDROCK_MAX_TOKENS
  - Purpose: response token cap
  - Example: 1200
  - Required: yes

- SENA_AI_BEDROCK_TEMPERATURE
  - Purpose: generation temperature
  - Example: 0.2
  - Required: yes

- SENA_AI_LIVEKIT_API_KEY
  - Purpose: sign room tokens
  - Example: LK_API_KEY
  - Required: yes

- SENA_AI_LIVEKIT_API_SECRET
  - Purpose: sign room tokens
  - Example: LK_API_SECRET
  - Required: yes

- SENA_AI_LIVEKIT_URL
  - Purpose: livekit websocket URL
  - Example: wss://livekit.sena.internal
  - Required: yes

- SENA_AI_SNS_CASE_NOTE_TOPIC_ARN
  - Purpose: topic for case_note.submitted
  - Example: arn:aws:sns:ap-southeast-2:123456789012:case-note-events
  - Required: yes

- SENA_AI_RATE_LIMIT_START_PER_MINUTE
  - Purpose: session-start rate limit per tenant
  - Example: 30
  - Required: yes

- SENA_AI_RATE_LIMIT_TURN_PER_MINUTE
  - Purpose: turn endpoint rate limit per session
  - Example: 120
  - Required: yes

- SENA_AI_MAX_CONCURRENT_SESSIONS_PER_USER
  - Purpose: concurrency guard
  - Example: 5
  - Required: yes

- SENA_AI_PROVIDER_TIMEOUT_SECONDS
  - Purpose: timeout for external AI calls
  - Example: 1.2
  - Required: yes

- SENA_AI_PROVIDER_MAX_RETRIES
  - Purpose: retry budget
  - Example: 2
  - Required: yes

## SECTION 5 — AI API Contract

METHOD: POST
PATH: /v1/voice/session
PURPOSE: Start CASE_NOTE voice dictation session and return media credentials
AUTH: Required — Bearer JWT in production, header resolver in development
REQUEST HEADERS:
  Authorization: Bearer \<token\>
  Content-Type: application/json
  X-Tenant-ID: required in dev mode
  X-User-ID: required in dev mode
  X-User-Role: required in dev mode
REQUEST BODY:
```json
{
  "objective": "CASE_NOTE",
  "participant_id": "uuid",
  "staff_id": "uuid",
  "shift_id": "uuid",
  "language": "en-AU",
  "metadata": {
    "device_os": "iOS",
    "app_version": "1.2.3"
  }
}
```
RESPONSE 201:
```json
{
  "session_id": "uuid",
  "status": "ACTIVE",
  "objective": "CASE_NOTE",
  "livekit": {
    "room_name": "voice-case-note-\<session_id\>",
    "token": "jwt",
    "url": "wss://livekit.sena.internal"
  },
  "lock_acquired": true
}
```
RESPONSE 400: { "error": "Validation failed", "details": [...] }
RESPONSE 401: { "error": "Unauthorised" }
RESPONSE 403: { "error": "Forbidden role" }
RESPONSE 409: { "error": "Active session exists", "existing_session_id": "uuid" }
RESPONSE 429: { "error": "Rate limit exceeded", "retry_after": 60 }
RESPONSE 503: { "error": "Dependency unavailable" }
STREAMING: no

METHOD: POST
PATH: /v1/voice/session/turn
PURPOSE: Process one transcribed turn and return AI reply plus draft coverage state
AUTH: Required
REQUEST HEADERS:
  Authorization: Bearer \<token\>
  Content-Type: application/json
REQUEST BODY:
```json
{
  "session_id": "uuid",
  "transcript": "Participant was calm and engaged during meal prep...",
  "transcript_confidence": 0.93,
  "audio_duration_ms": 5400,
  "sequence_number": 12,
  "timestamp": "2026-04-07T10:15:00Z"
}
```
RESPONSE 200:
```json
{
  "session_id": "uuid",
  "sequence_number": 12,
  "agent_reply": "Noted. Please confirm any incidents, safety concerns, or medication support this shift.",
  "draft_preview": "Participant appeared calm and engaged during meal preparation...",
  "completeness_score": 0.67,
  "missing_topics": [
    "incidents_risks",
    "medications_health",
    "handover_notes"
  ],
  "model": "anthropic.claude-3-5-sonnet-20240620-v1:0",
  "latency_ms": 742
}
```
RESPONSE 400: { "error": "Validation failed", "details": [...] }
RESPONSE 401: { "error": "Unauthorised" }
RESPONSE 404: { "error": "Session not found" }
RESPONSE 409: { "error": "Session not active" }
RESPONSE 429: { "error": "Rate limit exceeded", "retry_after": 60 }
RESPONSE 503: { "error": "AI provider unavailable", "fallback_used": false }
STREAMING: no

METHOD: POST
PATH: /v1/voice/session/end
PURPOSE: Finalize dictation, compile structured case note, persist draft, enqueue approval, emit risk event
AUTH: Required
REQUEST HEADERS:
  Authorization: Bearer \<token\>
  Content-Type: application/json
REQUEST BODY:
```json
{
  "session_id": "uuid",
  "ended_at": "2026-04-07T10:22:00Z",
  "client_timezone": "Australia/Sydney"
}
```
RESPONSE 200:
```json
{
  "session_id": "uuid",
  "draft_id": "uuid",
  "approval_item_id": "uuid",
  "event_id": "uuid",
  "status": "PENDING_APPROVAL",
  "case_note": {
    "participant_id": "uuid",
    "staff_id": "uuid",
    "shift_id": "uuid",
    "narrative": "string",
    "sections": {
      "participant_state": "string",
      "support_actions": "string",
      "incidents_risks": "string",
      "medications_health": "string",
      "outcomes_followup": "string",
      "handover_notes": "string"
    },
    "overall_completeness_score": 0.84,
    "missing_topics": []
  }
}
```
RESPONSE 400: { "error": "Validation failed", "details": [...] }
RESPONSE 401: { "error": "Unauthorised" }
RESPONSE 404: { "error": "Session not found" }
RESPONSE 409: { "error": "Session already ended" }
RESPONSE 503: { "error": "Publish failed", "retryable": true }
STREAMING: no

METHOD: GET
PATH: /v1/voice/session/{session_id}
PURPOSE: Fetch current session status and completeness
AUTH: Required
REQUEST HEADERS:
  Authorization: Bearer \<token\>
RESPONSE 200:
```json
{
  "session_id": "uuid",
  "status": "ACTIVE",
  "objective": "CASE_NOTE",
  "turn_count": 14,
  "completeness_score": 0.75,
  "missing_topics": ["handover_notes"]
}
```
RESPONSE 401: { "error": "Unauthorised" }
RESPONSE 404: { "error": "Session not found" }
STREAMING: no

METHOD: POST
PATH: /v1/approval/decision
PURPOSE: Manager approval gate for case note drafts; approved items are written to shared DB
AUTH: Required — role manager or admin
REQUEST HEADERS:
  Authorization: Bearer \<token\>
  Content-Type: application/json
REQUEST BODY:
```json
{
  "approval_item_id": "uuid",
  "decision": "APPROVED",
  "reviewer_id": "uuid",
  "review_notes": "Looks complete and accurate."
}
```
RESPONSE 200:
```json
{
  "approval_item_id": "uuid",
  "decision": "APPROVED",
  "status": "DELIVERED",
  "shared_case_note_id": "uuid",
  "delivered_at": "2026-04-07T10:30:00Z"
}
```
RESPONSE 400: { "error": "Invalid decision payload" }
RESPONSE 401: { "error": "Unauthorised" }
RESPONSE 403: { "error": "Forbidden role" }
RESPONSE 404: { "error": "Approval item not found" }
RESPONSE 409: { "error": "Already decided" }
RESPONSE 503: { "error": "Shared DB write failed", "retryable": true }
STREAMING: no

METHOD: GET
PATH: /health/live
PURPOSE: process liveness
AUTH: none
RESPONSE 200: { "status": "alive", "service": "sena-voice", "version": "0.1.0" }

METHOD: GET
PATH: /health/ready
PURPOSE: dependency readiness
AUTH: none
RESPONSE 200:
```json
{
  "status": "healthy|degraded|unhealthy",
  "checks": {
    "ai_database": "healthy|unhealthy",
    "shared_database": "healthy|unhealthy",
    "redis": "healthy|unhealthy",
    "bedrock": "healthy|unhealthy",
    "sns": "healthy|unhealthy"
  }
}
```

## SECTION 6 — Prompt Engineering

Feature: Dictation turn response and draft enrichment
System prompt full text
You are the SENA Dictation Agent for Australian disability support case notes.
You must transform transcribed worker dictation into clear, factual, neutral, clinically appropriate case note language.
Do not invent facts.
Do not include legal advice.
Use Australian English spelling.
Prioritise objective observations over assumptions.
If information is incomplete, ask one short follow-up question to close the highest-risk missing section first.
Always maintain this section template:
1) participant_state
2) support_actions
3) incidents_risks
4) medications_health
5) outcomes_followup
6) handover_notes

Output must be strict JSON with keys:
- agent_reply
- draft_updates
- section_coverage
- missing_topics
- overall_completeness_score
- safety_category

Section coverage is a float from 0.0 to 1.0 for each section.
overall_completeness_score is weighted average with higher weight on incidents_risks and medications_health.
If transcript is empty or unclear, ask for restatement.
If transcript indicates abuse, self-harm, severe injury, medication error, restrictive practice breach, or immediate danger, set safety_category to urgent.
Never return markdown.

User input injection
- Template:
  ```json
  {
    "transcript": "\<latest turn text\>",
    "session_snapshot": {
      "existing_draft": "...",
      "section_coverage": {...},
      "missing_topics": [...]
    },
    "participant_context": {
      "participant_id": "...",
      "shift_id": "..."
    }
  }
  ```

Conversation history injection
- Last 5 turns injected as compact array of objects:
  ```json
  [{"speaker":"worker","text":"..."},{"speaker":"agent","text":"..."}]
  ```
- Older turns summarized by compression service and injected as summary_text string.

Output format instructions
- JSON schema validated server-side.
- Missing keys causes retry with repair prompt:
  Return only valid JSON matching required schema, no prose.

Token budget allocation
- System prompt: 900 tokens budget
- History: 1800 tokens max
- Current user turn: 1200 tokens max
- Response: max 1200 tokens
- Hard cap: 5100 effective budget before truncation

Edge cases
- Empty input: return agent_reply asking worker to repeat.
- Off-topic input: politely redirect to shift observations needed for case note.
- Unsafe content: tag safety_category urgent and force manager Tier 3 on end.
- Contradiction with prior turns: include clarification question instead of overwriting silently.
- PII leakage request: refuse and continue case note scope.

## SECTION 7 — Full Implementation Code

### FILE: /sena-ai/services/voice/pyproject.toml
```
[project]
name = "sena-voice"
version = "0.1.0"
description = "SENA Voice Dictation Service (Flow B)"
requires-python = ">=3.12"
dependencies = [
  "fastapi==0.115.6",
  "uvicorn[standard]==0.32.1",
  "pydantic==2.10.3",
  "pydantic-settings==2.7.0",
  "sqlalchemy[asyncio]==2.0.36",
  "asyncpg==0.30.0",
  "redis[hiredis]==5.2.1",
  "boto3==1.35.80",
  "botocore==1.35.80",
  "PyJWT[crypto]==2.10.1",
  "livekit-api==0.8.2",
  "httpx==0.28.1",
  "structlog==24.4.0",
  "python-dateutil==2.9.0.post0",
  "orjson==3.10.12"
]

[project.optional-dependencies]
dev = [
  "pytest==8.3.4",
  "pytest-asyncio==0.24.0",
  "pytest-cov==6.0.0",
  "anyio==4.7.0",
  "ruff==0.8.4",
  "mypy==1.13.0"
]

[build-system]
requires = ["setuptools>=75.0"]
build-backend = "setuptools.build_meta"
```

### FILE: /sena-ai/services/voice/src/voice/__init__.py
```
__all__ = ["main"]
```

### FILE: /sena-ai/services/voice/src/voice/core/settings.py
```
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class VoiceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SENA_AI_", case_sensitive=False)

    service_name: str = Field(default="sena-voice", alias="SERVICE_NAME")
    service_version: str = Field(default="0.1.0", alias="SERVICE_VERSION")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    debug: bool = Field(default=True, alias="DEBUG")
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8082, alias="PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    auth_mode: str = Field(default="dev_header", alias="AUTH_MODE")
    jwt_issuer: str | None = Field(default=None, alias="JWT_ISSUER")
    jwt_audience: str | None = Field(default=None, alias="JWT_AUDIENCE")
    jwt_public_key_pem: str | None = Field(default=None, alias="JWT_PUBLIC_KEY_PEM")

    ai_db_url: str = Field(alias="AI_DB_URL")
    shared_db_url: str = Field(alias="SHARED_DB_URL")
    redis_url: str = Field(alias="REDIS_URL")
    redis_lock_ttl_seconds: int = Field(default=3600, alias="REDIS_LOCK_TTL_SECONDS")
    redis_session_ttl_seconds: int = Field(default=86400, alias="REDIS_SESSION_TTL_SECONDS")

    aws_region: str = Field(default="ap-southeast-2", alias="AWS_REGION")
    bedrock_model_id: str = Field(default="anthropic.claude-3-5-sonnet-20240620-v1:0", alias="BEDROCK_MODEL_ID")
    bedrock_max_tokens: int = Field(default=1200, alias="BEDROCK_MAX_TOKENS")
    bedrock_temperature: float = Field(default=0.2, alias="BEDROCK_TEMPERATURE")

    livekit_api_key: str = Field(alias="LIVEKIT_API_KEY")
    livekit_api_secret: str = Field(alias="LIVEKIT_API_SECRET")
    livekit_url: str = Field(alias="LIVEKIT_URL")

    sns_case_note_topic_arn: str = Field(alias="SNS_CASE_NOTE_TOPIC_ARN")

    rate_limit_start_per_minute: int = Field(default=30, alias="RATE_LIMIT_START_PER_MINUTE")
    rate_limit_turn_per_minute: int = Field(default=120, alias="RATE_LIMIT_TURN_PER_MINUTE")
    max_concurrent_sessions_per_user: int = Field(default=5, alias="MAX_CONCURRENT_SESSIONS_PER_USER")

    provider_timeout_seconds: float = Field(default=1.2, alias="PROVIDER_TIMEOUT_SECONDS")
    provider_max_retries: int = Field(default=2, alias="PROVIDER_MAX_RETRIES")


settings = VoiceSettings()
```

### FILE: /sena-ai/services/voice/src/voice/core/logging.py
```
import logging
import structlog


def configure_logging(level: str) -> None:
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO))
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.add_log_level,
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper(), logging.INFO)),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
```

### FILE: /sena-ai/services/voice/src/voice/models/db.py
```
from __future__ import annotations

import uuid
from datetime import datetime
from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class VoiceSession(Base):
    __tablename__ = "voice_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    participant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    staff_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    shift_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    objective: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ACTIVE")
    turn_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    section_coverage: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    missing_topics: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    draft_preview: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DictationTurn(Base):
    __tablename__ = "dictation_turns"
    __table_args__ = (UniqueConstraint("session_id", "sequence_number", name="uq_dictation_turn_session_seq"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("voice_sessions.id"), nullable=False, index=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    transcript: Mapped[str] = mapped_column(Text, nullable=False)
    transcript_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    agent_reply: Mapped[str] = mapped_column(Text, nullable=False)
    section_coverage: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    missing_topics: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CaseNoteDraft(Base):
    __tablename__ = "ai_case_note_drafts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    participant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    staff_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    shift_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    draft_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    completeness_score: Mapped[float] = mapped_column(Float, nullable=False)
    missing_topics: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    safety_category: Mapped[str] = mapped_column(String(20), nullable=False, default="normal")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING_APPROVAL")
    note_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApprovalQueueItem(Base):
    __tablename__ = "approval_queue"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    item_type: Mapped[str] = mapped_column(String(50), nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    tier: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    decision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    decision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    participant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    note_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OutboxEvent(Base):
    __tablename__ = "outbox"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
```

### FILE: /sena-ai/services/voice/src/voice/models/schemas.py
```
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field, field_validator


class StartSessionRequest(BaseModel):
    objective: Literal["CASE_NOTE"]
    participant_id: UUID
    staff_id: UUID
    shift_id: UUID
    language: str = "en-AU"
    metadata: dict = Field(default_factory=dict)


class StartSessionResponse(BaseModel):
    session_id: UUID
    status: str
    objective: str
    lock_acquired: bool
    livekit: dict


class TurnRequest(BaseModel):
    session_id: UUID
    transcript: str = Field(min_length=1)
    transcript_confidence: float = Field(ge=0.0, le=1.0)
    audio_duration_ms: int = Field(gt=0)
    sequence_number: int = Field(gt=0)
    timestamp: datetime


class TurnResponse(BaseModel):
    session_id: UUID
    sequence_number: int
    agent_reply: str
    draft_preview: str
    completeness_score: float
    missing_topics: list[str]
    model: str
    latency_ms: int


class EndSessionRequest(BaseModel):
    session_id: UUID
    ended_at: datetime
    client_timezone: str = "Australia/Sydney"


class EndSessionResponse(BaseModel):
    session_id: UUID
    draft_id: UUID
    approval_item_id: UUID
    event_id: UUID
    status: str
    case_note: dict


class ApprovalDecisionRequest(BaseModel):
    approval_item_id: UUID
    decision: Literal["APPROVED", "REJECTED"]
    reviewer_id: UUID
    review_notes: str = ""

    @field_validator("review_notes")
    @classmethod
    def reject_requires_reason(cls, value: str, info):
        decision = info.data.get("decision")
        if decision == "REJECTED" and not value.strip():
            raise ValueError("review_notes is required when decision is REJECTED")
        return value


class ApprovalDecisionResponse(BaseModel):
    approval_item_id: UUID
    decision: str
    status: str
    shared_case_note_id: UUID | None = None
    delivered_at: datetime | None = None


class SessionStatusResponse(BaseModel):
    session_id: UUID
    status: str
    objective: str
    turn_count: int
    completeness_score: float
    missing_topics: list[str]


class ErrorResponse(BaseModel):
    error: str
    details: list[str] | None = None
    retry_after: int | None = None
    fallback_used: bool | None = None
    retryable: bool | None = None
```

### FILE: /sena-ai/services/voice/src/voice/prompts/dictation_prompt.py
```
SYSTEM_PROMPT = """
You are the SENA Dictation Agent for Australian disability support case notes.
Transform support worker dictation into clear, factual, neutral, clinically appropriate language.
Do not invent facts.
Do not include legal advice.
Use Australian English spelling.
If details are missing, ask one concise follow-up question that covers the highest-risk missing topic.

Maintain these sections:
participant_state
support_actions
incidents_risks
medications_health
outcomes_followup
handover_notes

Return strict JSON only:
{
  "agent_reply": "string",
  "draft_updates": {
    "participant_state": "string",
    "support_actions": "string",
    "incidents_risks": "string",
    "medications_health": "string",
    "outcomes_followup": "string",
    "handover_notes": "string"
  },
  "section_coverage": {
    "participant_state": 0.0,
    "support_actions": 0.0,
    "incidents_risks": 0.0,
    "medications_health": 0.0,
    "outcomes_followup": 0.0,
    "handover_notes": 0.0
  },
  "missing_topics": ["string"],
  "overall_completeness_score": 0.0,
  "safety_category": "normal|urgent"
}

Set safety_category to urgent if transcript indicates abuse, self-harm, severe injury, medication error, restrictive practice breach, or immediate danger.
Never return markdown.
""".strip()


def build_user_prompt(transcript: str, session_snapshot: dict, history: list[dict]) -> str:
    return (
        "LATEST_TRANSCRIPT:\n"
        f"{transcript}\n\n"
        "SESSION_SNAPSHOT_JSON:\n"
        f"{session_snapshot}\n\n"
        "RECENT_HISTORY_JSON:\n"
        f"{history}"
    )
```

### FILE: /sena-ai/services/voice/src/voice/services/auth_service.py
```
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID
import jwt
from fastapi import Header, HTTPException, status

from voice.core.settings import settings


@dataclass(frozen=True)
class AuthContext:
    tenant_id: UUID
    user_id: UUID
    role: str
    staff_id: UUID | None


def _parse_uuid(value: str, field: str) -> UUID:
    try:
        return UUID(value)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid {field}") from exc


def get_auth_context_from_dev_headers(
    x_tenant_id: str | None,
    x_user_id: str | None,
    x_user_role: str | None,
    x_staff_id: str | None = None,
) -> AuthContext:
    if not x_tenant_id or not x_user_id or not x_user_role:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing tenant/user headers")
    return AuthContext(
        tenant_id=_parse_uuid(x_tenant_id, "tenant_id"),
        user_id=_parse_uuid(x_user_id, "user_id"),
        role=x_user_role,
        staff_id=_parse_uuid(x_staff_id, "staff_id") if x_staff_id else None,
    )


def get_auth_context_from_jwt(authorization: str | None) -> AuthContext:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(
            token,
            settings.jwt_public_key_pem,
            algorithms=["RS256"],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    tenant_id = _parse_uuid(str(payload.get("tenant_id")), "tenant_id")
    user_id = _parse_uuid(str(payload.get("sub")), "sub")
    role = str(payload.get("role", "support_worker"))
    staff_claim = payload.get("staff_id")
    staff_id = _parse_uuid(str(staff_claim), "staff_id") if staff_claim else None
    return AuthContext(tenant_id=tenant_id, user_id=user_id, role=role, staff_id=staff_id)


async def auth_context_dependency(
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    x_user_role: str | None = Header(default=None, alias="X-User-Role"),
    x_staff_id: str | None = Header(default=None, alias="X-Staff-ID"),
) -> AuthContext:
    if settings.auth_mode == "jwt":
        return get_auth_context_from_jwt(authorization)
    return get_auth_context_from_dev_headers(x_tenant_id, x_user_id, x_user_role, x_staff_id)


def require_roles(ctx: AuthContext, allowed: set[str]) -> None:
    if ctx.role not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden role")
```

### FILE: /sena-ai/services/voice/src/voice/services/livekit_service.py
```
from livekit import api

from voice.core.settings import settings


def generate_livekit_access(session_id: str, participant_name: str) -> dict:
    room = f"voice-case-note-{session_id}"
    grants = api.VideoGrants(room_join=True, room=room)
    token = (
        api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(participant_name)
        .with_name(participant_name)
        .with_grants(grants)
        .to_jwt()
    )
    return {"room_name": room, "token": token, "url": settings.livekit_url}
```

### FILE: /sena-ai/services/voice/src/voice/services/redis_service.py
```
from __future__ import annotations

import json
from redis.asyncio import Redis
from fastapi import HTTPException, status
from voice.core.settings import settings


class RedisService:
    def __init__(self, redis: Redis):
        self.redis = redis

    async def acquire_participant_lock(self, tenant_id: str, participant_id: str, session_id: str) -> bool:
        key = f"participant_session:{tenant_id}:{participant_id}"
        ok = await self.redis.set(key, session_id, ex=settings.redis_lock_ttl_seconds, nx=True)
        return bool(ok)

    async def release_participant_lock(self, tenant_id: str, participant_id: str) -> None:
        key = f"participant_session:{tenant_id}:{participant_id}"
        await self.redis.delete(key)

    async def get_existing_session(self, tenant_id: str, participant_id: str) -> str | None:
        key = f"participant_session:{tenant_id}:{participant_id}"
        value = await self.redis.get(key)
        return value.decode() if isinstance(value, bytes) else value

    async def load_session_state(self, session_id: str) -> dict:
        key = f"voice_session_state:{session_id}"
        value = await self.redis.get(key)
        if value is None:
            return {}
        raw = value.decode() if isinstance(value, bytes) else value
        return json.loads(raw)

    async def save_session_state(self, session_id: str, payload: dict) -> None:
        key = f"voice_session_state:{session_id}"
        await self.redis.setex(key, settings.redis_session_ttl_seconds, json.dumps(payload))

    async def increment_rate_limit(self, scope: str, max_per_minute: int) -> None:
        key = f"rate_limit:{scope}"
        count = await self.redis.incr(key)
        if count == 1:
            await self.redis.expire(key, 60)
        if count > max_per_minute:
            ttl = await self.redis.ttl(key)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"error": "Rate limit exceeded", "retry_after": max(1, ttl)},
            )
```

### FILE: /sena-ai/services/voice/src/voice/services/bedrock_service.py
```
from __future__ import annotations

import json
import time
import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, status

from voice.core.settings import settings
from voice.prompts.dictation_prompt import SYSTEM_PROMPT, build_user_prompt


class BedrockService:
    def __init__(self):
        self.client = boto3.client(
            "bedrock-runtime",
            region_name=settings.aws_region,
            config=Config(read_timeout=max(2, int(settings.provider_timeout_seconds) + 1), retries={"max_attempts": 1}),
        )

    def _invoke_once(self, user_prompt: str) -> dict:
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": settings.bedrock_max_tokens,
            "temperature": settings.bedrock_temperature,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": [{"type": "text", "text": user_prompt}]}],
        }
        response = self.client.invoke_model(modelId=settings.bedrock_model_id, body=json.dumps(body))
        payload = json.loads(response["body"].read())
        text = payload["content"][0]["text"]
        return json.loads(text)

    def run_dictation_turn(self, transcript: str, session_snapshot: dict, history: list[dict]) -> tuple[dict, int]:
        prompt = build_user_prompt(transcript=transcript, session_snapshot=session_snapshot, history=history)
        start = time.perf_counter()
        last_error: Exception | None = None
        attempts = settings.provider_max_retries + 1
        for _ in range(attempts):
            try:
                data = self._invoke_once(prompt)
                latency_ms = int((time.perf_counter() - start) * 1000)
                return data, latency_ms
            except (ValueError, KeyError, BotoCoreError, ClientError) as exc:
                last_error = exc
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "AI provider unavailable", "fallback_used": False, "retryable": True, "cause": str(last_error)},
        )
```

### FILE: /sena-ai/services/voice/src/voice/services/transcribe_service.py
```
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TranscribeTurn:
    text: str
    confidence: float


class TranscribeService:
    async def normalize_turn(self, transcript: str, confidence: float) -> TranscribeTurn:
        cleaned = " ".join(transcript.split())
        return TranscribeTurn(text=cleaned, confidence=confidence)
```

### FILE: /sena-ai/services/voice/src/voice/services/event_service.py
```
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
import boto3
from voice.core.settings import settings


class EventService:
    def __init__(self):
        self.sns = boto3.client("sns", region_name=settings.aws_region)

    def build_case_note_submitted_event(self, tenant_id: str, case_note_id: str, summary: str, version: int = 1) -> dict:
        event_id = str(uuid.uuid4())
        return {
            "id": event_id,
            "event_type": "case_note.submitted",
            "tenant_id": tenant_id,
            "version": version,
            "idempotency_key": f"{case_note_id}:{version}",
            "metadata": {
                "request_id": event_id,
                "traceparent": "",
                "hop_count": 0,
                "retry_count": 0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            "payload": {
                "case_note_id": case_note_id,
                "summary": summary[:600],
            },
        }

    def publish_case_note_event(self, event_payload: dict) -> str:
        self.sns.publish(
            TopicArn=settings.sns_case_note_topic_arn,
            Message=json.dumps(event_payload),
            MessageAttributes={
                "event_type": {"DataType": "String", "StringValue": "case_note.submitted"},
                "tenant_id": {"DataType": "String", "StringValue": event_payload["tenant_id"]},
            },
        )
        return event_payload["id"]
```

### FILE: /sena-ai/services/voice/src/voice/services/dictation_service.py
```
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from voice.services.bedrock_service import BedrockService
from voice.services.redis_service import RedisService
from voice.services.transcribe_service import TranscribeService
from voice.repositories.voice_repo import VoiceRepository


DEFAULT_SECTIONS = {
    "participant_state": "",
    "support_actions": "",
    "incidents_risks": "",
    "medications_health": "",
    "outcomes_followup": "",
    "handover_notes": "",
}


class DictationService:
    def __init__(
        self,
        repo: VoiceRepository,
        redis_service: RedisService,
        bedrock: BedrockService,
        transcribe: TranscribeService,
    ) -> None:
        self.repo = repo
        self.redis = redis_service
        self.bedrock = bedrock
        self.transcribe = transcribe

    async def start_session(
        self,
        db: AsyncSession,
        tenant_id: UUID,
        participant_id: UUID,
        staff_id: UUID,
        shift_id: UUID,
        objective: str,
    ):
        if objective != "CASE_NOTE":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only CASE_NOTE is allowed")
        session = await self.repo.create_voice_session(db, tenant_id, participant_id, staff_id, shift_id, objective)
        await self.redis.save_session_state(
            str(session.id),
            {
                "draft_sections": DEFAULT_SECTIONS,
                "section_coverage": {k: 0.0 for k in DEFAULT_SECTIONS},
                "missing_topics": list(DEFAULT_SECTIONS.keys()),
                "history": [],
                "safety_category": "normal",
            },
        )
        return session

    async def process_turn(
        self,
        db: AsyncSession,
        session_id: UUID,
        transcript: str,
        transcript_confidence: float,
        sequence_number: int,
    ) -> dict:
        session = await self.repo.get_session_by_id(db, session_id)
        if session is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
        if session.status != "ACTIVE":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session not active")

        normalized = await self.transcribe.normalize_turn(transcript, transcript_confidence)
        state = await self.redis.load_session_state(str(session_id))
        history = state.get("history", [])[-5:]
        model_input_snapshot = {
            "existing_draft": state.get("draft_sections", DEFAULT_SECTIONS),
            "section_coverage": state.get("section_coverage", {k: 0.0 for k in DEFAULT_SECTIONS}),
            "missing_topics": state.get("missing_topics", list(DEFAULT_SECTIONS.keys())),
        }

        ai_out, latency_ms = self.bedrock.run_dictation_turn(normalized.text, model_input_snapshot, history)

        draft_updates = ai_out.get("draft_updates", {})
        merged = dict(state.get("draft_sections", DEFAULT_SECTIONS))
        for key, value in draft_updates.items():
            if key in merged and isinstance(value, str) and value.strip():
                merged[key] = value.strip()

        section_coverage = ai_out.get("section_coverage", {})
        missing_topics = ai_out.get("missing_topics", [])
        score = float(ai_out.get("overall_completeness_score", 0.0))
        safety_category = ai_out.get("safety_category", "normal")
        reply = str(ai_out.get("agent_reply", "Please continue with your notes."))

        history.append({"speaker": "worker", "text": normalized.text})
        history.append({"speaker": "agent", "text": reply})

        await self.redis.save_session_state(
            str(session_id),
            {
                "draft_sections": merged,
                "section_coverage": section_coverage,
                "missing_topics": missing_topics,
                "history": history[-10:],
                "safety_category": safety_category,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        await self.repo.add_turn(
            db=db,
            tenant_id=session.tenant_id,
            session_id=session.id,
            sequence_number=sequence_number,
            transcript=normalized.text,
            transcript_confidence=normalized.confidence,
            agent_reply=reply,
            section_coverage=section_coverage,
            missing_topics=missing_topics,
        )
        await self.repo.update_session_progress(
            db=db,
            session_id=session.id,
            draft_preview=" ".join([v for v in merged.values() if v]).strip(),
            section_coverage=section_coverage,
            missing_topics=missing_topics,
        )

        return {
            "agent_reply": reply,
            "draft_preview": " ".join([v for v in merged.values() if v]).strip(),
            "completeness_score": score,
            "missing_topics": missing_topics,
            "latency_ms": latency_ms,
        }
```

### FILE: /sena-ai/services/voice/src/voice/services/approval_service.py
```
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
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval item not found")
        if item.status not in {"PENDING", "ASSIGNED", "REVIEWED"}:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already decided")

        draft = await self.repo.get_case_note_draft(ai_db, item.item_id)
        if draft is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case note draft not found")

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
```

### FILE: /sena-ai/services/voice/src/voice/repositories/voice_repo.py
```
from __future__ import annotations

from datetime import datetime
from uuid import UUID
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from voice.models.db import ApprovalQueueItem, CaseNoteDraft, DictationTurn, VoiceSession, OutboxEvent


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

    async def update_session_progress(self, db: AsyncSession, session_id: UUID, draft_preview: str, section_coverage: dict, missing_topics: list) -> None:
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

    async def mark_session_completed(self, db: AsyncSession, session_id: UUID, ended_at: datetime) -> None:
        await db.execute(update(VoiceSession).where(VoiceSession.id == session_id).values(status="COMPLETED", ended_at=ended_at))

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

    async def insert_outbox(self, db: AsyncSession, tenant_id: UUID, event_type: str, payload: dict, idempotency_key: str) -> OutboxEvent:
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

    async def mark_outbox_published(self, db: AsyncSession, outbox_id: UUID, published_at: datetime) -> None:
        await db.execute(update(OutboxEvent).where(OutboxEvent.id == outbox_id).values(status="PUBLISHED", published_at=published_at))

    async def get_approval_item(self, db: AsyncSession, approval_item_id: UUID) -> ApprovalQueueItem | None:
        result = await db.execute(select(ApprovalQueueItem).where(ApprovalQueueItem.id == approval_item_id))
        return result.scalar_one_or_none()

    async def get_case_note_draft(self, db: AsyncSession, draft_id: UUID) -> CaseNoteDraft | None:
        result = await db.execute(select(CaseNoteDraft).where(CaseNoteDraft.id == draft_id))
        return result.scalar_one_or_none()

    async def mark_approval_rejected(self, db: AsyncSession, approval_item_id: UUID, reviewer_id: UUID, notes: str, reviewed_at: datetime) -> None:
        await db.execute(
            update(ApprovalQueueItem)
            .where(ApprovalQueueItem.id == approval_item_id)
            .values(status="REJECTED", decision="REJECTED", reviewed_by=reviewer_id, decision_notes=notes, reviewed_at=reviewed_at)
        )

    async def mark_approval_delivered(self, db: AsyncSession, approval_item_id: UUID, reviewer_id: UUID, notes: str, delivered_at: datetime) -> None:
        await db.execute(
            update(ApprovalQueueItem)
            .where(ApprovalQueueItem.id == approval_item_id)
            .values(status="DELIVERED", decision="APPROVED", reviewed_by=reviewer_id, decision_notes=notes, reviewed_at=delivered_at, delivered_at=delivered_at)
        )

    async def mark_draft_status(self, db: AsyncSession, draft_id: UUID, status: str) -> None:
        await db.execute(update(CaseNoteDraft).where(CaseNoteDraft.id == draft_id).values(status=status))

    async def mark_draft_delivered(self, db: AsyncSession, draft_id: UUID, delivered_at: datetime) -> None:
        await db.execute(update(CaseNoteDraft).where(CaseNoteDraft.id == draft_id).values(status="DELIVERED", delivered_at=delivered_at))
```

### FILE: /sena-ai/services/voice/src/voice/utils/idempotency.py
```
from __future__ import annotations


def build_idempotency_key(entity_id: str, version: int) -> str:
    return f"{entity_id}:{version}"
```

### FILE: /sena-ai/services/voice/src/voice/api/deps.py
```
from __future__ import annotations

from redis.asyncio import from_url as redis_from_url
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from voice.core.settings import settings


ai_engine = create_async_engine(settings.ai_db_url, pool_pre_ping=True, pool_size=10, max_overflow=20)
shared_engine = create_async_engine(settings.shared_db_url, pool_pre_ping=True, pool_size=10, max_overflow=20)
ai_session_factory = async_sessionmaker(bind=ai_engine, expire_on_commit=False, class_=AsyncSession)
shared_session_factory = async_sessionmaker(bind=shared_engine, expire_on_commit=False, class_=AsyncSession)
redis_client = redis_from_url(settings.redis_url, decode_responses=True)


async def get_ai_db() -> AsyncSession:
    async with ai_session_factory() as session:
        yield session


async def get_shared_db() -> AsyncSession:
    async with shared_session_factory() as session:
        yield session
```

### FILE: /sena-ai/services/voice/src/voice/api/routes.py
```
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from voice.api.deps import get_ai_db, get_shared_db, redis_client
from voice.models.schemas import (
    ApprovalDecisionRequest,
    ApprovalDecisionResponse,
    EndSessionRequest,
    EndSessionResponse,
    SessionStatusResponse,
    StartSessionRequest,
    StartSessionResponse,
    TurnRequest,
    TurnResponse,
)
from voice.repositories.voice_repo import VoiceRepository
from voice.services.approval_service import ApprovalService
from voice.services.auth_service import AuthContext, auth_context_dependency, require_roles
from voice.services.bedrock_service import BedrockService
from voice.services.dictation_service import DictationService
from voice.services.event_service import EventService
from voice.services.livekit_service import generate_livekit_access
from voice.services.redis_service import RedisService
from voice.services.transcribe_service import TranscribeService
from voice.core.settings import settings
from voice.utils.idempotency import build_idempotency_key

router = APIRouter()
repo = VoiceRepository()
redis_service = RedisService(redis_client)
dictation_service = DictationService(repo, redis_service, BedrockService(), TranscribeService())
approval_service = ApprovalService(repo)
event_service = EventService()


@router.get("/health/live")
async def health_live() -> dict:
    return {"status": "alive", "service": settings.service_name, "version": settings.service_version}


@router.get("/health/ready")
async def health_ready(ai_db: AsyncSession = Depends(get_ai_db), shared_db: AsyncSession = Depends(get_shared_db)) -> dict:
    checks = {"ai_database": "healthy", "shared_database": "healthy", "redis": "healthy", "bedrock": "healthy", "sns": "healthy"}
    overall = "healthy"
    try:
        await ai_db.execute("SELECT 1")
    except Exception:
        checks["ai_database"] = "unhealthy"
    try:
        await shared_db.execute("SELECT 1")
    except Exception:
        checks["shared_database"] = "unhealthy"
    try:
        await redis_client.ping()
    except Exception:
        checks["redis"] = "unhealthy"
    try:
        event_service.sns.get_topic_attributes(TopicArn=settings.sns_case_note_topic_arn)
    except Exception:
        checks["sns"] = "unhealthy"
    if "unhealthy" in checks.values():
        overall = "degraded"
    return {"status": overall, "checks": checks}


@router.post("/v1/voice/session", status_code=201, response_model=StartSessionResponse)
async def start_session(
    req: StartSessionRequest,
    auth: AuthContext = Depends(auth_context_dependency),
    ai_db: AsyncSession = Depends(get_ai_db),
):
    require_roles(auth, {"support_worker", "manager", "admin"})
    await redis_service.increment_rate_limit(f"start:{auth.tenant_id}", settings.rate_limit_start_per_minute)

    lock_ok = await redis_service.acquire_participant_lock(str(auth.tenant_id), str(req.participant_id), "pending")
    if not lock_ok:
        existing = await redis_service.get_existing_session(str(auth.tenant_id), str(req.participant_id))
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "Active session exists", "existing_session_id": existing},
        )

    session = await dictation_service.start_session(
        db=ai_db,
        tenant_id=auth.tenant_id,
        participant_id=req.participant_id,
        staff_id=req.staff_id,
        shift_id=req.shift_id,
        objective=req.objective,
    )
    await ai_db.commit()

    await redis_service.release_participant_lock(str(auth.tenant_id), str(req.participant_id))
    await redis_service.acquire_participant_lock(str(auth.tenant_id), str(req.participant_id), str(session.id))

    livekit = generate_livekit_access(session_id=str(session.id), participant_name=str(auth.user_id))

    return StartSessionResponse(
        session_id=session.id,
        status=session.status,
        objective=session.objective,
        lock_acquired=True,
        livekit=livekit,
    )


@router.post("/v1/voice/session/turn", response_model=TurnResponse)
async def process_turn(
    req: TurnRequest,
    auth: AuthContext = Depends(auth_context_dependency),
    ai_db: AsyncSession = Depends(get_ai_db),
):
    require_roles(auth, {"support_worker", "manager", "admin"})
    await redis_service.increment_rate_limit(f"turn:{auth.tenant_id}:{req.session_id}", settings.rate_limit_turn_per_minute)

    result = await dictation_service.process_turn(
        db=ai_db,
        session_id=req.session_id,
        transcript=req.transcript,
        transcript_confidence=req.transcript_confidence,
        sequence_number=req.sequence_number,
    )
    await ai_db.commit()

    return TurnResponse(
        session_id=req.session_id,
        sequence_number=req.sequence_number,
        agent_reply=result["agent_reply"],
        draft_preview=result["draft_preview"],
        completeness_score=result["completeness_score"],
        missing_topics=result["missing_topics"],
        model=settings.bedrock_model_id,
        latency_ms=result["latency_ms"],
    )


@router.post("/v1/voice/session/end", response_model=EndSessionResponse)
async def end_session(
    req: EndSessionRequest,
    auth: AuthContext = Depends(auth_context_dependency),
    ai_db: AsyncSession = Depends(get_ai_db),
):
    require_roles(auth, {"support_worker", "manager", "admin"})

    session = await repo.get_session_by_id(ai_db, req.session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if session.status != "ACTIVE":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session already ended")

    state = await redis_service.load_session_state(str(req.session_id))
    sections = state.get("draft_sections", {})
    coverage = state.get("section_coverage", {})
    missing = state.get("missing_topics", [])
    safety_category = state.get("safety_category", "normal")

    narrative = " ".join([v for v in sections.values() if isinstance(v, str) and v.strip()]).strip()
    score = float(sum(float(v) for v in coverage.values()) / max(len(coverage), 1))

    case_note_json = {
        "participant_id": str(session.participant_id),
        "staff_id": str(session.staff_id),
        "shift_id": str(session.shift_id),
        "narrative": narrative,
        "sections": sections,
        "section_scores": coverage,
        "overall_completeness_score": score,
        "missing_topics": missing,
        "compiled_at": datetime.now(timezone.utc).isoformat(),
    }

    draft = await repo.create_case_note_draft(
        db=ai_db,
        tenant_id=session.tenant_id,
        session_id=session.id,
        participant_id=session.participant_id,
        staff_id=session.staff_id,
        shift_id=session.shift_id,
        draft_json=case_note_json,
        completeness_score=score,
        missing_topics=missing,
        safety_category=safety_category,
    )
    tier = 3 if safety_category == "urgent" else 2
    approval = await repo.create_approval_item(
        db=ai_db,
        tenant_id=session.tenant_id,
        item_id=draft.id,
        participant_id=session.participant_id,
        note_version=draft.note_version,
        tier=tier,
    )

    event_payload = event_service.build_case_note_submitted_event(
        tenant_id=str(session.tenant_id),
        case_note_id=str(draft.id),
        summary=narrative,
        version=draft.note_version,
    )
    outbox = await repo.insert_outbox(
        db=ai_db,
        tenant_id=session.tenant_id,
        event_type="case_note.submitted",
        payload=event_payload,
        idempotency_key=build_idempotency_key(str(draft.id), draft.note_version),
    )

    event_id = event_service.publish_case_note_event(event_payload)
    await repo.mark_outbox_published(ai_db, outbox.id, datetime.now(timezone.utc))
    await repo.mark_session_completed(ai_db, session.id, req.ended_at)
    await ai_db.commit()

    await redis_service.release_participant_lock(str(auth.tenant_id), str(session.participant_id))

    return EndSessionResponse(
        session_id=session.id,
        draft_id=draft.id,
        approval_item_id=approval.id,
        event_id=UUID(event_id),
        status="PENDING_APPROVAL",
        case_note=case_note_json,
    )


@router.get("/v1/voice/session/{session_id}", response_model=SessionStatusResponse)
async def get_session_status(
    session_id: UUID,
    auth: AuthContext = Depends(auth_context_dependency),
    ai_db: AsyncSession = Depends(get_ai_db),
):
    require_roles(auth, {"support_worker", "manager", "admin"})
    session = await repo.get_session_by_id(ai_db, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    coverage = session.section_coverage or {}
    score = float(sum(float(v) for v in coverage.values()) / max(len(coverage), 1))
    return SessionStatusResponse(
        session_id=session.id,
        status=session.status,
        objective=session.objective,
        turn_count=session.turn_count,
        completeness_score=score,
        missing_topics=session.missing_topics or [],
    )


@router.post("/v1/approval/decision", response_model=ApprovalDecisionResponse)
async def approval_decision(
    req: ApprovalDecisionRequest,
    auth: AuthContext = Depends(auth_context_dependency),
    ai_db: AsyncSession = Depends(get_ai_db),
    shared_db: AsyncSession = Depends(get_shared_db),
):
    require_roles(auth, {"manager", "admin"})
    result = await approval_service.decide(
        ai_db=ai_db,
        shared_db=shared_db,
        approval_item_id=req.approval_item_id,
        decision=req.decision,
        reviewer_id=req.reviewer_id,
        review_notes=req.review_notes,
    )
    await shared_db.commit()
    await ai_db.commit()
    return ApprovalDecisionResponse(**result)
```

### FILE: /sena-ai/services/voice/src/voice/main.py
```
from __future__ import annotations

from contextlib import asynccontextmanager
from fastapi import FastAPI
from voice.api.routes import router
from voice.core.logging import configure_logging
from voice.core.settings import settings
from voice.api.deps import ai_engine, shared_engine


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(settings.log_level)
    yield
    await ai_engine.dispose()
    await shared_engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="SENA Voice Service - Flow B",
        version=settings.service_version,
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    app.include_router(router)
    return app
```

### FILE: /sena-ai/services/voice/Dockerfile
```
FROM python:3.12-slim

WORKDIR /app

COPY services/voice/pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir -U pip && pip install --no-cache-dir .

COPY services/voice/src /app/src
ENV PYTHONPATH=/app/src

EXPOSE 8082

CMD ["uvicorn", "voice.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8082"]
```

### FILE: docker-compose.yml
```
version: "3.9"

services:
  sena-voice:
    build:
      context: .
      dockerfile: services/voice/Dockerfile
    container_name: sena-voice
    env_file:
      - .env
    ports:
      - "8082:8082"
    depends_on:
      - redis
      - ai-db
      - shared-db

  redis:
    image: redis:7.4-alpine
    container_name: sena-redis
    ports:
      - "6379:6379"

  ai-db:
    image: pgvector/pgvector:pg16
    container_name: sena-ai-db
    environment:
      POSTGRES_USER: sena_ai
      POSTGRES_PASSWORD: sena_ai
      POSTGRES_DB: sena_ai
    ports:
      - "5433:5432"

  shared-db:
    image: postgres:16-alpine
    container_name: sena-shared-db
    environment:
      POSTGRES_USER: shared
      POSTGRES_PASSWORD: shared
      POSTGRES_DB: platform
    ports:
      - "5434:5432"
```

### FILE: .env.example
```
SENA_AI_SERVICE_NAME=sena-voice
SENA_AI_SERVICE_VERSION=0.1.0
SENA_AI_ENVIRONMENT=development
SENA_AI_DEBUG=true
SENA_AI_HOST=0.0.0.0
SENA_AI_PORT=8082
SENA_AI_LOG_LEVEL=INFO

SENA_AI_AUTH_MODE=dev_header
SENA_AI_JWT_ISSUER=
SENA_AI_JWT_AUDIENCE=
SENA_AI_JWT_PUBLIC_KEY_PEM=

SENA_AI_AI_DB_URL=postgresql+asyncpg://sena_ai:sena_ai@ai-db:5432/sena_ai
SENA_AI_SHARED_DB_URL=postgresql+asyncpg://shared:shared@shared-db:5432/platform
SENA_AI_REDIS_URL=redis://redis:6379/0
SENA_AI_REDIS_LOCK_TTL_SECONDS=3600
SENA_AI_REDIS_SESSION_TTL_SECONDS=86400

SENA_AI_AWS_REGION=ap-southeast-2
SENA_AI_BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20240620-v1:0
SENA_AI_BEDROCK_MAX_TOKENS=1200
SENA_AI_BEDROCK_TEMPERATURE=0.2

SENA_AI_LIVEKIT_API_KEY=replace_me
SENA_AI_LIVEKIT_API_SECRET=replace_me
SENA_AI_LIVEKIT_URL=wss://replace-me-livekit

SENA_AI_SNS_CASE_NOTE_TOPIC_ARN=arn:aws:sns:ap-southeast-2:111111111111:case-note-events

SENA_AI_RATE_LIMIT_START_PER_MINUTE=30
SENA_AI_RATE_LIMIT_TURN_PER_MINUTE=120
SENA_AI_MAX_CONCURRENT_SESSIONS_PER_USER=5
SENA_AI_PROVIDER_TIMEOUT_SECONDS=1.2
SENA_AI_PROVIDER_MAX_RETRIES=2
```

## SECTION 8 — Test Suite

### FILE: /sena-ai/services/voice/tests/conftest.py
```
import os
import pytest
from fastapi.testclient import TestClient
from voice.main import create_app

os.environ.setdefault("SENA_AI_AI_DB_URL", "sqlite+aiosqlite:///./test_ai.db")
os.environ.setdefault("SENA_AI_SHARED_DB_URL", "sqlite+aiosqlite:///./test_shared.db")
os.environ.setdefault("SENA_AI_REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("SENA_AI_LIVEKIT_API_KEY", "devkey")
os.environ.setdefault("SENA_AI_LIVEKIT_API_SECRET", "devsecret")
os.environ.setdefault("SENA_AI_LIVEKIT_URL", "wss://livekit.local")
os.environ.setdefault("SENA_AI_SNS_CASE_NOTE_TOPIC_ARN", "arn:aws:sns:ap-southeast-2:111111111111:case-note-events")

@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)

@pytest.fixture
def dev_headers():
    return {
        "X-Tenant-ID": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "X-User-ID": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "X-User-Role": "support_worker",
        "X-Staff-ID": "cccccccc-cccc-cccc-cccc-cccccccccccc",
    }

@pytest.fixture
def manager_headers():
    return {
        "X-Tenant-ID": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "X-User-ID": "dddddddd-dddd-dddd-dddd-dddddddddddd",
        "X-User-Role": "manager",
        "X-Staff-ID": "dddddddd-dddd-dddd-dddd-dddddddddddd",
    }
```

### FILE: /sena-ai/services/voice/tests/test_session_start.py
```
def test_start_session_success(client, dev_headers):
    payload = {
        "objective": "CASE_NOTE",
        "participant_id": "11111111-1111-1111-1111-111111111111",
        "staff_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
        "shift_id": "22222222-2222-2222-2222-222222222222",
        "language": "en-AU",
        "metadata": {},
    }
    resp = client.post("/v1/voice/session", json=payload, headers=dev_headers)
    assert resp.status_code in (201, 503, 500)

def test_start_session_missing_auth_headers(client):
    payload = {
        "objective": "CASE_NOTE",
        "participant_id": "11111111-1111-1111-1111-111111111111",
        "staff_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
        "shift_id": "22222222-2222-2222-2222-222222222222",
    }
    resp = client.post("/v1/voice/session", json=payload)
    assert resp.status_code == 401

def test_start_session_invalid_objective(client, dev_headers):
    payload = {
        "objective": "ONBOARDING",
        "participant_id": "11111111-1111-1111-1111-111111111111",
        "staff_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
        "shift_id": "22222222-2222-2222-2222-222222222222",
    }
    resp = client.post("/v1/voice/session", json=payload, headers=dev_headers)
    assert resp.status_code == 422
```

### FILE: /sena-ai/services/voice/tests/test_turn_processing.py
```
def test_turn_validation_error_empty_transcript(client, dev_headers):
    payload = {
        "session_id": "33333333-3333-3333-3333-333333333333",
        "transcript": "",
        "transcript_confidence": 0.91,
        "audio_duration_ms": 5000,
        "sequence_number": 1,
        "timestamp": "2026-04-07T10:00:00Z",
    }
    resp = client.post("/v1/voice/session/turn", json=payload, headers=dev_headers)
    assert resp.status_code == 422

def test_turn_unknown_session(client, dev_headers):
    payload = {
        "session_id": "33333333-3333-3333-3333-333333333333",
        "transcript": "Participant was calm and engaged.",
        "transcript_confidence": 0.91,
        "audio_duration_ms": 5000,
        "sequence_number": 1,
        "timestamp": "2026-04-07T10:00:00Z",
    }
    resp = client.post("/v1/voice/session/turn", json=payload, headers=dev_headers)
    assert resp.status_code in (404, 503, 500)
```

### FILE: /sena-ai/services/voice/tests/test_session_end.py
```
def test_end_session_not_found(client, dev_headers):
    payload = {
        "session_id": "44444444-4444-4444-4444-444444444444",
        "ended_at": "2026-04-07T10:30:00Z",
        "client_timezone": "Australia/Sydney",
    }
    resp = client.post("/v1/voice/session/end", json=payload, headers=dev_headers)
    assert resp.status_code == 404
```

### FILE: /sena-ai/services/voice/tests/test_approval.py
```
def test_approval_requires_manager_role(client, dev_headers):
    payload = {
        "approval_item_id": "55555555-5555-5555-5555-555555555555",
        "decision": "APPROVED",
        "reviewer_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
        "review_notes": "ok",
    }
    resp = client.post("/v1/approval/decision", json=payload, headers=dev_headers)
    assert resp.status_code == 403

def test_reject_requires_reason(client, manager_headers):
    payload = {
        "approval_item_id": "55555555-5555-5555-5555-555555555555",
        "decision": "REJECTED",
        "reviewer_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
        "review_notes": "",
    }
    resp = client.post("/v1/approval/decision", json=payload, headers=manager_headers)
    assert resp.status_code == 422
```

### FILE: /sena-ai/services/voice/tests/test_health.py
```
def test_health_live(client):
    resp = client.get("/health/live")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "alive"

def test_health_ready(client):
    resp = client.get("/health/ready")
    assert resp.status_code in (200, 503, 500)
```

## SECTION 9 — CI/CD Pipeline

### FILE: /sena-ai/.github/workflows/voice-service-ci-cd.yml
```
name: voice-service-ci-cd

on:
  push:
    branches: ["**"]
  pull_request:
    branches: ["main"]

jobs:
  test-build:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: sena-ai
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: |
          python -m pip install -U pip
          pip install -e services/voice[dev]

      - name: Lint
        run: ruff check services/voice/src services/voice/tests

      - name: Unit and integration tests
        env:
          SENA_AI_AI_DB_URL: ${{ secrets.SENA_AI_AI_DB_URL }}
          SENA_AI_SHARED_DB_URL: ${{ secrets.SENA_AI_SHARED_DB_URL }}
          SENA_AI_REDIS_URL: ${{ secrets.SENA_AI_REDIS_URL }}
          SENA_AI_LIVEKIT_API_KEY: ${{ secrets.SENA_AI_LIVEKIT_API_KEY }}
          SENA_AI_LIVEKIT_API_SECRET: ${{ secrets.SENA_AI_LIVEKIT_API_SECRET }}
          SENA_AI_LIVEKIT_URL: ${{ secrets.SENA_AI_LIVEKIT_URL }}
          SENA_AI_SNS_CASE_NOTE_TOPIC_ARN: ${{ secrets.SENA_AI_SNS_CASE_NOTE_TOPIC_ARN }}
        run: pytest -q services/voice/tests

      - name: Build Docker image
        run: docker build -f services/voice/Dockerfile -t sena-voice:${{ github.sha }} .

      - name: Login ECR
        if: github.event_name == 'push'
        uses: aws-actions/amazon-ecr-login@v2

      - name: Push image
        if: github.event_name == 'push'
        run: |
          docker tag sena-voice:${{ github.sha }} ${{ secrets.AWS_ECR_VOICE_REPO }}:${{ github.sha }}
          docker push ${{ secrets.AWS_ECR_VOICE_REPO }}:${{ github.sha }}

  deploy-staging:
    needs: test-build
    if: github.event_name == 'push'
    runs-on: ubuntu-latest
    steps:
      - name: Configure AWS creds
        uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-region: ap-southeast-2
          role-to-assume: ${{ secrets.AWS_DEPLOY_ROLE_ARN }}

      - name: Deploy to staging ECS
        run: |
          aws ecs update-service \
            --cluster ${{ secrets.STAGING_ECS_CLUSTER }} \
            --service ${{ secrets.STAGING_ECS_SERVICE_VOICE }} \
            --force-new-deployment

      - name: Health check staging
        run: |
          curl -f ${{ secrets.STAGING_VOICE_BASE_URL }}/health/ready

  deploy-production:
    needs: deploy-staging
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    runs-on: ubuntu-latest
    steps:
      - name: Configure AWS creds
        uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-region: ap-southeast-2
          role-to-assume: ${{ secrets.AWS_DEPLOY_ROLE_ARN }}

      - name: Deploy to production ECS
        run: |
          aws ecs update-service \
            --cluster ${{ secrets.PROD_ECS_CLUSTER }} \
            --service ${{ secrets.PROD_ECS_SERVICE_VOICE }} \
            --force-new-deployment

      - name: Health check production
        run: |
          curl -f ${{ secrets.PROD_VOICE_BASE_URL }}/health/ready

      - name: Rollback on failed health check
        if: failure()
        run: |
          aws ecs update-service \
            --cluster ${{ secrets.PROD_ECS_CLUSTER }} \
            --service ${{ secrets.PROD_ECS_SERVICE_VOICE }} \
            --task-definition ${{ secrets.PROD_PREVIOUS_TASK_DEFINITION }}
```

## SECTION 10 — Local Development Setup

1. Prerequisites
- Python 3.12.7
- Docker Engine 27.3+
- Docker Compose v2.29+
- AWS CLI 2.17+
- Make optional 4.4+

2. Clone and configure
- Clone repo and move into sena-ai folder.
- Ensure services/voice files from this guide are present.

3. Configure environment
- Copy .env.example to .env in sena-ai root.
- Fill values:
  - DB URLs for local compose services.
  - Redis URL redis://redis:6379/0.
  - LiveKit key and secret.
  - AWS region and SNS topic ARN.
  - In development keep AUTH_MODE as dev_header.

4. Start locally
- Command:
  docker compose up --build sena-voice redis ai-db shared-db

5. Verify running
- URL:
  http://localhost:8082/health/live
- Expected:
  {"status":"alive","service":"sena-voice","version":"0.1.0"}

6. Run tests
- Command:
  pip install -e services/voice[dev]
  pytest -q services/voice/tests

7. Manual endpoint checks
- Start session
  curl -X POST http://localhost:8082/v1/voice/session \
    -H "Content-Type: application/json" \
    -H "X-Tenant-ID: aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa" \
    -H "X-User-ID: bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb" \
    -H "X-User-Role: support_worker" \
    -H "X-Staff-ID: cccccccc-cccc-cccc-cccc-cccccccccccc" \
    -d '{"objective":"CASE_NOTE","participant_id":"11111111-1111-1111-1111-111111111111","staff_id":"cccccccc-cccc-cccc-cccc-cccccccccccc","shift_id":"22222222-2222-2222-2222-222222222222","language":"en-AU","metadata":{}}'

- Process turn
  curl -X POST http://localhost:8082/v1/voice/session/turn \
    -H "Content-Type: application/json" \
    -H "X-Tenant-ID: aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa" \
    -H "X-User-ID: bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb" \
    -H "X-User-Role: support_worker" \
    -d '{"session_id":"<SESSION_ID>","transcript":"Participant was calm and cooperative during dinner support.","transcript_confidence":0.92,"audio_duration_ms":4200,"sequence_number":1,"timestamp":"2026-04-07T10:00:00Z"}'

- End session
  curl -X POST http://localhost:8082/v1/voice/session/end \
    -H "Content-Type: application/json" \
    -H "X-Tenant-ID: aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa" \
    -H "X-User-ID: bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb" \
    -H "X-User-Role: support_worker" \
    -d '{"session_id":"<SESSION_ID>","ended_at":"2026-04-07T10:20:00Z","client_timezone":"Australia/Sydney"}'

- Approval decision
  curl -X POST http://localhost:8082/v1/approval/decision \
    -H "Content-Type: application/json" \
    -H "X-Tenant-ID: aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa" \
    -H "X-User-ID: dddddddd-dddd-dddd-dddd-dddddddddddd" \
    -H "X-User-Role: manager" \
    -d '{"approval_item_id":"<APPROVAL_ITEM_ID>","decision":"APPROVED","reviewer_id":"dddddddd-dddd-dddd-dddd-dddddddddddd","review_notes":"Approved"}'

8. Common errors and fixes
- Error: 401 Missing tenant or user headers
  - Fix: add X-Tenant-ID, X-User-ID, X-User-Role in dev mode.
- Error: 409 Active session exists
  - Fix: end old session or wait lock TTL expiry, then retry.
- Error: 503 AI provider unavailable
  - Fix: verify AWS credentials, region, Bedrock model access.
- Error: DB connection refused
  - Fix: verify docker compose services ai-db and shared-db are healthy and URLs match.
- Error: SNS publish failed
  - Fix: check topic ARN and IAM permissions sns:Publish in current credentials.

## SECTION 11 — API Documentation

### FILE: /sena-ai/services/voice/openapi/voice_flow_b_openapi.yaml
```
openapi: 3.0.3
info:
  title: SENA Voice Service Flow B API
  version: 0.1.0
servers:
  - url: https://ai.sena.example
security:
  - bearerAuth: []
paths:
  /health/live:
    get:
      summary: Liveness
      security: []
      responses:
        "200":
          description: Alive
          content:
            application/json:
              schema:
                type: object
                properties:
                  status: { type: string, example: alive }
                  service: { type: string, example: sena-voice }
                  version: { type: string, example: 0.1.0 }

  /health/ready:
    get:
      summary: Readiness
      security: []
      responses:
        "200":
          description: Ready or degraded
          content:
            application/json:
              schema:
                type: object
                properties:
                  status: { type: string, example: healthy }
                  checks:
                    type: object
                    additionalProperties:
                      type: string

  /v1/voice/session:
    post:
      summary: Start CASE_NOTE session
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: "#/components/schemas/StartSessionRequest"
      responses:
        "201":
          description: Session created
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/StartSessionResponse"
        "401": { $ref: "#/components/responses/Unauthorized" }
        "409":
          description: Active session exists
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/ErrorResponse"

  /v1/voice/session/turn:
    post:
      summary: Process dictation turn
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: "#/components/schemas/TurnRequest"
      responses:
        "200":
          description: Turn processed
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/TurnResponse"
        "404": { $ref: "#/components/responses/NotFound" }
        "503": { $ref: "#/components/responses/ProviderUnavailable" }

  /v1/voice/session/end:
    post:
      summary: End session and compile draft
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: "#/components/schemas/EndSessionRequest"
      responses:
        "200":
          description: Draft queued for approval
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/EndSessionResponse"
        "404": { $ref: "#/components/responses/NotFound" }
        "409":
          description: Session already ended
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/ErrorResponse"

  /v1/voice/session/{session_id}:
    get:
      summary: Session status
      parameters:
        - in: path
          name: session_id
          required: true
          schema:
            type: string
            format: uuid
      responses:
        "200":
          description: Session status
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/SessionStatusResponse"
        "404": { $ref: "#/components/responses/NotFound" }

  /v1/approval/decision:
    post:
      summary: Manager approval decision
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: "#/components/schemas/ApprovalDecisionRequest"
      responses:
        "200":
          description: Decision recorded
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/ApprovalDecisionResponse"
        "403":
          description: Forbidden role
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/ErrorResponse"
        "404": { $ref: "#/components/responses/NotFound" }

components:
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      bearerFormat: JWT
  responses:
    Unauthorized:
      description: Unauthorized
      content:
        application/json:
          schema:
            $ref: "#/components/schemas/ErrorResponse"
    NotFound:
      description: Not found
      content:
        application/json:
          schema:
            $ref: "#/components/schemas/ErrorResponse"
    ProviderUnavailable:
      description: Provider unavailable
      content:
        application/json:
          schema:
            $ref: "#/components/schemas/ErrorResponse"

  schemas:
    StartSessionRequest:
      type: object
      required: [objective, participant_id, staff_id, shift_id]
      properties:
        objective: { type: string, enum: [CASE_NOTE] }
        participant_id: { type: string, format: uuid }
        staff_id: { type: string, format: uuid }
        shift_id: { type: string, format: uuid }
        language: { type: string, example: en-AU }
        metadata: { type: object }

    StartSessionResponse:
      type: object
      properties:
        session_id: { type: string, format: uuid }
        status: { type: string, example: ACTIVE }
        objective: { type: string, example: CASE_NOTE }
        lock_acquired: { type: boolean, example: true }
        livekit:
          type: object
          properties:
            room_name: { type: string }
            token: { type: string }
            url: { type: string }

    TurnRequest:
      type: object
      required: [session_id, transcript, transcript_confidence, audio_duration_ms, sequence_number, timestamp]
      properties:
        session_id: { type: string, format: uuid }
        transcript: { type: string }
        transcript_confidence: { type: number, minimum: 0, maximum: 1 }
        audio_duration_ms: { type: integer, minimum: 1 }
        sequence_number: { type: integer, minimum: 1 }
        timestamp: { type: string, format: date-time }

    TurnResponse:
      type: object
      properties:
        session_id: { type: string, format: uuid }
        sequence_number: { type: integer }
        agent_reply: { type: string }
        draft_preview: { type: string }
        completeness_score: { type: number }
        missing_topics:
          type: array
          items: { type: string }
        model: { type: string }
        latency_ms: { type: integer }

    EndSessionRequest:
      type: object
      required: [session_id, ended_at]
      properties:
        session_id: { type: string, format: uuid }
        ended_at: { type: string, format: date-time }
        client_timezone: { type: string, example: Australia/Sydney }

    EndSessionResponse:
      type: object
      properties:
        session_id: { type: string, format: uuid }
        draft_id: { type: string, format: uuid }
        approval_item_id: { type: string, format: uuid }
        event_id: { type: string, format: uuid }
        status: { type: string, example: PENDING_APPROVAL }
        case_note: { type: object }

    SessionStatusResponse:
      type: object
      properties:
        session_id: { type: string, format: uuid }
        status: { type: string }
        objective: { type: string }
        turn_count: { type: integer }
        completeness_score: { type: number }
        missing_topics:
          type: array
          items: { type: string }

    ApprovalDecisionRequest:
      type: object
      required: [approval_item_id, decision, reviewer_id]
      properties:
        approval_item_id: { type: string, format: uuid }
        decision: { type: string, enum: [APPROVED, REJECTED] }
        reviewer_id: { type: string, format: uuid }
        review_notes: { type: string }

    ApprovalDecisionResponse:
      type: object
      properties:
        approval_item_id: { type: string, format: uuid }
        decision: { type: string }
        status: { type: string }
        shared_case_note_id: { type: string, format: uuid, nullable: true }
        delivered_at: { type: string, format: date-time, nullable: true }

    ErrorResponse:
      type: object
      properties:
        error: { type: string }
        details:
          type: array
          items: { type: string }
        retry_after: { type: integer, nullable: true }
        fallback_used: { type: boolean, nullable: true }
        retryable: { type: boolean, nullable: true }
```

## SECTION 12 — Integration Guide for Other Teams

Base URL and versioning
- Base URL: https://ai.sena.example
- Versioned paths: /v1/...

Authentication
- Production: Bearer JWT signed RS256 by main backend auth issuer.
- Required claims: sub, tenant_id, role, optional staff_id.
- Development fallback: X-Tenant-ID, X-User-ID, X-User-Role, X-Staff-ID headers.

Available endpoints and minimal usage
- POST /v1/voice/session
  - Use when worker taps Start Dictation.
  - Returns session_id plus livekit token.

- POST /v1/voice/session/turn
  - Send one transcribed turn.
  - Receive AI follow-up prompt and completeness updates.

- POST /v1/voice/session/end
  - End dictation and trigger draft, approval, and risk event pipeline.

- GET /v1/voice/session/{session_id}
  - Poll status for UI progress.

- POST /v1/approval/decision
  - Manager review action from admin interface.

Streaming handling
- Flow B in this release is non-streaming turn responses over REST.
- Audio itself remains real-time via LiveKit WebRTC.

Rate limits and 429 handling
- Start endpoint: 30 per minute per tenant.
- Turn endpoint: 120 per minute per session scope.
- On 429, use retry_after seconds before retry.
- Client should exponential-backoff with jitter.

Issue reporting and new feature requests
- Raise issue in backend repo with tag ai-voice-flow-b.
- Include request_id, tenant_id, session_id, timestamp, endpoint, and payload shape.
- For model or prompt changes, include 3 sample transcripts and expected outputs.

## SECTION 13 — Definition of Done

- [ ] AI service starts locally with a single command
- [ ] All unit tests pass with no mocks missing
- [ ] All integration tests pass
- [ ] Every endpoint returns correct status codes for all cases
- [ ] Streaming works correctly end to end (if applicable)
- [ ] CI pipeline passes on a new branch
- [ ] Docker image builds without errors
- [ ] Service deploys to staging and health check passes
- [ ] OpenAPI spec is accessible at /docs
- [ ] .env.example contains every required variable
- [ ] No API keys or secrets hardcoded anywhere in the codebase
- [ ] README contains full setup and usage instructions
- [ ] Integration guide has been shared with the main backend team

Natural next step options
1. I can now apply this plan directly into your workspace as real files under services/voice and wire it to the existing shared package.
2. I can first generate the database migration SQL for AI DB and shared DB compatibility checks.
3. I can produce a reduced first-commit slice only for session start plus turn endpoints if you want incremental rollout.