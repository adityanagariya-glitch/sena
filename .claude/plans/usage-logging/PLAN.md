# Usage Logging System — PLAN

**Status:** draft · awaiting user sign-off before task-breaker
**Author:** sena-planner via main (2026-05-26)
**Scope:** `services/voice/`, `services/onboarding/`, `services/case_review/`, `shared/sena_common/`, `migrations/`
**Replaces:** the engineering-estimate doc at `.claude/plans/usage-logging/TOKEN_ESTIMATES_FOR_CLIENT.md` with measured per-org data after ~4 weeks of operation

---

## 1. Goal

Capture per-LLM-call usage data (tokens, audio-seconds, latency, success) across all 8 AI features, write per-session totals to Postgres `usage_events` (billing-hot) and per-turn detail to CloudWatch Logs (forensic-cold), so the client can move from estimates to measured tier pricing.

---

## 2. Architectural overview

```
                   AI critical path  (NEVER blocked by logger)
                   ──────────────────────────────────────────►
+----------------+        +-----------------+        +----------------+
|  voice service |        | onboarding svc  |        | case_review    |
|  (Bedrock)     |        | (Gemini Live)   |        | (Gemini Flash) |
+-------+--------+        +--------+--------+        +-------+--------+
        │ wraps invoke_model       │ wraps server_content     │ wraps generate_content
        ▼                          ▼                          ▼
+──────────────────────────────────────────────────────────────+
│      sena_common.usage_logger.UsageSession (async ctx)       │
│   record_turn() ── append-only counters; fire-and-forget     │
│   __aenter__: INSERT id, tenant, started_at                  │
│   __aexit__:  UPSERT totals + ended_at                       │
+──────┬───────────────────────────────────────────────┬───────+
       │                                               │
       │ async asyncio.create_task                     │ batch put_log_events
       ▼                                               ▼
+──────────────────────+              +────────────────────────────+
│ Postgres ai-db       │              │ CloudWatch Logs            │
│ usage_events         │              │ /sena/usage-events         │
│ (1 row per session)  │              │ (1 event per LLM turn)     │
│ → billing rollups    │              │ → Athena forensic queries  │
+──────────────────────+              +────────────────────────────+
        │                                               │
        ▼                                               ▼
   nightly rollup                              CloudWatch → S3 export
   /v1/usage/by-org                            Athena DDL for ad-hoc
   /v1/usage/by-feature                        per-turn analysis
```

**Invariants:**
- AI critical path NEVER awaits the logger. `asyncio.create_task` fan-out only.
- Postgres write failure → log + drop (CloudWatch still captures detail).
- CloudWatch write failure → log + drop (Postgres still captures totals).
- Feature flag `SENA_AI_USAGE_LOGGING_ENABLED=false` short-circuits the whole logger to a no-op.

---

## 3. Postgres schema — `usage_events` table

ORM (lives in `shared/sena_common/models/usage_event.py` — co-located with logger):

```python
# Pseudo-spec; final code by sena-implementer
from sena_common.db import Base, TenantMixin, TimestampMixin  # existing primitives
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, JSON,
    Enum as SQLEnum, Index,
)
import enum, uuid

class UsageFeature(str, enum.Enum):
    voice_onboarding             = "voice_onboarding"
    case_note_drafting           = "case_note_drafting"
    case_note_summary            = "case_note_summary"
    incident_report_analysis     = "incident_report_analysis"
    ai_chat                      = "ai_chat"                  # reserved (#5)
    psr_summary                  = "psr_summary"
    monthly_report               = "monthly_report"
    staff_doc_extraction         = "staff_doc_extraction"     # reserved (#8)

class UsageEvent(Base, TenantMixin, TimestampMixin):
    __tablename__ = "usage_events"
    id              = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # tenant_id      ← from TenantMixin (NOT NULL, indexed)
    user_id         = Column(String(64), nullable=False, index=True)
    feature         = Column(SQLEnum(UsageFeature, name="usage_feature"), nullable=False, index=True)
    model           = Column(String(80), nullable=False)
    session_id      = Column(String(64), nullable=False, unique=True)   # idempotent UPSERT key
    started_at      = Column(DateTime(timezone=True), nullable=False)
    ended_at        = Column(DateTime(timezone=True), nullable=True)
    prompt_tokens   = Column(Integer, nullable=False, default=0)
    response_tokens = Column(Integer, nullable=False, default=0)
    cached_tokens   = Column(Integer, nullable=False, default=0)        # Gemini context-cache hit
    audio_seconds_in  = Column(Float, nullable=False, default=0.0)
    audio_seconds_out = Column(Float, nullable=False, default=0.0)
    tool_call_count = Column(Integer, nullable=False, default=0)
    success         = Column(Boolean, nullable=False, default=False)    # flips True on clean __aexit__
    failure_reason  = Column(String(200), nullable=True)
    extras          = Column(JSON, nullable=False, default=dict)        # 'metadata' is reserved on Base

    __table_args__ = (
        Index("ix_usage_tenant_started", "tenant_id", "started_at"),
        Index("ix_usage_feature_started", "feature", "started_at"),
        Index("ix_usage_tenant_feature_started", "tenant_id", "feature", "started_at"),
    )
```

