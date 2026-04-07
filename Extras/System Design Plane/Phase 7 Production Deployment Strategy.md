# === PHASE 7: PRODUCTION DEPLOYMENT STRATEGY ===

## REALITY CHECK — THIS IS NOT A TYPICAL DEPLOYMENT

Before applying a textbook "dark launch → canary → full rollout" template, let's acknowledge what makes SENA's deployment fundamentally different:

1. **There is no "old system" to run alongside.** This is a greenfield AI backend. There's nothing to dark-launch against, no existing traffic to canary, no old system to keep as hot standby. The platform team (Nishant/Jill) is building their system in parallel — neither side has API contracts yet.

2. **The team is 2 people.** A 10-week phased rollout with 24/7 on-call during canary is impossible. The deployment strategy must be operationally realistic for a senior dev + team lead + intern.

3. **The deployment is modular.** OCR and RAG are completely independent. Voice, Case Notes, and Risk Flagging form a connected chain. Each module can be deployed and validated independently.

4. **Real data arrives ~end of March 2026.** Until then, everything runs against synthetic/test data. The "production" deployment is actually a staged progression: dev → staging with synthetic data → staging with real data → production.

The standard canary playbook doesn't fit. What follows is a **deployment strategy designed for SENA's actual constraints**.

---

## DEPLOYMENT ENVIRONMENTS — THREE STAGES

### Environment Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  DEVELOPMENT (Local)                                                  │
│                                                                       │
│  docker compose up                                                    │
│  ├── PostgreSQL 16 + pgvector (local container)                       │
│  ├── Redis (local container, added in Sprint 1)                       │
│  ├── OCR service (hot-reload, port 8001)                              │
│  ├── RAG service (hot-reload, port 8002)                              │
│  └── ... future services                                              │
│                                                                       │
│  Trigger: Every developer, every push to feature branch               │
│  Cost: $0                                                             │
└──────────────────────────────────────────────────────────────────────┘
         │
         │  CI passes → merge to main
         ▼
┌──────────────────────────────────────────────────────────────────────┐
│  STAGING (GCP — australia-southeast1)                                 │
│                                                                       │
│  Cloud Run (per-service) + Cloud SQL + Memorystore Redis              │
│  ├── Identical container images to production                         │
│  ├── Separate Cloud SQL instance (smaller tier)                       │
│  ├── Populated with synthetic + public NDIS test data                 │
│  ├── Test tenants: 3 orgs with 50+ seed records each                  │
│  ├── Vertex AI models accessible (same region)                        │
│  └── platform team can hit staging APIs for integration testing       │
│                                                                       │
│  Trigger: Every merge to main → auto-deploy                          │
│  Cost: ~$100-150/month (min Cloud SQL + Cloud Run cold starts)        │
└──────────────────────────────────────────────────────────────────────┘
         │
         │  Manual promotion (senior dev approval)
         ▼
