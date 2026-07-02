# SENA Infrastructure Architecture

How each SENA service uses the shared infrastructure: **ai-db**, **shared-db**, **redis**.
All facts below are verified against `docker-compose.deploy.yml` and service source (2026-07-02).

---

## Overview

| Component | Image | Container | Port | Consumers |
|-----------|-------|-----------|------|-----------|
| **ai-db** | `pgvector/pgvector:pg16` | `sena-ai-db-internal` | 5432 | voice, case_review |
| **shared-db** | `postgres:16-alpine` | `sena-shared-db-internal` | 5433 | **voice only** |
| **redis** | `redis:7.4-alpine` | `sena-redis-internal` | 6979 | voice (db0), onboarding (db0), case_review (db1) |

**Not using any of the three**: `doc_service` uses **DynamoDB + S3 + Bedrock Knowledge Base** (see [doc_service](#doc_service--dynamodb--s3--bedrock-kb) below). All the pure-LLM services (staff, policy_proc, casenote_monthly, ai-communication-log, ai-text-extraction, shift-summary, ai_chatbot) hold no state in these stores.

Connection strings from `docker-compose.deploy.yml`:
```yaml
# voice
REDIS_URL:      redis://redis-internal:6979/0
AI_DB_URL:      postgresql+asyncpg://sena_ai:sena_ai@ai-db-internal:5432/sena_ai
SHARED_DB_URL:  postgresql+asyncpg://shared:shared@shared-db-internal:5433/platform
# onboarding
SENA_AI_REDIS_URL: redis://redis-internal:6979/0
# case_review
SENA_AI_AI_DB_URL:          postgresql+asyncpg://sena_ai:sena_ai@ai-db-internal:5432/sena_ai
SENA_AI_RP_DATABASE_URL:    postgresql+asyncpg://sena_ai:sena_ai@ai-db-internal:5432/sena_ai
SENA_AI_CASE_REVIEW_REDIS_URL: redis://redis-internal:6979/1
```

---

## ai-db (PostgreSQL + pgvector)

- **Image**: `pgvector/pgvector:pg16` · **Container**: `sena-ai-db-internal` · **Port**: 5432
- **Credentials**: user `sena_ai`, password `sena_ai`, database `sena_ai`
- **Schema**: created via SQLAlchemy `create_all()` from each service's `models/db.py`
- **Note**: deployed schema drifts from models (create_all, not alembic) — fix with idempotent `ALTER`, not migrations.
- **Consumers**: **voice** and **case_review** only. (doc_service does **not** use ai-db.)

### voice → ai-db

Models: [voice/models/db.py](voice/models/db.py). Repository: [voice/repositories/voice_repo.py](voice/repositories/voice_repo.py).

| Table (class) | Purpose |
|---------------|---------|
| `voice_sessions` (`VoiceSession`) | Session lifecycle: tenant/participant/staff/shift, status, section_coverage, missing_topics, draft_preview, turn_count |
| `dictation_turns` (`DictationTurn`) | Per-turn transcript rows (sequence_number, transcript) |
| `personal_details_drafts` (`PersonalDetailsDraft`) | Extracted personal-details draft (Gemini text path) |
| `ai_case_note_drafts` (`CaseNoteDraft`) | Generated case-note draft (draft_json, status) |
| `approval_queue` (`ApprovalQueueItem`) | Approval workflow: PENDING → REVIEWED → DELIVERED / REJECTED |
| `outbox` (`OutboxEvent`) | Transactional outbox for async event publishing |

Repository methods actually present: `create_voice_session`, `get_session_by_id`, `update_session_progress`, `update_session_fields`, `mark_session_completed`, `add_turn`, `create_case_note_draft`, `create_approval_item`, `insert_outbox`, `mark_outbox_published`, `get_approval_item`, `get_case_note_draft`, `mark_approval_rejected`, `mark_approval_delivered`, `mark_draft_status`, `create_personal_details_draft`, `mark_draft_delivered`.

### case_review → ai-db

Models: [case_review/models/db.py](case_review/models/db.py). Repository: [case_review/repositories/review_repo.py](case_review/repositories/review_repo.py).
Reads `SENA_AI_RP_DATABASE_URL`, falling back to `SENA_AI_AI_DB_URL` (both point at ai-db in compose).

| Table (class) | Purpose |
|---------------|---------|
| `cr_rolling_summary` (`RollingSummary`) | Rolling case-note summary per participant |
| `cr_review_session` (`ReviewSession`) | Review session state |
| `cr_incident_draft` (`IncidentDraft`) | Generated incident draft, confirm flow |
| `cr_review_audit_log` (`ReviewAuditLog`) | Audit trail of review actions |
| `cr_submission_record` (`SubmissionRecord`) | Submission records |
| `rp_ndis_policy_chunks` (`NDISPolicyChunk`) | RAG corpus: `embedding HALFVEC(1024)` (pgvector cosine) **+** `search_vector TSVECTOR` (BM25); hybrid results merged via RRF |
| `behaviour_support_plans` (`BehaviourSupportPlan`) | Behaviour support plan records |
| `rp_case_note_runs` (`CaseNoteRun`) | Case-note pipeline run records |

Repository methods present: `get_rolling_summary`, `upsert_rolling_summary`, `get_review_session`, `create_review_session`, `update_review_session`, `create_incident_draft`, `get_incident_draft`, `confirm_incident_draft`, `append_audit`, `list_audit`.

> **Embeddings live in `rp_ndis_policy_chunks`** (a `HALFVEC(1024)` column), not a separate embeddings table. Vector cosine search runs alongside a `TSVECTOR` BM25 keyword search; the two result sets are merged with Reciprocal Rank Fusion.

---

## shared-db (PostgreSQL)

- **Image**: `postgres:16-alpine` · **Container**: `sena-shared-db-internal` · **Port**: 5433 (runs `postgres -p 5433`)
- **Credentials**: user `shared`, password `shared`, database `platform`
- **Consumer**: **voice only.** Compose comment: *"The only consumer is voice's SHARED_DB_URL (also :5433)."*
- The distinct port (5433 vs ai-db's 5432) keeps the two Postgres instances unambiguous.

### voice → shared-db (write path only)

Voice **writes** approved case notes into the platform's `case_notes` table; it never reads shared-db.
Implemented in [voice/services/approval_service.py](voice/services/approval_service.py) `ApprovalService.decide()`:

- On **APPROVED**: `INSERT INTO case_notes (id, tenant_id, participant_id, staff_id, shift_id, content_json, ...) ... ON CONFLICT (id) DO UPDATE`, copying the finalized `ai_case_note_drafts` payload (which lives in ai-db) into shared-db.
- On **REJECTED**: only the ai-db draft/approval rows are updated; nothing is written to shared-db.

Everything else (drafting, turns, approval-queue state) stays in ai-db. shared-db is purely the publish sink so the wider platform can read finished case notes.

---

## redis

- **Image**: `redis:7.4-alpine` · **Container**: `sena-redis-internal` · **Port**: 6979 · `--appendonly yes`
- **One instance**, split by logical database number:

| DB | Consumer(s) | Client / layer | Env var |
|----|-------------|----------------|---------|
| **db=0** | **voice** and **onboarding** (shared instance, disjoint key prefixes) | voice: `RedisService`; onboarding: `FormStateRepo` (own fork) | `REDIS_URL` (voice), `SENA_AI_REDIS_URL` (onboarding) |
| **db=1** | **case_review** | `FormStateRepo` (shared engine, `key_prefix="sena:case_review"`) | `SENA_AI_CASE_REVIEW_REDIS_URL` |

case_review deliberately uses a **separate logical DB** (db=1) so its keys never collide with the voice/onboarding namespace on db=0.

### voice (db=0) — `RedisService`

Layer: [voice/services/redis_service.py](voice/services/redis_service.py). Uses pipelines to batch writes into one round-trip.

| Key pattern | Purpose | TTL |
|-------------|---------|-----|
| `participant_session:{tenant_id}:{participant_id}` | Exclusive per-participant session lock (`SET nx`) | `redis_lock_ttl_seconds` |
| `voice_session_state:{session_id}` | Live session field state (JSON) | `redis_session_ttl_seconds` |
| `sentiment_trend:{session_id}` | Cached sentiment from last turn | 30s |
| `engagement_summary:{session_id}` | Cached engagement level + progress | 60s |
| `rate_limit:{scope}` | Rate-limit counter (`INCR` + `EXPIRE`) | 60s |

### onboarding (db=0) — `FormStateRepo` (own fork)

Layer: [onboarding/voice/state_repo.py](onboarding/voice/state_repo.py). Scope prefix `sena:onboarding[:{tenant_id}]`. This is onboarding's own fork of the voice engine — it persists form state to Redis (there is no in-memory backend).

| Key template | Purpose | TTL |
|--------------|---------|-----|
| `{scope}:session:{sid}` | Form state (JSON) | per-session `ttl_sec` |
| `{scope}:session:{sid}:schema` | Step schema | per-session `ttl_sec` |
| `{scope}:session:{sid}:bootstrap` | Bootstrap data | per-session `ttl_sec` |
| `{scope}:session:{sid}:transcript` | Turn transcript | per-session |
| `{scope}:ws_lock:{sid}` | WebSocket session lock | — |
| `{scope}:resumption:{handle}` | Resumption handle → session | TTL |
| `{scope}:session:{sid}:last_frame:camera` / `:screen` | Last camera / screen frame | — |
| `{scope}:errors:{sid}` | Client-reported validation errors (telemetry) | 7 days |

Cross-screen context: [onboarding/repositories/user_context_repo.py](onboarding/repositories/user_context_repo.py) stores per-step summaries as Redis hash fields `step:{step_number}` under a participant bucket key.

### case_review (db=1) — shared `FormStateRepo`

Layer: [case_review/api/deps.py](case_review/api/deps.py) builds `FormStateRepo(voice_redis_client, key_prefix="sena:case_review", tenant_id=<auth>)` per voice session — this backs case_review's **voice case-note dictation** feature (Gemini Live). Same key templates as onboarding above, but under the `sena:case_review` scope.
Additionally, [case_review/api/voice_routes.py](case_review/api/voice_routes.py) uses `rate_limit:voice_casenote:{tenant_id}` for per-tenant dictation rate limiting.

---

## doc_service — DynamoDB + S3 + Bedrock KB

**doc_service uses none of ai-db / shared-db / redis.** It is a document-ingestion gateway for the Bedrock Knowledge Base. Config: [doc_service/config.py](doc_service/config.py).

| Store | What / where | Used for |
|-------|--------------|----------|
| **DynamoDB** | table `sena-doc-registry` (GSI `org_id-index`) via [doc_service/registry.py](doc_service/registry.py) | Per-document registry: `doc_id`, `org_id`, `filename`, `bucket`, `status` (INGESTING/…), job IDs, failure reasons |
| **S3** | bucket `sena-policy-docs` (prefixes `sena/misty/orgs/`, `sena/misty/md/orgs/`) | Uploaded source docs + converted markdown |
| **Bedrock Knowledge Base** | `KB_ID`, `DS_ID` | RAG ingestion / sync; ingestion status polled (`POLL_INTERVAL_SECONDS`, `POLL_MAX_ATTEMPTS`) |

Pipeline: [doc_service/pipeline.py](doc_service/pipeline.py) (`run_upload`, `run_delete`, `poll_and_update`). Registry ops: `registry_create`, `registry_update`, `registry_get`, `registry_list_by_org`.

---

## Consumer Matrix (verified)

| Service | ai-db (5432) | shared-db (5433) | redis (6979) | Other |
|---------|:---:|:---:|:---:|-------|
| **voice** | ✅ full (sessions, drafts, approval) | ✅ write-only (`case_notes`) | ✅ db0 (`RedisService`) | — |
| **case_review** | ✅ full (reviews, RAG chunks, RP) | — | ✅ db1 (`FormStateRepo`) | — |
| **onboarding** | — | — | ✅ db0 (`FormStateRepo` fork) | — |
| **doc_service** | — | — | — | DynamoDB, S3, Bedrock KB |
| staff / policy_proc / casenote_monthly / ai-communication-log / ai-text-extraction / shift-summary / ai_chatbot | — | — | — | LLM only (stateless) |

---

## Connection Pooling (verified)

Async SQLAlchemy engines, from [voice/api/deps.py](voice/api/deps.py):
```python
ai_engine     = create_async_engine(AI_DB_URL,     pool_pre_ping=True, pool_size=10, max_overflow=20)
shared_engine = create_async_engine(SHARED_DB_URL, pool_pre_ping=True, pool_size=10, max_overflow=20)
redis_client  = redis_from_url(REDIS_URL, decode_responses=True)
```
Redis clients are created lazily (`from_url` opens no socket until first command), so importing a module / running the REST test suite does not require Redis to be up.

---

## Related Documentation

- [services/README.md](README.md) — models, Langfuse tags, service index
- [services/VOICE_ARCHITECTURE.md](VOICE_ARCHITECTURE.md) — voice engine internals (shared vs onboarding fork)
- Memory: `sena_compose_file` (use `docker-compose.deploy.yml`), `sena_db_schema_drift` (schema-drift fixes), `sena_port_policy` (only nginx publishes host ports)
