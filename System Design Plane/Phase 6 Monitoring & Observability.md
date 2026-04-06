
# === PHASE 6: MONITORING & OBSERVABILITY DESIGN ===

## CURRENT STATE — WHAT EXISTS VS WHAT'S MISSING

The design has **fragments** of observability scattered across multiple sections, but **no cohesive monitoring architecture**. Here's the honest inventory:

### What Exists (Built or Designed)

| Component | Location | Status |
|---|---|---|
| `X-Request-ID` correlation middleware | request_id.py | **Built** — generates/propagates UUID per request |
| Tenant context propagation | tenant_context.py | **Built** — ContextVar per request |
| `audit_log` table schema | Appendix D of system design | **Designed** — captures agent name, tokens, latency, confidence, status |
| Health check endpoint | routes.py `/v1/ocr/health` | **Built** — checks DB connectivity |
| Error handler with severity levels | error_handler.py | **Built** — CRITICAL for tenant isolation breaches |
| `log_level` + `log_format` settings | settings.py | **Built** — defaults to JSON format |
| Evaluation strategy table | §8.3 | **Designed** — 7 evaluation methods listed |
| Latency SLA targets | §9.1 | **Designed** — voice <1s, OCR <3s, RAG <5s, reports <60s |

### What's MISSING (Critical Gaps)

| Gap | Impact | Phase to Fix |
|---|---|---|
| **No structured logging implementation** — `log_format: "json"` is configured but no actual structured logger is initialized anywhere | Cannot query or filter logs effectively; GCP Cloud Logging won't parse unstructured Python print statements | Sprint 0 |
| **No OpenTelemetry integration** — no trace spans, no distributed tracing across LangGraph nodes or inter-service calls | Cannot trace a request across OCR → Audit → Approval or Case Note → Risk Flagging async chain | Sprint 1 |
| **No metrics collection** — no Prometheus, no Cloud Monitoring custom metrics, no counters or gauges anywhere in the codebase | No latency percentiles, no error rates, no cost tracking, no SLA monitoring | Sprint 1 |
| **No alerting rules defined** — §8.3 mentions "alert: voice P95 > 1.5s, RAG P95 > 5s" but no alerting infrastructure or rule definitions exist | Failures go undetected until a user complains; NDIS compliance issues could remain hidden for hours/days | Sprint 1 |
| **No dashboards** — no Grafana, no Cloud Monitoring dashboards, no visualization of any metric | Team has no operational visibility; can't demo system health to the client | Sprint 1 |
| **No PII redaction in telemetry** — traces and logs will contain participant names, medical history, voice transcripts | Australian Privacy Act violation if telemetry data is exported to external systems (Datadog, Grafana Cloud) | Sprint 1 |
| **No cost tracking instrumentation** — the corrected cost model (Phase 3) has per-request costs but no way to measure actual spend | Cannot validate $730/month projection; cost surprises at scale | Sprint 2 |
| **No AI-specific observability** — hallucination detection, confidence score trends, citation failure rates, approval rates are in the eval strategy but have no collection mechanism | Cannot detect model degradation, cannot report quality metrics to client | Sprint 2 |

---

## KEY METRICS — FOUR PILLARS

### Pillar 1: Agent Performance Metrics

These are **SENA-specific**. Generic web app metrics (HTTP status codes, response times) are necessary but not sufficient. The real monitoring challenge is: **"Is the AI behaving correctly?"**

| Metric Name | Type | Labels | Source | Why It Matters |
|---|---|---|---|---|
| `sena.agent.latency_ms` | Histogram | `agent_name`, `graph_node`, `tenant_id`, `status` | OpenTelemetry span duration | P95 latency per agent; detect model slowdowns before they hit SLA |
| `sena.agent.tokens_input` | Counter | `agent_name`, `llm_model`, `tenant_id` | LLM API response metadata | Track token consumption for cost reconciliation |
| `sena.agent.tokens_output` | Counter | `agent_name`, `llm_model`, `tenant_id` | LLM API response metadata | Output tokens are 4x more expensive; detect prompt bloat |
| `sena.agent.confidence` | Histogram | `agent_name`, `tenant_id` | Agent output `confidence` field | Detect model drift — if median confidence drops week-over-week, model or data has changed |
| `sena.agent.errors` | Counter | `agent_name`, `error_type`, `tenant_id` | Exception handler | Error rate per agent; distinguish transient (timeout) from persistent (bad prompt) |
| `sena.agent.fallback_used` | Counter | `agent_name`, `fallback_type` | Circuit breaker | How often are we hitting fallback paths? High rate = upstream reliability issue |
| `sena.agent.retries` | Counter | `agent_name`, `retry_reason` | Retry middleware | High retry rates waste money and add latency |