┌──────────────────────────────────────────────────────────────────────┐
│  PRODUCTION (GCP — australia-southeast1)                              │
│                                                                       │
│  Cloud Run (per-service) + Cloud SQL (HA) + Memorystore Redis         │
│  ├── Cloud SQL HA (automatic failover, daily backups)                 │
│  ├── Memorystore Redis with TLS + AUTH                                │
│  ├── VPC-internal services (no public IPs except gateway)             │
│  ├── Cloud Armor WAF on gateway (DDoS + basic request filtering)      │
│  ├── GCP Secret Manager for all credentials                          │
│  ├── JWT auth (platform team's auth system validates tokens)          │
│  └── Real tenant data (when available)                                │
│                                                                       │
│  Trigger: Manual promotion from staging + go/no-go checklist          │
│  Cost: ~$400-600/month MVP, ~$730/month at 50 orgs (Phase 3 est.)    │
└──────────────────────────────────────────────────────────────────────┘
```

**Why Cloud Run (not GKE)?** The design doc (§A.2) leans Cloud Run for HTTP APIs. For a 2-person team, Cloud Run is correct:
- Zero cluster management (no node pools, no kubectl, no Helm charts)
- Per-request billing (no idle cost during low-traffic hours)
- Auto-scaling to zero (staging environment costs nearly nothing overnight)
- HTTPS + load balancing + TLS termination included
- Revision-based deployment with instant rollback

**Exception**: Voice service (LiveKit) cannot run on Cloud Run (needs persistent WebSocket connections, GPU for low-latency inference). Voice service runs on a single **GKE Autopilot** node pool or a **Compute Engine VM** with LiveKit installed. This is a Phase 2 deployment decision.

---

## DEPLOYMENT PIPELINE — CI/CD

### Pipeline Architecture

```
Developer pushes to branch
         │
         ▼
┌─────────────────────────┐
│  GitHub Actions / GitLab │
│  CI Workflow              │
│                           │
│  1. Lint (ruff)           │  ~15s
│  2. Type check (mypy)    │  ~30s
│  3. Unit tests (pytest)  │  ~60s
│  4. Build Docker images  │  ~120s
│  5. Tenant isolation     │  ~30s  ← THE critical gate
│     regression tests     │
│  6. Integration tests    │  ~120s (against ephemeral DB)
│                           │
│  TOTAL: ~6 minutes        │
└────────────┬──────────────┘
             │
     ┌───────┴───────┐
     │               │
  Feature          Main branch
  branch           (merge)
     │               │
     ▼               ▼
  Done         ┌─────────────────┐
  (PR only)    │ Auto-deploy to   │
               │ STAGING           │
               │                   │
               │ 1. Build & push   │  ~3 min
               │    to Artifact    │
               │    Registry       │
               │ 2. Deploy new     │
               │    Cloud Run      │
               │    revision       │
               │ 3. Run smoke      │  ~2 min
               │    tests against  │
               │    staging        │
               │ 4. Notify Slack   │
               └────────┬──────────┘
                        │
                        ▼
               ┌─────────────────┐
               │ Manual promote   │
               │ to PRODUCTION    │
               │                   │
               │ Trigger: senior   │
               │ dev runs          │
               │ `make promote`    │
               │                   │
               │ 1. Same image     │
               │    (immutable     │
               │    artifact)      │
               │ 2. Deploy new     │
               │    Cloud Run      │
               │    revision       │
               │ 3. Traffic split: │
               │    100% new       │
               │ 4. Monitor 30min  │
               │ 5. If OK → done   │
               │    If bad →       │
               │    rollback       │
               └───────────────────┘
```

### The Critical CI Gate: Tenant Isolation Regression Tests

Every deployment MUST pass the tenant isolation test suite. This is not optional, not skippable, not overridable. The test_tenant_isolation.py test must:

1. Create two test tenants (Tenant A, Tenant B)
2. Insert data as Tenant A
3. Query as Tenant B → assert zero results
4. Attempt to update Tenant A's data as Tenant B → assert rejection
5. Verify RLS is enabled and forced on ALL tenant-scoped tables
6. Verify that `get_session_no_tenant()` cannot read tenant-scoped data

**If this test fails, the deployment MUST NOT proceed.** No `--no-verify`, no manual override. This is a legal compliance gate.

### Why Not Canary / Traffic Splitting?

For SENA's specific situation, per-request traffic splitting (5% → 10% → 50% → 100%) adds complexity without benefit:

- **No existing system to compare against** — canary compares new vs. old. There's no old.
- **Very low initial traffic** — MVP is 5-10 orgs. 5% of 200 requests/day = 10 requests. Not enough to detect anything statistical.
- **Modular deployment** — OCR and RAG are independent. Deploying OCR doesn't affect RAG. The blast radius is already contained by architecture.
- **Cloud Run revision rollback is instant** — if the new revision has errors, rollback takes <30 seconds (`gcloud run services update-traffic --to-revisions=PREVIOUS=100`). This is faster than any canary ramp-down.

**Instead**: Deploy new revision at 100% traffic, monitor for 30 minutes, rollback if P1 alerts fire. This is the right strategy for a 2-person team with low traffic and independent services.

**When to add canary**: If/when daily volume exceeds 5K requests AND multiple teams are deploying simultaneously (>4 devs). Until then, revision-based instant rollback is sufficient.

---

## PRE-PRODUCTION VALIDATION — THE GO/NO-GO CHECKLIST

Before any service goes to production, it must pass this checklist. This is a **gate**, not a suggestion.

### Infrastructure Readiness

| # | Check | How to Verify | Status |
|---|---|---|---|
| I.1 | Cloud SQL instance provisioned in `australia-southeast1` | GCP Console / Terraform output | ❓ Blocked on cloud account |
| I.2 | Cloud SQL HA enabled (automatic failover) | GCP Console | ❓ |
| I.3 | Cloud SQL daily backups configured (7-day retention) | GCP Console | ❓ |
| I.4 | `sena_app` database user created (restricted, no schema changes) | `init_db.sql` runs successfully | ❓ |
| I.5 | RLS policies applied to ALL tenant-scoped tables | `setup_rls.sql` runs successfully + regression test | ❓ |
| I.6 | GCP Secret Manager has all production secrets | Secret list via `gcloud` | ❓ |
| I.7 | Artifact Registry configured for container images | `gcloud artifacts repositories list` | ❓ |
| I.8 | Cloud Run service deployed (each module) | `gcloud run services list` | ❓ |
| I.9 | VPC connector configured (Cloud Run → Cloud SQL) | GCP Console | ❓ |
| I.10 | Domain + TLS certificate configured | `gcloud` / DNS provider | ❓ |

### Security Readiness

| # | Check | How to Verify | Status |
|---|---|---|---|
| S.1 | `JWTTenantResolver` implemented and tested | Unit tests + integration test with platform team's JWT | ❓ Blocked on client auth |
| S.2 | No plaintext secrets in code, config, or container images | `grep -r "password\|secret\|key"` on repo + image inspection | ❓ |
| S.3 | RBAC middleware (`require_role`) applied to admin-only endpoints | Route-level test: support worker cannot call admin endpoints | ❓ |
| S.4 | Health check endpoints exempt from auth | Unauthenticated `GET /health/ready` returns 200 | ❓ |
| S.5 | No debug endpoints in production (`docs_url=None`) | `create_app()` checks `environment != "development"` | ✅ Already in code |
| S.6 | Redis TLS + AUTH enabled | Connection test with TLS | ❓ |
| S.7 | Cloud Armor WAF rules on gateway endpoint | GCP Console | ❓ |

### Application Readiness (Per Module)

| # | Check | How to Verify | Status |
|---|---|---|---|
| A.1 | All tests pass (unit + integration) | `make test` in CI — 100% green | ❓ |
| A.2 | Tenant isolation regression passes against production DB schema | Dedicated CI job against Cloud SQL staging | ❓ |
| A.3 | Health check returns `healthy` with all dependencies connected | `curl /health/ready` on staging | ❓ |
| A.4 | Structured logging producing valid JSON lines | `gcloud logging read` shows parseable entries | ❓ |
| A.5 | OpenTelemetry traces appearing in Cloud Trace | Cloud Trace UI shows spans for test requests | ❓ |
| A.6 | Audit log entries written for every processed request | Query `audit_log` table after test requests | ❓ |
| A.7 | Error responses don't leak internal details | Send malformed request, verify generic 500 response | ✅ Already in error handler |
| A.8 | Circuit breaker tested for external service failure | Kill Vertex AI connection, verify fallback behavior | ❓ |

### Performance Readiness

| # | Check | How to Verify | Status |
|---|---|---|---|
| P.1 | Module passes load test at 2× expected peak traffic | `locust` or `k6` against staging | ❓ |
| P.2 | P95 latency within SLA (per Phase 3 targets) | Load test results | ❓ |
| P.3 | Database connection pool behaves under load | Monitor pool stats during load test | ❓ |
| P.4 | No memory leaks during sustained load (30 min test) | Container memory usage flat, not climbing | ❓ |
| P.5 | Cold start time < 10s (Cloud Run first request) | Deploy new revision, time first request | ❓ |

### Compliance Readiness

| # | Check | How to Verify | Status |
|---|---|---|---|
| C.1 | All data stored in `australia-southeast1` only | `gcloud` resource listing — no resources in other regions | ❓ |
| C.2 | Vertex AI model endpoint in AU region confirmed | Vertex AI Console | ❓ |
| C.3 | Audit trail captures every AI I/O | Run 10 test requests, verify 10 audit entries | ❓ |
| C.4 | PII redaction active in operational logs | Search Cloud Logging for Medicare numbers — should find none | ❓ |
| C.5 | Participant data deletion function tested | Delete test participant, verify cascade across all tables + vectors | ❓ Designed in Phase 5, not built |

---

## ROLLOUT TIMELINE — PHASED BY MODULE

This is not a single big-bang deployment. Each module goes through its own **deploy → validate → stabilize** cycle.

### Phase 0 → Phase 1 Transition (Current → Sprint 1-2)

```
WEEK 1-2: Foundation Validation (Sprint 0 completion)
├── docker compose up works end-to-end
├── Tenant isolation tests pass against real Postgres
├── CI pipeline running (GitHub Actions)
├── Git repo initialized, team onboarded
├── Client meeting completed → cloud provider confirmed
└── GO/NO-GO: Can the team build modules on this scaffold?

WEEK 3: Cloud Account Setup (Track C)
├── GCP project created with billing
├── Cloud SQL instance provisioned (AU region)
├── Artifact Registry configured
├── Cloud Run service account + IAM
├── Secret Manager populated
├── Staging environment deployed (scaffold only)
└── GO/NO-GO: Can staging accept a real service deployment?

WEEK 4-6: OCR Module Development + Deployment
├── OCR LangGraph implementation (Document AI + Gemini Vision fallback)
├── Document type handlers (4 doc types)
├── Circuit breaker for external APIs
├── Audit logging integration
├── Test against labeled document set (>90% accuracy target)
├── Deploy to staging → validate → fix issues
├── Go/No-Go checklist (subset applicable to OCR)
├── Deploy to production
├── Monitor for 1 week
└── MILESTONE: First AI module in production

WEEK 5-8: RAG Module Development + Deployment (overlaps with OCR)
├── Document ingestion pipeline (PDF → chunking → embedding → pgvector)
├── Hybrid search implementation (vector + BM25 + RRF)
├── Policy Synthesizer agent (Gemini Pro)
├── Citation verification post-processing
├── Evaluation Q&A set (50+ pairs from public NDIS docs)
├── SYSTEM tenant seeded with NDIS documents
├── Deploy to staging → evaluate → tune prompts → re-evaluate
├── Accuracy target: >80% on evaluation set (iterate until met)
├── Deploy to production
├── Monitor for 1 week
└── MILESTONE: RAG chatbot live, platform team can start integration testing
```

### Phase 1 → Phase 2 Transition (Sprint 2-5)

```
WEEK 9-10: Platform Integration Sprint
├── API contracts finalized with Nishant's team
├── JWT validation implemented (JWTTenantResolver)
├── Webhook delivery to platform backend tested
├── Platform team sends live traffic to staging OCR + RAG
├── Fix integration issues
└── MILESTONE: AI backend integrated with platform

WEEK 10-14: Voice + Case Notes + Risk Flagging
├── LiveKit deployment (GKE node or VM)
├── Voice agent development (Gemini multimodal streaming)
├── Case Note review agent
├── Risk Flagging agent + Pub/Sub event chain
├── Approval Queue service
├── End-to-end chain: Voice → Case Note → Risk Flag → Approval → Webhook
├── Deploy each component to staging as completed
├── Integration testing of the full chain
├── Load test voice at 2× expected concurrent sessions
└── MILESTONE: First HITL workflow end-to-end in production

WEEK 15-16: Stabilization
├── Monitor all modules for 2 weeks
├── Fix production issues
├── Tune prompts based on real usage patterns
├── Review approval rate metrics (target >80%)
├── Client demo of operational dashboards
└── GO/NO-GO for Phase 3 modules
```

### Phase 2 → Phase 3 (Sprint 6+)

Remaining 4 modules deployed incrementally, each following the same pattern:
1. Develop locally (docker compose)
2. Deploy to staging with test data
3. Validate accuracy/performance
4. Go/No-Go checklist
5. Deploy to production
6. Monitor for 1 week

---

## ROLLBACK PROCEDURE

### Cloud Run Instant Rollback (< 30 seconds)

```bash
# See current revisions
gcloud run revisions list --service=sena-ocr --region=australia-southeast1

# Route 100% traffic to previous revision
gcloud run services update-traffic sena-ocr \
  --region=australia-southeast1 \
  --to-revisions=sena-ocr-00042=100

# Verify
gcloud run services describe sena-ocr --region=australia-southeast1 --format='value(status.traffic)'
```

**Timeline**:
1. P1 alert fires (~2 min detection)
2. Senior dev receives page, opens terminal (~2 min)
3. Runs rollback command (~30 sec)
4. Cloud Run routes traffic to previous revision (~10 sec)
5. **Total time to safety: < 5 minutes**

### Database Rollback (More Complex)

If the deployment includes a schema migration that breaks the previous revision:

**Prevention**: Never deploy a breaking migration and new code in the same step. Use the **expand-contract pattern**:
1. **Expand**: Deploy migration that adds new columns/tables (backward compatible). Old code ignores new columns.
2. **Deploy**: Deploy new code that uses new columns.
3. **Contract**: After stabilization, deploy migration that removes old columns (if needed).

This means any Cloud Run rollback to a previous revision still works against the current database schema.

**If a migration must be rolled back**:
1. `alembic downgrade -1` against staging first
2. Verify previous revision works against downgraded schema
3. Apply downgrade to production
4. Route traffic to previous Cloud Run revision

**Important**: Alembic migration files in versions/ must include both `upgrade()` and `downgrade()` functions. Never skip the downgrade path.

### Vector Store Rollback

If a bad RAG document or embedding model change corrupts the vector store:

1. Every document ingestion is tracked with `version` and `ingested_at` metadata
2. Rollback: `UPDATE document_chunks SET is_active = false WHERE ingested_at > :rollback_timestamp`
3. This immediately excludes bad chunks from retrieval without deleting them
4. Investigate, fix, re-ingest

### Redis Rollback (Voice Sessions)

Redis data is ephemeral by design (TTL < 1 hour). No rollback needed — active voice sessions may be interrupted, but they can restart. The form state includes `completed_sections`, so a restarted session resumes from where it left off.

---

## DISASTER RECOVERY

### Failure Scenarios and Recovery

| Scenario | Impact | Recovery | RTO | RPO |
|---|---|---|---|---|
| **Cloud Run service crash** | Single module unavailable | Cloud Run auto-restarts (built-in); if image is broken, rollback to previous revision | <1 min (auto), <5 min (manual rollback) | 0 (stateless) |
| **Cloud SQL failure** | All modules unavailable (DB is shared) | Cloud SQL HA automatic failover to standby | <2 min (auto failover) | 0 (synchronous replication) |
| **Cloud SQL data corruption** | Data loss | Point-in-time recovery from automated backups | ~30 min (restore from backup) | <24h (daily backups), <5 min with PITR enabled |
| **Single AZ outage** | Services in that zone unavailable | Cloud Run: auto-migrates to healthy zones; Cloud SQL HA: auto-failover | <5 min | 0 |
| **Region outage** (australia-southeast1 down) | EVERYTHING down | No automated cross-region failover (cost-prohibitive for 2-person team). Manual: deploy to australia-southeast2 from CI/CD. DB: restore from cross-region backup. | Hours (manual) | <24h (cross-region backup, if configured) |
| **Vertex AI outage** | All LLM calls fail | Circuit breaker opens → fallback behavior per module (OCR: return raw Document AI output without LLM enhancement; RAG: return "Service temporarily unavailable" with retrieved chunks but no synthesis) | Depends on Google | 0 (no data loss, degraded functionality) |
| **Accidental deletion** (someone runs `terraform destroy`) | Everything gone | Restore from: Terraform state + Cloud SQL backup + Artifact Registry images. CI/CD can redeploy all services from git main branch. | Hours | <24h |

### Backup Strategy

| Data | Backup Method | Retention | Location |
|---|---|---|---|
| PostgreSQL (all data + audit) | Cloud SQL automated daily backup + PITR | Daily: 7 days, PITR: 7 days, Monthly: 1 year | Same region (default) + cross-region (configure manually) |
| Vector embeddings | Included in PostgreSQL backup (pgvector in same DB) | Same as PostgreSQL | Same as PostgreSQL |
| GCS documents (uploaded PDFs, reports) | GCS versioning + lifecycle policy | 90 days for processed files, indefinite for reports | Same bucket, versioning enabled |
| Redis session state | **No backup** (ephemeral, TTL <1h) | N/A | N/A |
| Container images | Artifact Registry (immutable tags) | 90 days (configurable) | Same region |
| Infrastructure config | Terraform state in GCS backend | Versioned | GCS with versioning |
| Source code | Git (GitHub/GitLab) | Indefinite | External (not GCP-dependent) |

### What We Deliberately DON'T Have (and Why)

- **No multi-region active-active**: Cost-prohibitive and operationally impossible for 2 people. A full australia-southeast1 outage is extremely rare (<1 per year for GCP). Accept the risk.
- **No dedicated DR environment**: Same reason. If the region is down, we deploy to australia-southeast2 manually. CI/CD makes this a 30-minute process, not a week-long process.
- **No automated chaos testing**: Netflix-style chaos engineering requires dedicated infrastructure and time. Not feasible now. Instead: manually test failure scenarios once per quarter (kill a Cloud Run instance, simulate DB failover, disable Vertex AI endpoint).

---

## INFRASTRUCTURE AS CODE

### Decision: Terraform (Minimal, Incremental)

The TECHNICAL_DECISIONS.md (C.2) notes IaC as OPEN. For a 2-person team:

**Start with 3 Terraform files, not 30:**

```
infra/
├── main.tf          # Provider config, project, region
├── database.tf      # Cloud SQL instance, databases, users, RLS setup
├── services.tf      # Cloud Run services (one per module), IAM, VPC connector
└── terraform.tfvars # Environment-specific values (staging vs production)
```

**What Terraform manages:**
- Cloud SQL instance + users + databases
- Cloud Run services (image reference, env vars, scaling config)
- Secret Manager secrets (references, not values)
- VPC connector (Cloud Run → Cloud SQL private network)
- Artifact Registry

**What Terraform does NOT manage (manual or GCP Console):**
- Initial GCP project creation + billing link
- Domain registration + DNS
- CI/CD pipeline config (lives in `.github/workflows/`)
- Vertex AI model endpoint activation

**Why not Pulumi or CDK?** Terraform is the most common IaC tool, has the best GCP provider, and the team lead likely has exposure to it. Don't optimize for the best tool; optimize for the tool someone can maintain.

---

## SCALING STRATEGY

### Auto-Scaling Configuration (Cloud Run)

| Service | Min Instances | Max Instances | Concurrency | CPU | Memory | Why |
|---|---|---|---|---|---|---|
| OCR | 0 | 10 | 10 | 1 | 512 MiB | Low traffic, each request is independent, 0 min saves cost |
| RAG | 1 | 20 | 5 | 1 | 1 GiB | Keep 1 warm (cold start loads embedding model), lower concurrency (LLM calls are resource-heavy) |
| Case Note | 0 | 10 | 10 | 1 | 512 MiB | Burst at shift changes, scale to zero overnight |
| Risk Flagging | 1 | 10 | 20 | 1 | 512 MiB | Event-driven, keep 1 warm for Pub/Sub pull, high concurrency (mostly waiting on LLM API) |
| Report Gen | 0 | 5 | 1 | 2 | 2 GiB | CPU-heavy (LaTeX compilation), low concurrency to prevent OOM |
| Voice | N/A | N/A | N/A | N/A | N/A | NOT on Cloud Run — runs on dedicated compute (GKE/VM) |

### Scaling Inflection Points (from §9.4, validated)

| Trigger | Current Capacity | Upgrade Path | Estimated When |
|---|---|---|---|
| Cloud Run cold starts annoying users | 0 min instances | Set min=1 for critical services | After MVP launch |
| DB connection pool exhaustion | 10+20 per service (session.py) | Add PgBouncer as connection pooler in front of Cloud SQL | >5 services or >100 concurrent connections |
| pgvector query latency >200ms | ~5M vectors | Add partial HNSW indexes per tenant, or migrate to dedicated Qdrant | >5M vectors |
| Pub/Sub backlog during shift changes | Single consumer per subscription | Add horizontal scaling: multiple Cloud Run instances pulling from same subscription | >5K case notes/day |
| Voice concurrent sessions >50 | Single LiveKit node | Add LiveKit pods with load balancing | >50 concurrent voice sessions |

---

## OPERATIONAL RUNBOOK STUBS

The docs/runbooks/ directory exists but is empty. These runbooks must be written before production deploy:

### Runbook 1: Service Rollback
**When**: P1 alert fires after deployment  
**Steps**: See Rollback Procedure above  
**Owner**: Senior dev  

### Runbook 2: Database Failover
**When**: Cloud SQL primary becomes unavailable  
**Steps**: Verify HA automatic failover → check application reconnection → verify RLS still enforced on new primary  
**Owner**: Senior dev  

### Runbook 3: Vertex AI Outage
**When**: `sena.circuit_breaker.open` alert for Vertex AI  
**Steps**: Verify circuit breaker is open → confirm degraded mode active per module → monitor GCP status page → circuit breaker half-open auto-tests recovery → when Vertex AI is back, circuit breaker closes automatically  
**Owner**: Team lead (senior dev informed)  

### Runbook 4: Tenant Isolation Alert
**When**: `sena.tenant.isolation.breach` P1 alert  
**Steps**: IMMEDIATE — this is a potential legal incident. (1) Identify the affected request via request_id in alert. (2) Check audit_log for what data was accessed. (3) Determine if actual cross-tenant data was exposed or if it's a false positive (e.g., missing header). (4) If real breach: notify client immediately, document for OAIC breach notification (30-day window). (5) Root cause analysis → fix → deploy.  
**Owner**: Senior dev  

### Runbook 5: Approval Queue Backlog
**When**: `sena.approval.queue.backlog` P2 alert  
**Steps**: Check which tenants are affected → verify managers are active → if Tier 3 items are stale, manually escalate → notify platform team to contact tenant's managers  
**Owner**: Team lead  

---

## COST MANAGEMENT CONTROLS

### Auto-Shutoff: Prevent Runaway Costs

| Control | Trigger | Action |
|---|---|---|
| Cloud Run max instances cap | Hard limit per service (see scaling table) | Cloud Run rejects new requests with 429 (better than $10K bill) |
| GCP billing alert | Monthly spend > $1,000 (MVP) or $2,000 (scale) | Email + Slack notification to senior dev |
| GCP budget auto-shutdown | Monthly spend > $3,000 | Auto-disable billing on non-critical services (requires GCP billing API setup) |
| Vertex AI quota | Per-model QPM (queries per minute) limit | Vertex AI returns 429 → circuit breaker opens → degraded mode |
| Document AI page limit | Monthly page processing cap in GCP Console | Document AI rejects requests beyond limit |

### Cost Review Cadence

| When | What | Who |
|---|---|---|
| Daily | Check GCP billing dashboard (30-second glance) | Team lead |
| Weekly | Review cost tracking dashboard (Phase 6, Dashboard 3) | Senior dev |
| Monthly | Compare actual spend vs. Phase 3 projections, adjust budget alerts | Senior dev + report to client |

---

## RECOMMENDED DEPLOYMENT ENHANCEMENTS — PRIORITIZED

| Priority | Enhancement | Category | Effort | When |
|---|---|---|---|---|
| **P0** | Set up CI pipeline (lint + test + build + tenant isolation gate) | CI/CD | Medium | Sprint 0 (NOW) |
| **P0** | Init git repo, push scaffold, protected `main` branch | Source Control | Small | Sprint 0 (NOW) |
| **P0** | GCP project + Cloud SQL + staging Cloud Run deployment | Infrastructure | Medium | Week 3 (after client confirms GCP) |
| **P0** | Terraform for Cloud SQL + Cloud Run (3 files, minimal) | IaC | Medium | Week 3 |
| **P1** | Staging auto-deploy on merge to main | CI/CD | Small | Week 3 |
| **P1** | Go/No-Go checklist as CI gate (pre-production promotion) | Process | Small | Week 4 |
| **P1** | GCP billing alerts ($1,000/$2,000/$3,000 thresholds) | Cost Control | Small | Week 3 |
| **P1** | Production Cloud Run with Secret Manager integration | Infrastructure | Medium | Week 4 |
| **P1** | Expand-contract migration pattern documented + enforced | Database | Small | Sprint 1 |
| **P2** | Operational runbooks (5 critical scenarios) | Documentation | Medium | Before first production deploy |
| **P2** | Load testing setup (`locust` or `k6`) | Testing | Medium | Sprint 1 |
| **P2** | Cloud SQL cross-region backup (DR) | Infrastructure | Small | After production stable |
| **P3** | Quarterly manual chaos test (kill services, simulate failures) | Resilience | Small (recurring) | After Phase 2 |
| **P3** | Auto-shutdown on budget exceeded | Cost Control | Medium | When monthly spend > $500 |

---

## PRODUCTION DEPLOYMENT ARCHITECTURE SUMMARY

```
┌─────────────────────────────────────────────────────────────────────┐
│                   DEPLOYMENT ARCHITECTURE                            │
│                                                                      │
│  SOURCE OF TRUTH                                                     │
│  ├── Git (GitHub/GitLab) — all code, migrations, IaC                │
│  ├── Terraform state in GCS — infrastructure state                   │
│  └── GCP Secret Manager — all production credentials                 │
│                                                                      │
│  CI/CD PIPELINE                                                      │
│  ├── Feature branch → lint + test + build → PR review               │
│  ├── Merge to main → auto-deploy staging → smoke tests              │
│  ├── Manual promote → deploy production (same image)                │
│  └── GATE: tenant isolation regression (NEVER skip)                  │
│                                                                      │
│  STAGING (australia-southeast1)                                      │
│  ├── Cloud Run (per-service, scale-to-zero)                         │
│  ├── Cloud SQL (small tier, synthetic data)                         │
│  └── Platform team integration testing endpoint                     │
│                                                                      │
│  PRODUCTION (australia-southeast1)                                   │
│  ├── Cloud Run (per-service, HA, auto-scaling)                      │
│  ├── Cloud SQL HA (automatic failover, daily backups, PITR)         │
│  ├── Memorystore Redis (TLS + AUTH)                                 │
│  ├── GCS (tenant-scoped buckets, versioning)                        │
│  ├── Cloud Pub/Sub (event bus, dead-letter queues)                  │
│  ├── Vertex AI (Gemini Flash + Pro, AU region)                      │
│  ├── Cloud Armor WAF (gateway protection)                           │
│  └── VPC-internal (no public IPs except gateway)                    │
│                                                                      │
│  ROLLBACK                                                            │
│  ├── Cloud Run: instant revision rollback (<30s)                    │
│  ├── Database: expand-contract migrations (always backward-compat)  │
│  ├── Vectors: soft-delete ( is_active=false) by ingestion timestamp │
│  └── Total time to safety: <5 minutes                               │
│                                                                      │
│  MONITORING (Phase 6)                                                │
│  ├── Cloud Logging (structured JSON, PII-redacted)                  │
│  ├── Cloud Trace (OpenTelemetry, distributed)                       │
│  ├── Cloud Monitoring (custom metrics + alerts)                     │
│  └── 4 dashboards: Ops, AI Quality, Cost, Tenant Health             │
└─────────────────────────────────────────────────────────────────────┘
```

---

## === END OF DESIGN REVIEW ===

All 7 phases complete:

| Phase | Focus | Key Finding |
|---|---|---|
| **Phase 1** | Architecture | Hierarchical topology validated; 8 LLM agents + 10 deterministic components correctly sized |
| **Phase 2** | Memory & State | pgvector + Redis + PostgreSQL stack validated; tenant filter in WHERE clause (not just RLS) critical for vector search correctness |
| **Phase 3** | Cost & Latency | Design's cost estimates overstated by ~3×; corrected to ~$730/month at 50 orgs; voice critical path needs pipelining to hit <1s |
| **Phase 4** | Failure Modes | Expanded from 6 to 16 failure modes; approval queue backlog (FM-7) and stale knowledge base (FM-8) are highest new risks |
| **Phase 5** | Security | Persistent prompt injection via document upload is the #1 security gap; APP 13 (right to deletion) has no implementation; RBAC not enforced |
| **Phase 6** | Monitoring | No operational observability exists yet; 4-pillar metric design + OpenTelemetry + structlog + PII sanitization needed; ~$0-30/month cost |
| **Phase 7** | Deployment | Cloud Run per-module (not GKE), revision-based rollback (not canary), expand-contract migrations, tenant isolation as CI gate, <5 min rollback |