**Naming note:** column is `extras` (not `metadata`). SQLAlchemy reserves `metadata` on the `Base` class. Same workaround the existing `cr_rolling_summary.metadata_json` uses.

**RLS:**

```sql
ALTER TABLE usage_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY usage_events_tenant_isolation ON usage_events
    USING (tenant_id::text = current_setting('app.current_tenant', true));
```

**WARNING:** `.claude/rules/database.md` says `app.current_tenant_id`. The actual RLS variable used by the case_review migrations is **`app.current_tenant`** (verified at `sena-ai/services/case_review/migrations/versions/0001_create_case_review_tables.py:160`). The rule file is stale. Add a follow-up entry. We use `app.current_tenant` for consistency with prod.

---

## 4. CloudWatch per-turn event shape

**Log group:** `/sena/usage-events` (one group, all services tag themselves via `service` field).
**Retention:** 365 days hot in CloudWatch, then S3 export for 7-year NDIS APP 11 trail.
**Region:** `ap-southeast-2` (Sydney) — data residency.

```jsonc
{
  "ts": "2026-05-26T10:14:32.105Z",
  "service": "onboarding",
  "tenant_id": "tenant_abc123",
  "user_id": "user_xyz",
  "feature": "voice_onboarding",
  "session_id": "sess_a1b2c3",
  "turn_id": 7,
  "model": "gemini-3.1-flash-live-preview",
  "prompt_tokens_delta": 540,
  "response_tokens_delta": 320,
  "cached_tokens_delta": 0,
  "audio_seconds_in_delta": 2.1,
  "audio_seconds_out_delta": 1.4,
  "tool_name": "update_field",
  "latency_ms": 380,
  "success": true,
  "failure_reason": null
}
```

**PII guardrail:** NEVER `prompt_text`, `response_text`, `field_value`. Counters and identifiers only. Type signature on `record_turn` enforces this — no string fields beyond `tool_name` (enum), `failure_reason` (enum-shaped).

**Athena DDL skeleton:**

```sql
CREATE EXTERNAL TABLE sena_usage_events (
    ts string, service string, tenant_id string, user_id string,
    feature string, session_id string, turn_id int, model string,
    prompt_tokens_delta int, response_tokens_delta int, cached_tokens_delta int,
    audio_seconds_in_delta double, audio_seconds_out_delta double,
    tool_name string, latency_ms int, success boolean, failure_reason string
)
PARTITIONED BY (year string, month string, day string)
STORED AS JSON
LOCATION 's3://sena-usage-events-archive-ap-southeast-2/raw/';
```

---

## 5. `sena_common.usage_logger` API