**Challenge to §8.3**: The design's evaluation strategy lists 7 metrics but **none are instrumented as real-time metrics**. The "Approval Rate Tracking" says "Continuous metric (dashboard)" but there's no counter being incremented anywhere. The "Latency P95" says "Continuous monitoring" but there's no histogram recording latency. These are aspirational, not operational.

### Pillar 2: System Health Metrics

| Metric Name | Type | Labels | Source | Why It Matters |
|---|---|---|---|---|
| `sena.request.latency_ms` | Histogram | `service`, `endpoint`, `method`, `status_code` | FastAPI middleware | End-to-end request latency (not just LLM call time) |
| `sena.request.total` | Counter | `service`, `endpoint`, `method`, `status_code` | FastAPI middleware | Request volume + error rate derivation |
| `sena.db.query_latency_ms` | Histogram | `service`, `query_type` | SQLAlchemy event hooks | Detect slow queries (vector search, audit writes) |
| `sena.db.pool_usage` | Gauge | `service` | SQLAlchemy pool stats | Detect connection pool exhaustion before it causes timeouts |
| `sena.redis.latency_ms` | Histogram | `operation` | Redis client wrapper | Voice session state reads must be <10ms; detect Redis issues |
| `sena.redis.connections` | Gauge | | Redis client stats | Connection pool health |
| `sena.pubsub.messages_published` | Counter | `topic`, `event_type` | Pub/Sub client | Event flow volume |
| `sena.pubsub.messages_received` | Counter | `subscription`, `event_type` | Pub/Sub handler | Verify events are being consumed |
| `sena.pubsub.processing_latency_ms` | Histogram | `subscription`, `event_type` | Time from publish to processing | Detect queue backlogs |
| `sena.circuit_breaker.state` | Gauge (enum→int) | `service_name`, `dependency` | Circuit breaker state changes | 0=closed, 1=half-open, 2=open. Alert on open state. |

### Pillar 3: Business / AI Quality KPIs

These are what the **client** cares about. If the client asks "How is the AI performing?", these metrics answer.

| Metric Name | Type | Labels | Source | Target (from §2.4) |
|---|---|---|---|---|
| `sena.approval.rate` | Gauge (computed) | `module`, `tier`, `tenant_id` | Approval queue decisions | >80% approved without modification |
| `sena.approval.pending_count` | Gauge | `tier`, `tenant_id` | Approval queue | <10 pending per manager (FM-7 from Phase 4) |
| `sena.approval.time_to_decision_hours` | Histogram | `tier`, `tenant_id` | Approval timestamps | Tier 3: <2h, Tier 2: <24h |
| `sena.rag.citation_accuracy` | Gauge (computed) | `tenant_id` | Post-processing citation verification | >85% (§2.4) |
| `sena.rag.retrieval_hit_rate` | Gauge | `tenant_id` | RAG retriever (>0 relevant chunks returned) | >95% (queries should return something) |
| `sena.ocr.field_confidence` | Histogram | `document_type`, `field_name` | OCR agent output | >90% fields above 0.7 confidence |
| `sena.risk.flags_per_day` | Counter | `risk_category`, `severity`, `tenant_id` | Risk classifier output | Baseline, then anomaly detection |
| `sena.voice.session_completion_rate` | Gauge | `objective`, `tenant_id` | Voice session end state | >80% of sessions complete the form |
| `sena.voice.turns_per_session` | Histogram | `objective`, `tenant_id` | Voice session turn count | Detect "stuck" conversations (>30 turns) |

