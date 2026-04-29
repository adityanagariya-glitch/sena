# Plan: Productionise the Restrictive Practices Detection Module

## Context

The `restrictive_practices` module is a working POC: a 7-step LangGraph pipeline (triage → RAG → evaluator → cross-check → audit) that detects NDIS regulated restrictive practices in support worker case notes. It produces correct AI verdicts end-to-end on synthetic data.

To deploy this to real Australian NDIS service providers, we must satisfy **legally binding** compliance constraints (multi-tenant isolation, human-in-the-loop, AU data residency, NDIS audit standards) and operational requirements (auth, retries, observability, idempotency, real document corpus, queue-based async, blue-green deploys).

**Confirmed decisions** (from clarifying Qs):
- Async API with queue (SQS + workers); platform receives results via signed webhook
- Module moves into `sena-ai/services/restrictive-practices/` as first-class service
- Vertex AI Gemini in `australia-southeast1` is **Phase 0 blocker** for AU residency

This plan does **not** include front-end / approval-queue UI (built by client team) or NDIS legal review (parallel workstream).

---

## Current State (POC)

**Location:** `C:\Users\Admin\Documents\SENA\restrictive_practices\` (standalone)

**What works:**
- 7-step pipeline, end-to-end verified on synthetic + Sarah/Liam test note
- 3 tables in single shared PG DB (`rp_ndis_policy_chunks`, `behaviour_support_plans`, `rp_case_note_runs`)
- HALFVEC(3072) Gemini embeddings + HNSW cosine index
- LangGraph with `_step` suffix node names; conditional triage gate
- FastAPI `POST /v1/restrictive-practices/evaluate` (sync)
- `models/db.py`, `pipeline/{triage,rag,evaluator,cross_check,graph}.py`, `api/routes.py`

**What's missing for production:**
- Auth, multi-tenancy, RLS, AU residency, real PDFs, retries, idempotency, async, observability, audit chain, approval workflow, CI/CD, deployment config, golden-set eval, rate limiting

---

## Target Architecture

```
                                                 ┌─ webhook signed (HMAC) ─┐
Platform Backend → POST /evaluate (sync 202)  →  │   SQS queue              │  →  Platform receives result
  + bearer JWT (tenant_id, role)                  └──────┬──────────────────┘
                                                          ↓
                                              ┌──────────────────────┐
                                              │ Worker pool (ECS)    │
                                              │ ┌─ LangGraph pipeline│
                                              │ │  triage_step       │ → Vertex AI (australia-southeast1)
                                              │ │  rag_step          │ → pgvector ai-db (RLS active)
                                              │ │  evaluator_step    │ → Vertex AI Pro
                                              │ │  cross_check_step  │ → SQL on BSP table
                                              │ └──────────────────  │
                                              └──────────────────────┘
                                                          ↓
                                              ┌──────────────────────┐
                                              │ rp_case_note_runs    │ (audit, hash-chained)
                                              │ rp_alert_decisions   │ (manager review)
                                              └──────────────────────┘