```python
# shared/src/sena_common/usage_logger.py — public surface

class UsageSession:
    """Async context manager for a single AI call lifecycle.
    INSERT on __aenter__; UPSERT totals on __aexit__.
    record_turn() is sync, counter-only, fire-and-forget queues."""

    async def __aenter__(self) -> "UsageSession": ...
    async def __aexit__(self, exc_type, exc, tb) -> None: ...

    def record_turn(
        self,
        *,
        prompt_tokens: int = 0,
        response_tokens: int = 0,
        cached_tokens: int = 0,
        audio_seconds_in: float = 0.0,
        audio_seconds_out: float = 0.0,
        tool_name: str | None = None,        # enum-shaped only
        latency_ms: int | None = None,
    ) -> None: ...
    # Type signature deliberately excludes prompt_text, response_text, field_value, etc.

    def mark_failure(self, reason: str) -> None: ...   # short enum-shaped reason only


# Public entry point — async ctx
def session(
    *,
    tenant_id: str,
    user_id: str,
    feature: UsageFeature,
    session_id: str,
    model: str,
    extras: dict[str, Any] | None = None,
) -> UsageSession: ...


# Sync adapter for boto3 (voice service / Bedrock)
class SyncUsageSession:
    """Routes record_turn / lifecycle to the async logger via
    asyncio.run_coroutine_threadsafe to a background loop started in
    voice/main.py lifespan."""
    def __enter__(self): ...
    def __exit__(self, *_): ...
    def record_turn(self, ...): ...    # mirror of async record_turn


def session_sync(...) -> SyncUsageSession: ...
```

**Cumulative-vs-delta handling for Gemini Live:** `server_content.usage_metadata` is CUMULATIVE per session, not per-turn. Logger tracks last-seen-value internally and emits the delta to CloudWatch on each turn. The Postgres totals row uses the final cumulative value. See Open Question §10.4 for the edge case (disconnect mid-turn → loss of partial deltas).

### 5b. Onboarding's new Postgres dependency

Onboarding is Redis-only today. Adding:

- New env var `SENA_AI_AI_DB_URL` (same value voice + case_review use).
- New `services/onboarding/src/onboarding/api/deps.py::get_ai_db_session` — `AsyncSession` factory using `sena_common.db.init_engine` + `get_session`.
- pyproject.toml: add `sqlalchemy[asyncio]>=2.0`, `asyncpg>=0.30` (already pinned versions in voice + case_review — match them).
- Connection-pool size 5 (matches voice). Pool is lazy — no connection at startup if logging is disabled.
- **No Alembic for onboarding.** Schema migrations live in `migrations/` and are owned by case_review. Onboarding READS the table only via the shared ORM model.

---

## 6. Subtask DAG (12 subtasks)