**Critical insight**: The `sena.approval.rate` metric is THE leading indicator for AI quality. If managers are rejecting >20% of AI outputs, either the model is wrong or the prompt needs tuning. This metric should be on every dashboard and reviewed weekly.

### Pillar 4: Cost Observability

| Metric Name | Type | Labels | Source | Why It Matters |
|---|---|---|---|---|
| `sena.cost.llm_input_tokens` | Counter | `model`, `agent_name`, `tenant_id` | LLM gateway | Real cost tracking vs. Phase 3 projections |
| `sena.cost.llm_output_tokens` | Counter | `model`, `agent_name`, `tenant_id` | LLM gateway | Output tokens are 4x more expensive for Gemini Pro |
| `sena.cost.estimated_usd` | Counter | `model`, `agent_name` | Derived (tokens × price) | Real-time spend. Alert if daily spend >2× projected. |
| `sena.cost.document_ai_pages` | Counter | `tenant_id` | Document AI API response | $1.50/1000 pages — track actual usage |
| `sena.cost.embedding_tokens` | Counter | `tenant_id` | Embedding API response | Negligible per Phase 3, but track anyway for anomaly detection |

---

## ALERT DEFINITIONS — THREE TIERS

### P1 — Critical (Page On-Call Immediately)

For a 2-person team, "on-call" is the senior dev. P1 means: **production is broken, users are affected.**

| Alert | Condition | Window | Why It's P1 |
|---|---|---|---|
| `sena.voice.latency.critical` | Voice turn P95 > 2,000ms | 3 min sustained | Voice sessions are unusable; participant experience destroyed |
| `sena.error.rate.critical` | Any service error rate > 15% | 2 min sustained | System is failing; tenant isolation breach possible if errors are in middleware |
| `sena.tenant.isolation.breach` | ANY `TenantIsolationError` logged at CRITICAL level | Immediate (single event) | Legal compliance — even one cross-tenant data access is a reportable breach |
| `sena.circuit_breaker.open` | Circuit breaker transitions to OPEN for Vertex AI | Immediate | All LLM calls failing; entire AI layer is non-functional |
| `sena.db.connection.exhausted` | DB pool available connections = 0 | 1 min sustained | All requests will timeout; cascading failure |

**Total P1 alerts: 5.** This is the right number for a 2-person team. More than 8 P1s creates alert fatigue.

### P2 — Warning (Slack/Teams Notification, Review Within Hours)

| Alert | Condition | Window | Action |
|---|---|---|---|
| `sena.request.latency.degraded` | Any service P95 > 2× SLA target (e.g., RAG P95 > 10s) | 10 min sustained | Investigate — likely a slow Vertex AI response or query performance issue |
| `sena.approval.queue.backlog` | Any tenant has >20 pending Tier 2/3 items | 30 min sustained | FM-7 (Phase 4): notify managers, check workload balancing |
| `sena.approval.tier3.stale` | Any Tier 3 item unreviewed for >1 hour | Rolling check every 15 min | NDIS compliance risk — mandatory reporting items must be actioned promptly |
| `sena.agent.confidence.drop` | Median confidence for any agent drops >15% vs 7-day rolling average | Daily computation | Model degradation or data distribution shift |
| `sena.cost.daily.exceeded` | Estimated daily LLM spend > 2× projected daily budget | Daily at 18:00 UTC | Cost anomaly — possible infinite loop, prompt bloat, or traffic spike |
| `sena.rag.knowledge.stale` | RAG evaluation Q&A set accuracy drops below 80% | Weekly batch | Knowledge base may have outdated NDIS rules (FM-8 from Phase 4) |
| `sena.approval.rate.low` | Approval rate drops below 70% for any module | Weekly computation | AI quality degradation — model or prompt needs review |
| `sena.error.rate.elevated` | Any service error rate > 5% | 5 min sustained | Something is wrong but not catastrophic; investigate before it becomes P1 |
| `sena.pubsub.lag` | Pub/Sub message processing lag > 5 min | 10 min sustained | Async pipeline (risk flagging, reports) is backed up |

### P3 — Informational (Dashboard Only, Review Weekly)