```

**Cloud:** AWS ECS in `ap-southeast-2` (matches voice service deploy).
**LLM:** Vertex AI Gemini in `australia-southeast1` (AU residency).
**Tenancy:** PostgreSQL Row-Level Security on every tenant-scoped table.
**Queue:** AWS SQS (one main queue + one DLQ).
**Cache:** Redis (existing `sena-redis` container) for embedding cache + rate limit token bucket.

---

## Phase 0 — Vertex AI + GCP Foundation (DAYS 1-2, BLOCKER)

**Why first:** Australian data residency is legally mandated. Every later phase produces audit data that must come from an AU-region LLM. Migrating later means every prod test before this is invalid for compliance.

### Scope
- Create GCP project, enable Vertex AI in `australia-southeast1`
- Service account + Workload Identity Federation for ECS task role (no static keys)
- Update `config.py` — populate `gcp_project`, `gcp_location=australia-southeast1`
- Verify `_make_client()` switches to `genai.Client(vertexai=True, ...)` automatically (already coded)
- Confirm Vertex AI quotas for `gemini-2.5-flash`, `gemini-2.5-pro`, `gemini-embedding-2`
- Set up GCP billing alerts (per-project daily cap)

### Files modified
- `restrictive_practices/.env.example` — Vertex AI block becomes primary
- `restrictive_practices/.env` — populate `SENA_AI_GCP_PROJECT` (dev value)
- No code changes — `embedder.py`, `triage.py`, `evaluator.py` already mode-switch via `settings.use_vertex_ai`

### Verification
1. Run `python scripts/test_pipeline.py` — verify 0 outbound calls to `generativelanguage.googleapis.com`, all to `australia-southeast1-aiplatform.googleapis.com`
2. GCP audit log shows requests in correct region
3. Confirm same verdict on Sarah/Liam test case (regression baseline)

---

## Phase 1 — Move into sena-ai Monorepo (WEEK 1)

**Why:** Stop duplicating infra. Adopt `sena-common`, Alembic migrations, Makefile, Docker compose, CI patterns. Become indistinguishable from voice/onboarding services.

### Scope
- Move source under `sena-ai/services/restrictive-practices/src/restrictive_practices/`
- Add `pyproject.toml` per-service (mirrors `services/voice/pyproject.toml`)
- Adopt `sena-common` for: structured logging, base SQLAlchemy models, Pydantic schema base classes, DB session helpers
- Replace `db/session.py::create_tables()` with Alembic migration: `migrations/versions/xxx_create_rp_tables.py`
- Add service to `sena-ai/docker-compose.yml` (port 8084)
- Add service Dockerfile (multi-stage, non-root)
- Add Makefile targets: `make rp-test`, `make rp-migrate`, `make rp-run`
- Add to `sena-ai/pyproject.toml` workspace `mypy_path` and `[tool.ruff.lint.isort]known-first-party`
- Pre-commit hook adoption (`.pre-commit-config.yaml` already exists at sena-ai root)

### Files to create
- `sena-ai/services/restrictive-practices/pyproject.toml` (model after `services/voice/pyproject.toml`)
- `sena-ai/services/restrictive-practices/Dockerfile` (model after voice Dockerfile)
- `sena-ai/services/restrictive-practices/src/restrictive_practices/main.py` (factory pattern: `create_app()`)
- `sena-ai/services/restrictive-practices/src/restrictive_practices/core/settings.py` (sectioned `RestrictivePracticesSettings`)
- `sena-ai/migrations/versions/<rev>_create_rp_tables.py` (DDL for 3 existing tables)

### Reuse from existing code
- `sena-ai/migrations/env.py` — Alembic async config (already runs against ai-db)
- `sena-ai/scripts/init_db.sql` — pgvector + uuid-ossp + `sena_app` non-superuser role
- `sena-ai/services/voice/src/voice/main.py` — `create_app()` factory pattern

### Verification
1. `cd sena-ai && pip install -e ".[dev]"` succeeds with new service in workspace
2. `make rp-migrate` creates 3 tables identical to current schema
3. `cd services/restrictive-practices && uvicorn src.restrictive_practices.main:create_app --factory --port 8084` starts cleanly
4. `pytest services/restrictive-practices/tests/` runs (even if empty)
5. `python scripts/test_pipeline.py` from new location produces same verdict as POC baseline

---

## Phase 2 — Auth + Multi-Tenant RLS (WEEK 2)

**Why:** CLAUDE.md mandates multi-tenant isolation (legally binding). RLS is the rigor level required for compliance data — denormalized filtering (voice service pattern) leaves a window for bugs to leak data across tenants.

### Scope

**Auth (mirror voice pattern):**
- Copy `sena-ai/services/voice/src/voice/services/auth_service.py::auth_context_dependency()` → `services/auth_service.py`
- Same dual-mode: `dev_header` (X-Tenant-ID, X-User-ID, X-User-Role) + `jwt` (RS256, claims)
- Returns frozen `AuthContext` injected via FastAPI `Depends()`
- Add `SENA_AI_AUTH_MODE`, `SENA_AI_JWT_PUBLIC_KEY` to settings

**RLS:**
- Add `tenant_id: UUID NOT NULL` column to `behaviour_support_plans` and `rp_case_note_runs`
- Add `tenant_id` to new tables coming in later phases (`rp_alert_decisions`, `rp_policy_documents`)
- **Do NOT** add `tenant_id` to `rp_ndis_policy_chunks` — NDIS policy is global reference data shared across all tenants
- Migration `xxx_add_tenant_id_and_rls.py`:
  - ALTER TABLE adds tenant_id with FK
  - ENABLE RLS on each table
  - CREATE POLICY using `current_setting('app.current_tenant')`
- Use `sena-ai/scripts/setup_rls.sql` as template

**Tenant context middleware:**
- New: `middleware/tenant.py` — sets `SET LOCAL app.current_tenant = '<uuid>'` on each session checkout (using `event.listen(engine, "checkout", ...)` or middleware that wraps each request)
- Update `db/session.py::get_db()` to require `auth_context` dependency and apply tenant binding before yielding session

**Pipeline updates:**
- Add `tenant_id` to `PipelineState` TypedDict
- Pass through every node
- Cross-check filters BSPs by `tenant_id` (RLS enforces this anyway, defense-in-depth)
- Audit row records `tenant_id`

### Files to create / modify
- new: `services/restrictive-practices/src/.../services/auth_service.py`
- new: `services/restrictive-practices/src/.../api/deps.py` (dual-engine pattern from voice)
- new: `services/restrictive-practices/src/.../middleware/tenant.py`
- new: `migrations/versions/<rev>_add_tenant_id_and_rls.py`
- modify: `models/db.py` — add tenant_id to BSP and CaseNoteRun
- modify: `pipeline/graph.py::PipelineState` — add `tenant_id`
- modify: `pipeline/cross_check.py` — explicit tenant filter

### Reuse
- `sena-ai/scripts/setup_rls.sql` (RLS policy template)
- `sena-ai/scripts/init_db.sql` (`sena_app` role created here is the one RLS targets)
- `sena-ai/services/voice/src/voice/services/auth_service.py:1-85` (auth pattern)

### Verification
1. Add `make check-rls` test target — submit case note as Tenant A, attempt to read it as Tenant B → blocked
2. Worker without `app.current_tenant` set → query fails (default-deny RLS)
3. JWT mode integration test — token without `tenant_id` claim → 401
4. `dev_header` mode — `X-Tenant-ID` missing → 401
5. Pipeline test — submitting with tenant A's worker should write audit row with tenant A; tenant B can't see it

---

## Phase 3 — Real NDIS Document Ingestion + Embedding Cache (WEEK 3)

**Why:** Sample data (10 chunks) produces noisy RAG. Real NDIS regulatory PDFs need versioning so retrieval is reproducible and auditable.

### Scope
- New table `rp_policy_documents` (id, source_uri, title, jurisdiction, version, effective_date, ingested_at, sha256)
- Add `document_version_id` FK to `rp_ndis_policy_chunks`
- `ingestion/pdf_processor.py` — extract text, chunk, deduplicate, version-tag
- `ingestion/embedder.py` — adopt batch endpoint, Redis cache by `sha256(text)` (24h TTL)
- `scripts/ingest_documents.py` — CLI that takes a directory of PDFs, ingests with version tracking
- `scripts/reembed.py` — re-embed when prompts/models change, blue-green swap (build new index, switch atomically)

### Files
- new: `models/db.py::PolicyDocument`
- new: `migrations/versions/<rev>_add_policy_documents.py`
- new: `ingestion/pdf_processor.py`
- modify: `ingestion/embedder.py` (cache, batch)
- modify: `ingestion/chunker.py` — accept document_version_id

### Verification
1. Ingest real NDIS Quality and Safeguards Commission "Restrictive Practices in NDIS" PDF
2. Confirm chunks tagged with version + sha256
3. Re-run pipeline — evaluator reasoning cites specific document/page
4. Re-ingest same PDF → 0 new rows (idempotent)
5. Bump version, re-ingest → both versions in table, only newest used in retrieval

---

## Phase 4 — Reliability, Idempotency, Async Queue (WEEKS 4-5)

**Why:** Sync 5-15s endpoint times out clients during incidents and can't absorb bursts. Compliance audit demands every submission processes exactly once.

### Scope

**Idempotency:**
- UNIQUE constraint on `rp_case_note_runs(case_note_id, tenant_id)`
- API endpoint: same `case_note_id` resubmitted → return existing result (200), don't re-run pipeline
- Worker: `INSERT ... ON CONFLICT DO NOTHING` on row creation, use existing run if found

**Async + Queue:**
- New endpoint design:
  - `POST /v1/restrictive-practices/evaluate` → 202 + `{job_id, case_note_id, status: "queued"}`
  - Body validated, message published to SQS
  - `GET /v1/restrictive-practices/result/{case_note_id}` → current status + result (when done)
  - Webhook fired to `rp_webhook_url` on completion (HMAC signed)
- New: `workers/pipeline_worker.py` — long-running ECS task, polls SQS, runs LangGraph, writes result, fires webhook
- One main queue + one DLQ; messages with > N retries land in DLQ
- LangGraph PostgresSaver checkpointer — pipeline survives worker restart mid-graph

**LLM resilience:**
- New: `services/llm_client.py` — wraps `genai.Client` with:
  - Exponential backoff retry (1s → 2s → 4s → 8s, max 4 attempts) on 429/500/503
  - Circuit breaker (open after 5 consecutive failures within 60s, half-open probe after 30s)
  - Per-call timeout (configurable, default triage=10s, evaluator=45s, embed=15s)
  - Cost/token tracking — every call logs usage with tenant_id and model

**Webhook delivery:**
- Copy `sena-ai/services/onboarding/src/onboarding/services/webhook.py` → `services/webhook_service.py`
- HMAC-SHA256 signature in `X-SENA-AI-Signature` header
- Exp backoff retry (3 attempts), failed deliveries → DLQ

**Rate limiting:**
- Redis token bucket per tenant (e.g., 100 evaluations/min default, override per tenant)
- Reject with 429 + `Retry-After` header

### Files
- new: `services/restrictive-practices/src/.../services/llm_client.py`
- new: `services/restrictive-practices/src/.../services/queue_publisher.py`
- new: `services/restrictive-practices/src/.../services/webhook_service.py`
- new: `services/restrictive-practices/src/.../middleware/rate_limit.py`
- new: `services/restrictive-practices/src/.../workers/pipeline_worker.py`
- new: `services/restrictive-practices/src/.../workers/__main__.py` (entry point for ECS task)
- modify: `pipeline/triage.py`, `evaluator.py`, `embedder.py` — replace direct genai.Client with `llm_client`
- modify: `pipeline/graph.py` — wire LangGraph PostgresSaver
- modify: `api/routes.py` — `/evaluate` returns 202 + job_id; new `/result/{case_note_id}` endpoint
- new: `migrations/versions/<rev>_add_idempotency_constraint.py`

### Reuse
- `sena-ai/services/onboarding/src/onboarding/services/webhook.py` — copy verbatim, adapt event names
- `sena-ai/services/voice/src/voice/services/bedrock_service.py` — retry pattern (linear, adapt to exp backoff)

### Verification
1. Submit same `case_note_id` 5x in parallel → 1 audit row, 5 identical 202 responses
2. Kill Vertex AI traffic mid-evaluation (toxiproxy) → circuit breaker opens, retries succeed when restored
3. 1000 concurrent submissions → all queued, all process, no DB lock contention
4. Worker dies mid-pipeline → restart, LangGraph resumes from last checkpoint, completes
5. Webhook receiver returns 500 → 3 retries with backoff → eventually DLQs
6. Tenant exceeds rate limit → 429 with Retry-After

---

## Phase 5 — Observability + PII Redaction (WEEK 6)

**Why:** Compliance ops demands traceable decisions. Every alert must be defensible: who triggered it, what model version, what document version, what reasoning. Case notes contain PII — logs must redact.

### Scope

**Logging:**
- Adopt `sena-common` structlog config
- Correlation ID middleware: generate `X-Request-ID` if absent, inject into log context
- Propagate request_id through LangGraph state so every step's log carries it
- PII redaction filter: regex masks for AU phone numbers, names (token list), Medicare numbers
- Never log full case note text — log first 80 chars + sha256

**Tracing:**
- OpenTelemetry FastAPI + asyncpg + httpx instrumentation
- Manual spans on each LangGraph node (4 spans per flagged note)
- Export to AWS X-Ray (matches voice service deploy region)

**Metrics (Prometheus):**
- `rp_triage_flag_rate` (counter)
- `rp_pipeline_latency_seconds{step}` (histogram, p50/p95/p99)
- `rp_alert_required_total{tenant}` (counter)
- `rp_llm_errors_total{model, error_class}` (counter)
- `rp_llm_tokens_total{model, tenant, kind="input|output"}` (counter — feeds cost dashboards)
- `rp_queue_depth` (gauge from worker)
- `rp_circuit_breaker_state{model}` (gauge)

**Alerts (Prometheus rules → Slack/Pager):**
- 5xx error rate > 1% over 10 min
- Queue depth > 1000 sustained 5 min
- Circuit breaker open > 2 min
- Daily cost > tenant budget (anomaly detection)
- 0 case notes processed in 1 hr (silent failure)

**Sentry:** unhandled exceptions, breadcrumbs include tenant_id (no PII)

### Files
- new: `core/logging.py` (structlog + correlation + PII redaction)
- new: `core/tracing.py` (OTel setup)
- new: `core/metrics.py` (Prometheus registry + custom metrics)
- new: `middleware/correlation.py`
- new: `infra/observability/dashboards/rp-operational.json` (Grafana)
- new: `infra/observability/dashboards/rp-compliance.json` (Grafana)
- new: `infra/observability/alerts/rp-alerts.yml` (Prometheus rules)

### Verification
1. Trigger error → Sentry captures with tenant context, no PII
2. End-to-end pipeline run → single trace in X-Ray spanning 4 nodes
3. Hit `/metrics` endpoint → all custom metrics present
4. Search logs by request_id → see full flow across services with no plaintext PII

---

## Phase 6 — Compliance, Audit Chain, Approval Workflow (WEEK 7)

**Why:** NDIS audit demands proof that the AI's verdict has not been altered. Human-in-the-loop is hard requirement (CLAUDE.md). Every alert must have a recorded human decision.

### Scope

**Tamper-evident audit:**
- Add columns to `rp_case_note_runs`: `prev_hash CHAR(64)`, `record_hash CHAR(64)`
- On insert: `record_hash = sha256(prev_hash || canonical_json(this_row))`
- Background validator job: walks chain nightly, alerts on first integrity break
- Genesis row hash hardcoded in config

**Approval workflow:**
- New table `rp_alert_decisions`: id, case_note_run_id, tenant_id, manager_id, decision (approved | rejected | escalated), notes, decided_at, ip_address
- New endpoint: `POST /v1/restrictive-practices/decision` (manager/admin role only)
- Decision creation appends to audit chain
- Webhook fires to platform on decision recorded

**Versioned prompts:**
- Move triage / evaluator prompts to `prompts/triage_v1.txt`, `prompts/evaluator_v1.txt`
- New table `rp_prompt_versions`: name, version, sha256, deployed_at, deprecated_at
- Audit row records `triage_prompt_sha256`, `evaluator_prompt_sha256`, `triage_model`, `evaluator_model`, `embedding_model`

**Right-to-deletion:**
- `DELETE /v1/restrictive-practices/case-notes/{id}` (admin role)
- Tombstones `rp_case_note_runs` row (sets `deleted_at`, nulls free-text fields)
- Hash chain remains valid because tombstone is itself appended (don't delete rows from a hash chain)

**Retention policy:**
- Per-tenant config `case_note_retention_days` (default 365)
- Daily cleanup job tombstones rows past retention

### Files
- new: `models/db.py::AlertDecision`, `PromptVersion`
- new: `migrations/versions/<rev>_add_audit_chain_and_decisions.py`
- new: `services/audit_chain.py` (hashing, validation)
- new: `prompts/triage_v1.txt`, `prompts/evaluator_v1.txt`
- new: `scripts/load_prompts.py` (sync filesystem prompts → DB on deploy)
- new: `scripts/verify_audit_chain.py` (cron)
- new: `scripts/retention_cleanup.py` (cron)
- new: `api/routes.py::/decision`, `:/case-notes/{id}` DELETE
- modify: `pipeline/graph.py::run_pipeline` — record prompt/model versions in audit row
- modify: `pipeline/triage.py`, `evaluator.py` — load prompts from filesystem (or DB)

### Verification
1. Manually mutate one row's `evaluator_output` field → audit chain validator detects tamper, fires alert
2. Submit alert → manager hits `/decision` with `approved` → row in `rp_alert_decisions` + new chain row
3. Update prompt → re-deploy → next audit row references new prompt sha256
4. DELETE on a case_note_id → row tombstoned, no real deletion, chain still valid
5. Retention cleanup runs → rows past N days tombstoned

---

## Phase 7 — Quality Loop + Golden Set Eval (WEEK 8)

**Why:** "We trust the LLM" is not a defensible position. We need measurable precision/recall on a labeled corpus to detect regressions when prompts or models change.

### Scope
- Build golden set: 50 case notes with expert (clinical advisor) labels for each of: `incident_detected`, `practice_category`, `policy_violation_risk`
  - 10 clean (negative)
  - 10 chemical, 10 seclusion, 10 physical, 5 mechanical, 5 environmental
- Eval runner: `scripts/run_eval.py`
  - Iterates golden set, runs pipeline, computes per-class precision/recall/F1, confusion matrix
  - Output goes to `evals/results/<timestamp>.json`
  - CI gate: deploy fails if F1 < 0.85 on any flagged category
- Prompt A/B framework: ship prompt v2, route 10% of traffic, compare quality + cost vs v1
- Drift monitor: nightly job samples 100 prod runs, computes distribution of categories vs baseline

### Files
- new: `evals/golden_set/<id>.json` × 50 (committed to repo)
- new: `evals/runner.py`
- new: `scripts/run_eval.py`
- new: `scripts/drift_check.py`
- new: `infra/observability/dashboards/rp-quality.json`
- modify: CI workflow — run eval on PRs that touch `prompts/` or `pipeline/`

### Verification
1. `python scripts/run_eval.py` produces report with F1 per class
2. Intentionally degrade triage prompt → eval F1 drops → CI gate fails the PR
3. Drift monitor detects synthetic shift (inject extra chemical-restraint cases) → alert fires

---

## Phase 8 — CI/CD + Production Deployment (WEEK 9)

**Why:** Manual deploys at this stakes level are unacceptable. Need automated tests, vulnerability scanning, blue/green, rollback drill.

### Scope

**CI:**
- Copy `.github/workflows/voice-service-ci-cd.yml` → `.github/workflows/restrictive-practices-ci-cd.yml`
- Pipeline: ruff → mypy → pytest → eval (if prompts changed) → docker build → trivy scan → ECR push
- Per-PR: lint + unit tests + RLS check + golden eval gate

**CD:**
- Staging deploy on merge to main → soak 2 hours → automated smoke test
- Manual approval gate → prod deploy
- Blue/green via ECS service with two task sets, traffic shift via ALB target weights
- Rollback button: revert ALB weights, re-pin previous task definition
- Drain in-flight requests on shutdown (60s grace), worker also drains queue

**Secrets:**
- AWS Secrets Manager: DB creds, Vertex AI service account JSON, JWT public key, webhook signing secret
- ECS task IAM role grants read; no secrets in env or git

**Health checks:**
- `GET /health/live` — process up, no deps
- `GET /health/ready` — pings ai-db, redis, SQS, Vertex AI (cached 10s), pgvector
- ALB uses `/health/ready`; ECS uses both

**Infra as code:**
- Terraform module: `infra/terraform/restrictive-practices/{ecs.tf, sqs.tf, iam.tf, alb.tf, secrets.tf}`
- Reuses existing VPC, subnets, ALB, ai-db, redis from voice service module

### Files
- new: `.github/workflows/restrictive-practices-ci-cd.yml`
- new: `infra/terraform/restrictive-practices/*.tf`
- modify: `Dockerfile` — multi-stage, distroless runtime, non-root, healthcheck
- new: `api/routes.py::/health/live`, `:/health/ready` (model after voice `api/routes.py:58-85`)

### Reuse
- `.github/workflows/voice-service-ci-cd.yml` (full template)
- `sena-ai/services/voice/src/voice/api/routes.py:58-85` (health checks)
- voice service Terraform module (if exists) for VPC/ALB/IAM patterns

### Verification
1. Open PR with bad code → CI blocks
2. Merge → auto-deploy to staging → smoke test passes
3. Manual approve → blue/green prod deploy → traffic shifts
4. Trigger rollback drill → previous task set serves traffic in < 60s
5. Confirm secrets fetched from Secrets Manager, none in env vars

---

## Cross-Phase Verification Gates (Production Readiness Checklist)

Before flipping the prod traffic switch, all of these must pass:

| Gate | How to verify |
|------|---------------|
| Tenant isolation | Two-tenant integration test; one cannot read other's data |
| Idempotency | Same case_note_id submitted 10x → 1 audit row |
| AU residency | tcpdump / GCP audit log shows only `australia-southeast1` traffic |
| LLM quality | Golden set F1 ≥ 0.85 across all 5 categories |
| Audit integrity | `verify_audit_chain.py` returns 0 errors over 10k rows |
| Approval workflow | Alert → decision recorded → webhook fires within 1s |
| Outage recovery | Vertex AI 503 for 5 min → circuit opens → queue grows → recovers cleanly |
| Webhook signing | Receiver verifies HMAC, rejects unsigned/wrong-sig |
| Rate limit | 200 RPS from one tenant → 429 after threshold |
| Compliance retention | DELETE on case note → tombstoned, chain valid |
| Observability | Trace one production request from API to webhook in X-Ray |
| Rollback drill | Bad deploy detected → traffic back on previous version in < 60s |
| Cost guard | Daily cost cap triggers → traffic throttled, page on-call |

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Cross-tenant data leak | Low | Critical | RLS + integration test gate in CI + `make check-rls` |
| Vertex AI quota exhaustion | Med | High | Per-tenant rate limit + circuit breaker + queue backpressure |
| Audit chain forged | Low | Critical | Hash chain + offsite hash backups + S3 Object Lock for tier 2 |
| Prompt regression breaks compliance | Med | High | Golden set CI gate; prompt version recorded in audit row |
| Vertex AI region outage | Low | High | Multi-region failover (`australia-southeast1` → `us-central1`) — but residency violation flag fires; tenant config decides whether to fail open or closed |
| LLM hallucinates wrong category | Med | Med | Cross-check + human approval required for all alerts |
| Webhook receiver compromised | Low | High | HMAC signing + receiver verifies + IP allowlist + rotate secret |
| NDIS rule change | Cert | Med | Versioned prompts + document version table + re-eval on each prompt update |
| Cost runaway from triage bug | Med | Med | Per-tenant daily budget cap + Prometheus cost alert |
| Worker pool stuck on bad msg | Med | Med | Visibility timeout + DLQ after N retries + on-call alert |

---

## Critical Files (Existing) Referenced by This Plan

These already exist and should be reused / copied — do not reimplement:

| File | Use |
|------|-----|
| `sena-ai/services/voice/src/voice/services/auth_service.py:1-85` | Auth dual-mode pattern |
| `sena-ai/services/onboarding/src/onboarding/services/webhook.py` | HMAC + exp backoff webhook |
| `sena-ai/scripts/setup_rls.sql` | RLS policy template |
| `sena-ai/scripts/init_db.sql` | `sena_app` non-superuser role for RLS |
| `sena-ai/migrations/env.py` | Async Alembic config |
| `sena-ai/services/voice/src/voice/api/routes.py:58-85` | Health check pattern |
| `sena-ai/services/voice/src/voice/main.py` | `create_app()` factory |
| `.github/workflows/voice-service-ci-cd.yml` | CI/CD template |
| `sena-ai/services/voice/src/voice/services/bedrock_service.py` | LLM retry pattern |
| `sena-ai/shared/src/sena_common/` | Shared library (logging, schemas, DB helpers) |
| `sena-ai/Makefile` | Targets template (`migrate`, `check-rls`, etc.) |
| `sena-ai/docker-compose.yml` | Add new service entry |
| `restrictive_practices/.claude/DATABASE_SCHEMA.md` | Current schema reference |

---

## Out of Scope (Explicitly Not in This Plan)

- Front-end UI for manager approval queue (built by client team — they consume our `/decision` endpoint and webhooks)
- NDIS legal review of system outputs (parallel workstream — clinical advisor signs off golden set labels)
- Voice service refactor to also use RLS (different scope — this plan scopes restrictive_practices only)
- Migration of existing voice service Bedrock → Vertex AI (separate decision)
- Multi-region active-active deployment (single region with documented failover path)
- Real-time streaming evaluations (POC sync API → async queue is the only mode delivered)

---

## Estimated Timeline

Sequential execution with 1 senior engineer:
- Phase 0: 2 days (blocker)
- Phase 1: 5 days
- Phase 2: 5 days
- Phase 3: 5 days
- Phase 4: 10 days
- Phase 5: 5 days
- Phase 6: 5 days
- Phase 7: 5 days
- Phase 8: 5 days

**Total: ~9 weeks** to production-ready, single contributor. Phases 5 & 7 partially parallelisable with Phase 4 (different surfaces). Realistic with one senior engineer + clinical advisor on call for Phase 7 labeling: **~7 calendar weeks**.

---

## Suggested Next Action

Start with Phase 0 immediately (Vertex AI setup) since it blocks all later compliance work. While GCP project is being provisioned (typically 1 day for org approval), begin Phase 1 monorepo migration in parallel — these don't conflict.