```yaml
plan_id: usage-logging
subtasks:

  - id: S1
    title: "Alembic migration: create usage_events table + usage_feature ENUM + RLS"
    file_scope: ["sena-ai/migrations/versions/NNNN_create_usage_events.py"]
    depends_on: []
    contract:
      adds: ["usage_events table", "usage_feature postgres enum (8 values)", "RLS policy on app.current_tenant"]
    security_tier: 3   # cross-tenant breach if RLS wrong
    test_requirement: "Migration applies clean to fresh ai-db; downgrade rolls back cleanly; INSERT under wrong tenant fails RLS."
    acceptance:
      - "Migration up + down both succeed locally and in staging."
      - "psql under tenant A cannot SELECT rows tenant_id='B'."

  - id: S2
    title: "ORM model: sena_common/models/usage_event.py + UsageFeature enum"
    file_scope: ["sena-ai/shared/src/sena_common/models/usage_event.py"]
    depends_on: [S1]
    contract:
      adds: ["class UsageEvent(Base, TenantMixin, TimestampMixin)", "class UsageFeature(str, Enum)"]
    security_tier: 2
    test_requirement: "tests/test_usage_event_model.py — instantiate, dump, round-trip via fakeredis-equivalent (or pytest-postgresql)."
    acceptance:
      - "mypy strict passes."
      - "All 8 UsageFeature values defined including reserved (#5 ai_chat, #8 staff_doc_extraction)."

  - id: S3
    title: "usage_logger.UsageSession + SyncUsageSession + session() / session_sync() entry points"
    file_scope: ["sena-ai/shared/src/sena_common/usage_logger.py"]
    depends_on: [S2]
    contract:
      adds: ["class UsageSession", "class SyncUsageSession", "def session()", "def session_sync()"]
    security_tier: 3   # PII guardrail at type signature
    test_requirement: "tests/test_usage_logger.py — INSERT-on-enter, UPSERT-on-exit, record_turn accumulates, fire-and-forget doesn't block, no-op when flag disabled, sync adapter round-trips via run_coroutine_threadsafe."
    acceptance:
      - "100 concurrent UsageSession contexts under load — no Postgres pool exhaustion."
      - "record_turn(prompt_text=...) is a STATIC TYPE ERROR — verified by mypy (gates S9 too)."

  - id: S4
    title: "Wire into voice/Bedrock"
    file_scope: ["sena-ai/services/voice/src/voice/services/bedrock_service.py", "sena-ai/services/voice/src/voice/services/dictation_service.py"]
    depends_on: [S3]
    contract:
      modifies: ["BedrockService.invoke_model wrapped in session_sync(); usage extracted from response['usage']"]
    security_tier: 2
    test_requirement: "tests/test_bedrock_usage.py — fake bedrock client returns {usage: {input_tokens, output_tokens}}; usage_events row written with matching counters."
    acceptance:
      - "Critical-path latency unchanged (record_turn is sync counter increment only)."
      - "Failure path (Bedrock 500) → mark_failure called; row written with success=False."

  - id: S5
    title: "Wire into onboarding/Gemini Live"
    file_scope: ["sena-ai/services/onboarding/src/onboarding/services/gemini_live.py", "sena-ai/services/onboarding/src/onboarding/api/deps.py", "sena-ai/services/onboarding/pyproject.toml", "sena-ai/services/onboarding/src/onboarding/core/settings.py"]
    depends_on: [S3]
    contract:
      modifies: ["gemini_live.run() opens UsageSession; g2b receive loop extracts server_content.usage_metadata delta per turn"]
      adds: ["onboarding pyproject sqlalchemy[asyncio]+asyncpg deps", "settings.ai_db_url", "deps.get_ai_db_session factory"]
    security_tier: 3   # tenant_id MUST flow from assert_session_owner, never from request body
    test_requirement: "tests/test_gemini_live_usage.py — fake genai client emits cumulative usage_metadata; per-turn delta computed correctly; final UPSERT row totals match cumulative."
    acceptance:
      - "Onboarding boots clean with USAGE_LOGGING_ENABLED=false (no Postgres connection attempted)."
      - "WS disconnect mid-turn → cumulative-since-last-flush captured (verified in S11 sweeper)."

  - id: S6
    title: "Wire into case_review/Gemini Flash classifier + summarizer"
    file_scope: ["sena-ai/services/case_review/src/case_review/services/llm/classifier.py", "sena-ai/services/case_review/src/case_review/services/llm/summarizer.py"]
    depends_on: [S3]
    contract:
      modifies: ["classifier + summarizer wrap generate_content in UsageSession; capture response.usage_metadata"]
    security_tier: 2
    test_requirement: "tests/test_case_review_usage.py — for each feature (case_note_summary, incident_report_analysis, psr_summary, monthly_report) — usage_events row written with correct feature enum value."
    acceptance:
      - "All 4 case_review features distinguishable in usage_events.feature column."

  - id: S7
    title: "CloudWatch fan-out — boto3 batch put_log_events with backoff"
    file_scope: ["sena-ai/shared/src/sena_common/usage_logger.py (extends S3)"]
    depends_on: [S3]
    contract:
      adds: ["UsageSession._flush_cloudwatch background task; 10-event batching with 1-second flush timer"]
    security_tier: 2
    test_requirement: "tests/test_usage_logger_cloudwatch.py — moto-based CloudWatch fake; verify batches; failure does NOT propagate to caller."
    acceptance:
      - "CloudWatch unreachable → Postgres write still happens; service does NOT crash."
      - "Log group /sena/usage-events created on first write (idempotent)."

  - id: S8
    title: "Billing endpoints: /v1/usage/by-org and /v1/usage/by-feature"
    file_scope: ["sena-ai/services/case_review/src/case_review/api/routes.py", "sena-ai/services/case_review/src/case_review/services/usage_query.py (new)"]
    depends_on: [S6]
    contract:
      adds: ["GET /v1/usage/by-org?since=...&until=... → per-org totals", "GET /v1/usage/by-feature?tenant_id=...&since=...&until=..."]
    security_tier: 3   # admin-only auth, cross-tenant query restrictions
    test_requirement: "tests/test_usage_endpoints.py — admin reads any tenant; non-admin only own tenant; date-range validation."
    acceptance:
      - "RLS still enforced (case_review uses set_config to scope queries)."
      - "Endpoint returns <500ms on 1M-row table with proper indexes."

  - id: S9
    title: "PII guardrail property test"
    file_scope: ["sena-ai/shared/tests/test_usage_logger_pii.py"]
    depends_on: [S3]
    contract:
      adds: ["property-based test that record_turn accepts no string field longer than 80 chars (enum-shaped only)"]
    security_tier: 3
    test_requirement: "hypothesis-based: 1000 random strings; if any > 80 chars and not in allowed enums, test fails."
    acceptance:
      - "Test FAILS if anyone adds a record_turn(prompt_text=...) kwarg later — gates the API contract."

  - id: S10
    title: "Feature flag wiring + per-service settings"
    file_scope: ["sena-ai/services/*/src/*/core/settings.py", "sena-ai/shared/src/sena_common/usage_logger.py"]
    depends_on: [S3]
    contract:
      adds: ["settings.usage_logging_enabled: bool = False (each service)"]
    security_tier: 1
    test_requirement: "tests/test_feature_flag.py per service — flag off → session() returns no-op stub; no Postgres connection."
    acceptance:
      - "Flag off → zero performance overhead vs main."

  - id: S11
    title: "Abandoned-session sweeper — close ended_at IS NULL rows older than 24h"
    file_scope: ["sena-ai/services/case_review/src/case_review/jobs/usage_sweeper.py", "sena-ai/services/case_review/src/case_review/main.py (wire APScheduler)"]
    depends_on: [S2]
    contract:
      adds: ["nightly job: UPDATE usage_events SET ended_at=started_at+'24 hours' WHERE ended_at IS NULL AND started_at < NOW()-'24 hours'"]
    security_tier: 1
    test_requirement: "tests/test_usage_sweeper.py — abandoned rows older than 24h get ended_at; younger rows untouched."
    acceptance:
      - "Job runs idempotent; sets failure_reason='abandoned' on swept rows."

  - id: S12
    title: "Integration test: 8-feature end-to-end with feature flag toggled"
    file_scope: ["sena-ai/services/case_review/tests/test_usage_e2e.py"]
    depends_on: [S4, S5, S6, S7, S8, S10]
    contract:
      adds: ["e2e: fake LLM responses for each of 6 implemented features; verify usage_events row + CloudWatch event per turn"]
    security_tier: 2
    test_requirement: "Drive all 6 currently-built features; assert 6 rows in usage_events with correct feature enum + non-zero token counters."
    acceptance:
      - "Run under flag=True → 6 rows. Run under flag=False → 0 rows. No regression in feature endpoints."
```