| Alert | Condition | Purpose |
|---|---|---|
| `sena.agent.fallback.elevated` | Fallback usage > 10% of calls for any agent | Track upstream reliability trends |
| `sena.db.query.slow` | Any query > 500ms | Identify optimization candidates |
| `sena.redis.latency.elevated` | Redis P95 > 50ms | Early warning for voice session impact |
| `sena.cost.monthly.projection` | Projected monthly cost based on current rate | Track against Phase 3 budget |
| `sena.ocr.low_confidence` | >20% of OCR extractions have confidence <0.7 | Document quality issue or model degradation |

---

## DISTRIBUTED TRACING STRATEGY

### The Problem: LangGraph Makes Tracing Non-Trivial

A single user request in SENA can traverse:
1. **API Gateway** (auth, tenant context, audit entry)
2. **LangGraph StateGraph nodes** (3-7 nodes depending on module, conditional edges)
3. **External API calls** (Vertex AI, Document AI, Redis, PostgreSQL)
4. **Async event chains** (Pub/Sub: Case Note → Risk Flagging → Approval Queue)

Standard HTTP tracing (OpenTelemetry auto-instrumentation for FastAPI) captures step 1 and partial step 3. It **does NOT** automatically instrument LangGraph nodes or Pub/Sub event chains. This means the most important part of the system — what the AI agents are actually doing — is invisible.

### Proposed: OpenTelemetry + LangGraph Custom Spans

**Stack**: OpenTelemetry SDK → Cloud Trace (GCP-native collector) OR Jaeger (self-hosted for cost savings)

**Decision recommendation**: Start with **Cloud Trace** (zero infrastructure overhead for a 2-person team, GCP-native, auto-ingests from Cloud Run). Switch to Jaeger/Grafana Tempo only if Cloud Trace's query capabilities are insufficient or costs become unreasonable.

**Span hierarchy for a RAG query:**

```
Trace: abc-123 (request_id)
│
├── [SPAN] gateway.auth_validate          2ms
├── [SPAN] gateway.tenant_context         1ms
├── [SPAN] gateway.audit_create           5ms
│
├── [SPAN] rag.graph.execute              3,200ms
│   ├── [SPAN] rag.node.embed_query       150ms
│   │   └── [SPAN] vertexai.embed         140ms   ← external call
│   ├── [SPAN] rag.node.hybrid_search     200ms
│   │   ├── [SPAN] pgvector.search        80ms    ← DB query
│   │   ├── [SPAN] bm25.search            50ms    ← DB query
│   │   └── [SPAN] rrf.fusion             5ms
│   ├── [SPAN] rag.node.rerank            300ms
│   │   └── [SPAN] vertexai.rerank        290ms   ← external call
│   ├── [SPAN] rag.node.synthesize        2,100ms
│   │   └── [SPAN] vertexai.generate      2,050ms ← external call
│   ├── [SPAN] rag.node.format_response   20ms
│   └── [SPAN] rag.node.audit_output      30ms
│       └── [SPAN] db.insert.audit_log    25ms
│
└── [SPAN] gateway.response               1ms

Total: 3,239ms
```

### Span Attributes (Standard Across All Agents)

Every span must carry:
- `sena.tenant_id` — for per-tenant analysis and **mandatory** for filtering PII
- `sena.request_id` — correlates with `X-Request-ID` header and audit log
- `sena.agent_name` — which agent persona (e.g., "policy_synthesizer")
- `sena.graph_node` — which LangGraph node (e.g., "hybrid_search")
- `sena.llm_model` — which model was called (e.g., "gemini-1.5-flash-002")
- `sena.tokens_in` / `sena.tokens_out` — per LLM call
- `sena.confidence` — agent output confidence score

### Cross-Service Trace Propagation (Pub/Sub)

The async chain (Case Note → Risk Flagging) currently **breaks the trace**. Pub/Sub messages don't automatically propagate trace context.

**Fix**: Embed `traceparent` header in the Pub/Sub event envelope (Appendix B already defines a metadata field). The Risk Flagging consumer extracts `traceparent` and creates a child span, linking the async chain to the original request.

```
Event Envelope (existing, from Appendix B):
{
  "event_type": "case_note.submitted",
  "tenant_id": "...",
  "metadata": {
    "request_id": "abc-123",
    "traceparent": "00-abc123...-def456...-01"  ← ADD THIS
  },
  "payload": { ... }
}
```

This creates a **single trace spanning synchronous + asynchronous processing**, which is essential for debugging end-to-end flows like: "A case note was submitted at 3:15pm; when did the risk flag get created, and why did it take 45 minutes instead of 5 seconds?"

### Sampling Strategy

At scale (50 orgs, 2,000 shifts/day), generating a trace for every request will produce ~70K+ spans/day. GCP Cloud Trace charges $0.20 per million spans ingested (first 25M/month free). Cost is negligible, but storage and query performance degrade with high volume.

**Recommendation**:
- **100% tracing during MVP** (5-10 orgs) — you need every trace for debugging
- **10% sampling at scale** EXCEPT:
  - Always trace: requests that hit a fallback path
  - Always trace: requests with latency > 2× SLA target
  - Always trace: requests that result in errors
  - Always trace: Tier 3 approval items
- This "tail sampling" approach captures interesting requests at 100% and routine ones at 10%

---

## STRUCTURED LOGGING DESIGN

### Gap: Built But Not Wired

The [settings.py](sena-ai/shared/src/sena_common/config/settings.py) has `log_format: str = "json"` — but **no actual logger is configured to use it**. The codebase has no `logging.config`, no `structlog` setup, no log formatters. Every `print()` or unconfigured `logging.info()` call will produce unstructured text that GCP Cloud Logging can ingest but cannot parse.

### Proposed: structlog + JSON Lines

**Why structlog over standard library logging**: structlog provides structured key-value logging natively, plays well with OpenTelemetry, and automatically binds context variables (tenant_id, request_id) to every log entry without manually passing them.

**Log entry structure (every log line)**:

```json
{
  "timestamp": "2026-03-11T14:30:00.123Z",
  "level": "INFO",
  "message": "RAG query completed",
  "service": "sena-rag",
  "request_id": "abc-123",
  "tenant_id": "aaaaaaaa-...",
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "span_id": "00f067aa0ba902b7",
  "agent_name": "policy_synthesizer",
  "graph_node": "synthesize",
  "duration_ms": 2100,
  "tokens_in": 4200,
  "tokens_out": 850,
  "confidence": 0.87,
  "extra": {}
}
```

### Log Levels — SENA-Specific Usage

| Level | When to Use | Example |
|---|---|---|
| `CRITICAL` | Tenant isolation breach, data corruption | `TenantIsolationError: tenant X accessed by tenant Y` |
| `ERROR` | Request failed, agent error, unhandled exception | `Vertex AI returned 500 for document_extractor` |
| `WARNING` | Degraded operation, fallback used, slow query | `Circuit breaker HALF-OPEN for vertexai; using fallback` |
| `INFO` | Normal operations, request start/end, agent output | `RAG query completed: 3 citations, confidence=0.87` |
| `DEBUG` | Detailed internals (dev only) | `LangGraph edge: hybrid_search → rerank (condition: chunks > 0)` |

### PII in Logs — Critical Risk