**DAG edges:** `S1→S2 · S2→S3 · S3→{S4,S5,S6,S7,S9,S10} · S2→S11 · S6→S8 · {S4,S5,S6,S7,S8,S10}→S12`

**Critical path:** S1 → S2 → S3 → (S4 ∥ S5 ∥ S6) → S10 → S12.

---

## 7. Threat model (STRIDE)

| Threat | Cat | Surface | Mitigation | Residual |
|--------|-----|---------|------------|----------|
| Cross-tenant usage data leak (tenant A reads tenant B's rows) | I | usage_events SELECT path | RLS on `app.current_tenant`; query layer calls `SET LOCAL app.current_tenant = '<tenant>'` per request | None by construction |
| PII (NDIS field values, transcripts, prompts) lands in CloudWatch | I, R | record_turn signature | S9 property test enforces type signature has NO free-text columns beyond enum-shaped `tool_name` + `failure_reason` | Author can still add a wrong column later — but S9 catches it in CI |
| Tenant_id spoofing via request body | S | Every Wire-in site (S4/S5/S6) | `tenant_id` flows ONLY from auth context (`assert_session_owner` / `AuthContext`); plan brief mandates this | None — same pattern as existing tenant-scoped queries |
| Logger blocks AI critical path | A | `asyncio.create_task` fan-out | Postgres write is fire-and-forget; CloudWatch is batch-buffered with timer flush; both have failure→drop semantics | <0.1ms p99 added to AI critical path (counter increment only) |
| Postgres pool exhaustion under burst | D | Connection pool sizing | Pool size 5 per service; lazy connection (no startup cost when flag off); session ctx ensures release | If 100+ concurrent sessions per pod → graceful degradation: log-and-drop |
| CloudWatch quota exhaustion → silent data loss | D | put_log_events rate limit (5 TPS per stream) | Batching: 10 events per put; per-tenant log stream; retries with backoff | Forensic data is best-effort; Postgres totals are the authoritative billing record |
| Audit log forging (org disputes a bill) | R | usage_events table | `started_at` + `ended_at` server-set; immutable after `ended_at` written (no UPDATE except sweeper); CloudWatch trail is independent corroboration | Two-source agreement required for billing disputes |
| Athena queries leak data to wrong analyst | E | S3 bucket policy + Athena workgroup | Workgroup-level IAM with `aws:RequestedRegion=ap-southeast-2`; per-tenant query result encryption | None within the AWS account; out-of-account access requires audit |

---

## 8. NDIS compliance check

| Requirement | How preserved |
|-------------|---------------|
| Australian data residency (APP 8) | ai-db is in `australia-southeast1` (Postgres). CloudWatch + S3 archive in `ap-southeast-2` (Sydney). |
| 7-year retention for AI-decision audit (APP 11) | CloudWatch 365-day hot retention → automated S3 export → S3 lifecycle policy retains 7 years; Postgres totals retained indefinitely (small footprint). |
| No PII in logs | S9 property test + structural type signature on record_turn. |
| Tenant isolation | RLS on usage_events + tenant_id from auth context only. |
| Billing dispute resolution | Two independent records (Postgres totals + CloudWatch detail). |

---

## 9. Rollback plan

- **Flag:** `SENA_AI_USAGE_LOGGING_ENABLED` (`bool`, default **`false`**) — per service.
- **Effect when false:** `session()` / `session_sync()` return no-op stubs. No Postgres connection attempted. Zero overhead vs main.
- **Effect when true:** Full logging active.
- **Promotion criteria:** S12 e2e green in staging × 7 days; no Postgres pool warnings; CloudWatch quota under 30% per tenant; ai-db disk usage < 100MB growth per week (Tier 4 ≈ 50 rows/day → <100KB/year per tenant).
- **Hot rollback:** flip env var, restart pod (or send SIGHUP if reload supported). No Redis or DB cleanup needed — rows already written remain. New writes stop instantly.
- **Schema rollback:** S1 Alembic migration has a clean `downgrade()`. Table can be dropped without affecting other features.

---

## 10. Open questions

1. **AI Chat (feature #5) model choice.** Plan reserves `UsageFeature.ai_chat` enum slot. When that feature is built, which model? Plan assumes Gemini Flash; logger schema works for any.
2. **Staff Document Extraction (feature #8) — multimodal billing.** Gemini Flash multimodal bills image tokens differently. Logger captures `prompt_tokens` cumulative; the `extras` jsonb can store `image_tokens` separately. Confirm with billing team.
3. **Per-turn delta granularity on Gemini Live disconnect.** If WebSocket drops mid-turn, the cumulative `usage_metadata` from the last successful event is the floor; whatever happened in the lost turn is not captured. S11 sweeper closes the row with `failure_reason='abandoned'`. Confirm with product whether this is acceptable accuracy for billing.
4. **CloudWatch → S3 export pipeline ownership.** Who owns the Kinesis Firehose / subscription filter that lands CloudWatch into S3? Likely ops, not eng. Flag in handoff.
5. **`/v1/usage/*` endpoint auth model.** Admin role required? Per-org admin can read own tenant? Cross-tenant analytics only by SENA platform admin? Needs auth-policy sign-off before S8.
6. **Stale rule cleanup.** `.claude/rules/database.md` says RLS variable is `app.current_tenant_id`; actual prod variable per `case_review/migrations/.../0001_create_case_review_tables.py:160` is `app.current_tenant`. Add an issues-solved entry + fix the rule.
7. **Backfill estimates from Bedrock + Gemini cost-explorer data.** AWS Cost Explorer has historical Bedrock spend per project; Google Cloud billing API has Gemini spend. We can derive ~30 days of historical per-org data (allocated proportionally by session count from existing Redis transcripts) to give the client a head-start before the logger collects real data. Worth ~2 days of work — flag as P2.