**Challenge**: The current `error_handler.py` logs the full error context. The `audit_log` stores full `input_payload` and `output_payload`. If these are also emitted as log lines (which is common for debugging), log entries will contain:
- Participant names and medical history (case notes)
- Voice transcripts (health discussions)
- Extracted ID document fields (driver's licence numbers, Medicare numbers)

**If logs are exported to any external system** (Datadog, Grafana Cloud, even GCP Cloud Logging in a shared project), this is an Australian Privacy Act breach.

**Mitigation** (non-negotiable before production):
1. **Log sanitizer**: A structlog processor that redacts known PII patterns before the log entry is emitted. Patterns: Medicare numbers (`\d{4}\s?\d{5}\s?\d{1}`), phone numbers, dates of birth, and any field from a configurable blocklist.
2. **Never log full payloads at INFO level**: Full payloads go to `audit_log` table (which is RLS-protected and encrypted). Log lines should contain only metadata: `agent_name`, `confidence`, `token_count`, `latency_ms`, `status`. Never the actual input text or output text.
3. **Log export controls**: GCP Cloud Logging should use a **log sink with exclusion filters** that strip any log entry containing fields from a sensitive attribute list before exporting to external monitoring tools.
4. **Separate audit from operational logs**: Audit = compliance trail, stored in PostgreSQL with RLS. Operational logs = debugging, stored in Cloud Logging with 30-day retention. Don't mix these.

---

## DASHBOARD DESIGN — FOUR VIEWS

### Dashboard 1: Operations Overview (For the Dev Team)

**Purpose**: "Is the system healthy right now?"

| Panel | Metric | Visualization |
|---|---|---|
| Request Rate | `sena.request.total` rate by service | Time series, stacked by service |
| Error Rate | `sena.request.total{status_code>=500}` / total | Time series, alert threshold line at 5% |
| P95 Latency by Module | `sena.request.latency_ms` p95 by service | Time series, with SLA threshold lines |
| Circuit Breaker States | `sena.circuit_breaker.state` by dependency | Status indicators (green/yellow/red) |
| DB Pool Usage | `sena.db.pool_usage` | Gauge with threshold at 80% |
| Active Voice Sessions | Count of open LiveKit rooms | Single stat |
| Pub/Sub Lag | `sena.pubsub.processing_latency_ms` p95 | Time series with 5-min threshold |

### Dashboard 2: AI Quality (For Weekly Team Review)

**Purpose**: "Is the AI getting better or worse?"

| Panel | Metric | Visualization |
|---|---|---|
| Approval Rate by Module | `sena.approval.rate` | Bar chart, weekly trend, 80% target line |
| Confidence Score Distribution | `sena.agent.confidence` histogram | Heatmap, weekly |
| RAG Citation Accuracy | `sena.rag.citation_accuracy` | Time series, 85% target line |
| Risk Flag Distribution | `sena.risk.flags_per_day` by category | Stacked bar chart |
| OCR Confidence by Field | `sena.ocr.field_confidence` | Box plot by document type |
| Hallucination Rate (Weekly) | Computed from citation verification failures | Single stat with trend arrow |
| Voice Completion Rate | `sena.voice.session_completion_rate` | Gauge with 80% target |

### Dashboard 3: Cost Tracking (For Monthly Business Review)

**Purpose**: "Are we staying within the Phase 3 budget?"

| Panel | Metric | Visualization |
|---|---|---|
| Daily LLM Spend | `sena.cost.estimated_usd` daily aggregate | Time series with daily budget line |
| Monthly Projection | Extrapolated from current daily rate | Single stat with color (green/yellow/red) |
| Token Usage by Model | `sena.cost.llm_input_tokens` + `sena.cost.llm_output_tokens` | Stacked bar by model |
| Cost per Request by Module | Total cost / request count by service | Bar chart |
| Document AI Pages | `sena.cost.document_ai_pages` | Counter with monthly target |
| Infra Cost (Cloud SQL, Redis, Compute) | GCP billing API or manual entry | Pie chart |

### Dashboard 4: Tenant Health (For Client Demo / Support)

**Purpose**: "How is tenant X performing?" — required when the client asks about a specific organization.

| Panel | Metric | Filter | Visualization |
|---|---|---|---|
| Request Volume | `sena.request.total` | by `tenant_id` | Time series |
| Error Rate | Per-tenant error count | by `tenant_id` | Single stat |
| Approval Queue Depth | `sena.approval.pending_count` | by `tenant_id` | Gauge |
| AI Usage Breakdown | Token counts by module | by `tenant_id` | Donut chart |
| Latency | P95 per module | by `tenant_id` | Table |

**Important**: This dashboard must be tagged so that it **only shows data for the selected tenant**. The `sena.tenant_id` label on all metrics makes this possible, but the dashboard template must not allow cross-tenant queries by non-superadmin users.

---

## HEALTH CHECK ENHANCEMENT

The current health check (`GET /v1/ocr/health`) only checks database connectivity. For production, health checks must cover all critical dependencies.

### Liveness vs. Readiness

| Check | Type | What It Tests | Failure Action |
|---|---|---|---|
| `GET /health/live` | Liveness | Process is running, not deadlocked | Kubernetes restarts the pod |
| `GET /health/ready` | Readiness | DB connected, Redis connected, Vertex AI reachable | Kubernetes stops routing traffic to this pod |

### Readiness Check — Full Dependency Verification

The readiness check should test:
1. **PostgreSQL**: `SELECT 1` (already implemented)
2. **Redis**: `PING` (not implemented — critical for voice service)
3. **Vertex AI**: Lightweight prediction or `GET` on model endpoint (not implemented — if Vertex AI is down, the service should not receive traffic)
4. **Pub/Sub**: Verify topic exists and subscription is active (for event-driven services like Risk Flagging)

**Challenge**: The design's single `HealthResponse` doesn't distinguish dependency failures. A health check returning `"status": "unhealthy"` tells you nothing about WHICH dependency failed. Extend to return per-dependency status:

```json
{
  "service": "sena-rag",
  "version": "0.1.0",
  "status": "degraded",
  "checks": {
    "database": "healthy",
    "redis": "healthy",
    "vertex_ai": "unhealthy",
    "pubsub": "healthy"
  }
}
```

Status logic: all healthy → "healthy"; any dependency unhealthy but service can partially function → "degraded"; critical dependency down → "unhealthy".

---

## OBSERVABILITY COST ESTIMATE

Monitoring isn't free. For a 2-person team with tight budget, this matters.

| Component | GCP Service | Free Tier | At Scale (50 orgs) | Monthly Cost |
|---|---|---|---|---|
| **Tracing** | Cloud Trace | 25M spans/month free | ~70K spans/day × 10% sampling = ~210K/month | **$0** (within free tier) |
| **Logging** | Cloud Logging | 50 GiB/month free | ~10-20 GiB/month (JSON logs, medium verbosity) | **$0** (within free tier) |
| **Metrics** | Cloud Monitoring | 150 MB/month free for custom metrics | ~50 custom metrics × 60s interval × 30 days = ~2 GiB | **~$10/month** |
| **Alerting** | Cloud Monitoring Alerting | Free (included) | 15-20 alert policies | **$0** |
| **Dashboards** | Cloud Monitoring Dashboards | Free (included) | 4 dashboards | **$0** |

**Total observability cost at MVP: ~$0/month** (within free tiers)  
**Total observability cost at scale: ~$10-30/month**

This is negligible compared to the $730/month infra budget (Phase 3). The ROI is enormous: a single undetected multi-hour outage costs more in trust and compliance risk than a year of monitoring.

**Alternative**: Self-hosted Grafana + Prometheus + Jaeger on a single VM (~$50/month) gives more control but adds operational burden for the 2-person team. **Not recommended until the team is >4 people.**

---

## IMPLEMENTATION — WHAT TO BUILD AND WHEN

### Sprint 0 (Now — during scaffold validation)

1. **Add structlog** to `sena_common` shared library
   - Configure JSON formatter
   - Bind `request_id` and `tenant_id` from ContextVars automatically
   - NO payload logging — metadata only
   - **Files**: `sena_common/logging/setup.py` (new), update `create_app()` in each service

2. **Enhance health checks**
   - Add `/health/live` and `/health/ready` separation
   - Add per-dependency status reporting
   - **Files**: Update routes.py, extract to shared health check utility

### Sprint 1 (OCR + RAG modules)

3. **Add OpenTelemetry SDK**
   - Auto-instrument FastAPI, SQLAlchemy, httpx (for Vertex AI calls)
   - Create a `@traced_node` decorator for LangGraph graph nodes that creates child spans with standard attributes
   - Export to Cloud Trace
   - **Files**: `sena_common/telemetry/setup.py` (new), `sena_common/telemetry/decorators.py` (new)

4. **Add Prometheus-style metrics**
   - Use `opentelemetry-sdk` metrics (exports to Cloud Monitoring)
   - Instrument: request latency histogram, agent latency histogram, token counters, error counters
   - **Files**: `sena_common/telemetry/metrics.py` (new)

5. **Deploy first two dashboards** (Operations Overview + AI Quality)
   - Use Cloud Monitoring dashboard-as-code (JSON/Terraform)

6. **Implement 5 P1 + 5 priority P2 alerts**

### Sprint 2+ (Voice, Risk Flagging, Reports)

7. **Pub/Sub trace propagation** — add `traceparent` to event envelope
8. **Cost tracking metrics** — instrument LLM gateway with per-model token counters
9. **PII log sanitizer** — structlog processor with configurable redaction patterns
10. **Tenant Health dashboard** — for client demos

---

## RECOMMENDED ENHANCEMENTS — PRIORITIZED

| Priority | Enhancement | Category | Effort | Impact |
|---|---|---|---|---|
| **P0** | Implement structlog with JSON formatting + context binding | Logging | Small | Foundation for all other observability |
| **P0** | Split health checks into `/health/live` + `/health/ready` with per-dependency status | Health | Small | Kubernetes-ready, prevents serving errors when dependencies fail |
| **P0** | Add OpenTelemetry auto-instrumentation (FastAPI, SQLAlchemy, httpx) | Tracing | Medium | Immediate visibility into request flows and external call latency |
| **P1** | Build `@traced_node` decorator for LangGraph nodes | Tracing | Small | AI-specific span hierarchy — the most valuable telemetry |
| **P1** | Instrument core metrics: request latency, agent latency, token counters, error counters | Metrics | Medium | Enables SLA monitoring and cost tracking |
| **P1** | Define and deploy P1 alerts (5 critical alerts) | Alerting | Small | Prevents silent failures |
| **P1** | PII sanitizer for log entries (regex-based redaction) | Compliance | Medium | Legal requirement before production |
| **P1** | Add `traceparent` to Pub/Sub event envelope | Tracing | Small | End-to-end trace across async chains |
| **P2** | Operations + AI Quality dashboards | Dashboards | Medium | Team visibility, client demos |
| **P2** | Cost tracking metrics (tokens per model, estimated USD) | Cost | Small | Budget validation against Phase 3 projections |
| **P2** | Sampling strategy (tail sampling for interesting requests) | Tracing | Small | Cost control at scale |
| **P3** | Tenant Health dashboard | Dashboards | Small | Client support and demos |
| **P3** | Alert runbooks in `docs/runbooks/` | Documentation | Medium | On-call effectiveness (directory already exists) |

---

## OBSERVABILITY ARCHITECTURE SUMMARY

```
┌─────────────────────────────────────────────────────────────────────┐
│                   OBSERVABILITY ARCHITECTURE                        │
│                                                                      │
│  COLLECTION LAYER (in-process, every service)                        │
│  ├── structlog → JSON logs → stdout → Cloud Logging                  │
│  ├── OpenTelemetry Tracer → spans → Cloud Trace                      │
│  ├── OpenTelemetry Metrics → counters/histograms → Cloud Monitoring  │
│  └── Context binding: request_id + tenant_id on every signal         │
│                                                                      │
│  ENRICHMENT LAYER                                                    │
│  ├── PII sanitizer (structlog processor, before emission)            │
│  ├── @traced_node decorator (LangGraph-specific spans)               │
│  ├── Pub/Sub traceparent propagation (async chain linking)           │
│  └── audit_log table (compliance-grade I/O capture, separate)        │
│                                                                      │
│  STORAGE & QUERY                                                     │
│  ├── Cloud Logging (operational logs, 30-day retention)              │
│  ├── Cloud Trace (distributed traces, 30-day retention)              │
│  ├── Cloud Monitoring (custom metrics, 6-month retention)            │
│  └── PostgreSQL audit_log (compliance trail, 7-year retention)       │
│                                                                      │
│  VISUALIZATION & ALERTING                                            │
│  ├── Dashboard 1: Operations Overview (team)                         │
│  ├── Dashboard 2: AI Quality (weekly review)                         │
│  ├── Dashboard 3: Cost Tracking (monthly)                            │
│  ├── Dashboard 4: Tenant Health (client/support)                     │
│  ├── P1 alerts → PagerDuty/SMS (5 rules)                            │
│  ├── P2 alerts → Slack/Teams (9 rules)                               │
│  └── P3 alerts → Dashboard only (5 rules)                            │
└─────────────────────────────────────────────────────────────────────┘
```

---

Type **'continue'** for Phase 7: Production Deployment Strategy.