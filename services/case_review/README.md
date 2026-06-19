# Case Review Service

> FastAPI + LangGraph service that automates NDIS restrictive practice detection. A support worker submits a case note (text or voice); the pipeline runs triage, retrieves NDIS policy via RAG, evaluates compliance, cross-checks the client's Behaviour Support Plan, and generates an incident report — all with full token tracking and prompt caching across AWS Bedrock Claude and Google Gemini.

---

## Table of Contents
- [What This Service Does](#what-this-service-does)
- [Architecture Overview](#architecture-overview)
- [AI Models Used](#ai-models-used)
- [7-Stage Pipeline (LangGraph)](#7-stage-pipeline-langgraph)
- [RAG — How Policy Retrieval Works](#rag--how-policy-retrieval-works)
- [Cost Optimisation — Everything We Built](#cost-optimisation--everything-we-built)
- [Token Tracking](#token-tracking)
- [API Reference](#api-reference)
- [Environment Variables](#environment-variables)
- [Running the Service](#running-the-service)
- [Database](#database)
- [Project Structure](#project-structure)

---

## What This Service Does

An NDIS support worker finishes a shift and either types or dictates their case note. This service:

1. **Screens** the note for any of the 5 regulated restrictive practices (physical, chemical, mechanical, environmental restraint, seclusion)
2. **Retrieves** the relevant NDIS policy chunks from a vector database
3. **Evaluates** whether a violation occurred and at what risk level
4. **Cross-checks** the client's Behaviour Support Plan (BSP) database — is this practice authorised?
5. **Generates** an incident draft if reporting is required (within 5 business days or 24 hours depending on severity)
6. **Summarises** the shift for the supervisor

If a case note is clean (no flags), the pipeline exits after stage 1 — no Sonnet calls, no RAG, minimal cost.

---

## Architecture Overview

```
Support Worker
    │
    ├─ POST /v1/restrictive-practices/evaluate   ← text case note
    ├─ POST /v1/restrictive-practices/draft       ← voice transcript → form fields
    └─ WS  /v1/voice/session                      ← real-time Gemini Live dictation

LangGraph Pipeline (core path):
  START
    → [1] Triage (Haiku)          — YES/NO gate + confidence score
    → [2] RAG (Cohere embeddings) — retrieve top-3 NDIS policy chunks
    → [3] Evaluator (Sonnet)      — structured compliance verdict
    → [4] Cross-check (SQL)       — BSP authorisation lookup
  END

Parallel (fire-and-forget):
    → [5] Summary (Haiku)         — shift overview for supervisor
    → [6] Incident Draft (Sonnet) — NDIS Commission report (if needed)

Standalone:
    → [7] Drafter (Sonnet)        — raw transcript → 6-section NDIS form
```

Clean notes (flagged=False) exit after step 1. Roughly 70% of notes never touch Sonnet.

---

## AI Models Used

| Model | Provider | Where Used | Why |
|-------|----------|-----------|-----|
| `au.anthropic.claude-haiku-4-5-20251001-v1:0` | AWS Bedrock | Triage, Summary | Fast cheap gate — YES/NO decisions, shift summaries |
| `au.anthropic.claude-sonnet-4-6` | AWS Bedrock | Evaluator, Incident Draft, Drafter | Complex structured reasoning, legal compliance output |
| `cohere.embed-english-v3` | AWS Bedrock | RAG embeddings | 1024-dim asymmetric embeddings for policy chunk retrieval |
| `gemini-3.5-flash` | Google AI | Context summariser, Classifier | Rolling context summaries across multiple case notes |
| `gemini-3.1-flash-live-preview` | Google AI (Live API) | Voice dictation WebSocket | Real-time conversational case note collection |

**Region**: All Bedrock calls use `ap-southeast-2` (Sydney) for Australian data residency.

---

## 7-Stage Pipeline (LangGraph)

### Stage 1 — Triage (`services/pipeline/triage.py`)
**Model**: Claude Haiku | **Max tokens out**: 512 | **Temperature**: 0.0

Reads the full case note and returns a binary gate decision plus a confidence score.

**Output schema**:
```json
{
  "flagged": true,
  "confidence": 0.92,
  "action_summary": "Staff held participant's arms to prevent self-harm"
}
```

- `flagged=False` → pipeline exits here. No RAG, no Sonnet. ~70% of notes.
- `confidence` (0.0–1.0) is logged for monitoring. High confidence = explicit restriction language. Low = ambiguous wording.
- Prompt caching: the static few-shot prefix is cached; only the transcript varies per call.

**Five regulated restrictive practices screened**:
1. Chemical Restraint — medication used to control behaviour (not for a diagnosed condition)
2. Seclusion — involuntary confinement in a room the person cannot freely leave
3. Physical Restraint — physical force restricting free movement
4. Mechanical Restraint — device used to restrict movement
5. Environmental Restraint — restricting access to parts of the environment

---

### Stage 2 — RAG (`services/pipeline/rag.py`)
**Model**: Cohere Embed English v3 | **Vector DB**: PostgreSQL + pgvector (HNSW index)

Retrieves the most relevant NDIS policy chunks to ground the evaluator. Uses the triage `action_summary` as the query (not the full transcript) — it is a clean 1-sentence description, far more semantically focused.

**Smarter RAG algorithm** (not naïve top-5):

```
1. Embed query → 1024-dimensional vector (input_type="search_query")
2. Fetch top-10 candidates from pgvector using cosine distance (<=>)
3. Filter: keep only chunks where cosine_distance < 0.35 (similarity > 0.65)
4. Cap at top-3 (not top-5)
5. Compress each chunk: strip version headers, dates, deduplicate repeated sentences
```

**Why cosine distance?**
```
cosine_distance = 1 - (A · B) / (‖A‖ · ‖B‖)
0.0 = identical vectors
2.0 = opposite vectors
< 0.35 ≈ strong semantic match (similarity > 0.65)
```

**Asymmetric embeddings**: chunks are indexed with `input_type="search_document"`, queries use `input_type="search_query"`. Cohere's v3 model is trained on asymmetric pairs — this meaningfully improves retrieval quality vs symmetric embeddings.

**Chunk compression**: before sending chunks to the evaluator, boilerplate is stripped (version headers, date lines, page references, consecutive duplicate sentences). Reduces each ~1200-char chunk by 20–35% without losing regulatory content.

**Result**: ~40% fewer evaluator input tokens on RAG context vs naïve top-5.

**Corpus**: ~300 chunks from 5 official NDIS government PDFs:
- Regulated Restrictive Practice Guide
- NDIS Practice Standards and Quality Indicators
- Code of Conduct — Provider Guidance
- Code of Conduct — Worker Guidance
- Incident Management Systems — Detailed Guidance

---

### Stage 3 — Evaluator (`services/pipeline/evaluator.py`)
**Model**: Claude Sonnet | **Max tokens out**: 8192 | **Temperature**: 0.0

Full compliance analysis grounded in the retrieved policy chunks.

**Output** (structured JSON):
```json
{
  "incident_detected": true,
  "practice_category": "Physical Restraint",
  "policy_violation_risk": "High",
  "confidence": "High",
  "reasoning": "The phrase 'held his arms' constitutes physical restraint under NDIS Rules 2018...",
  "trigger_phrases": ["held his arms", "prevented from leaving"],
  "suppression_factors": ["participant consented", "BSP referenced"],
  "bsp_mentioned_in_note": false,
  "reporting_required": true,
  "notification_timeframe": "5 business days"
}
```

**Confidence levels**:
- `High` — explicit restriction language ("held him down", "locked the door")
- `Medium` — implied or context-dependent restriction
- `Low` — ambiguous; could be non-restrictive support

**Risk levels**: Low → Medium → High → Critical

**Reporting obligations** (NDIS Rules 2018):
- Unauthorised restrictive practice → report within **5 business days**
- Serious injury or death also present → report within **24 hours**

**Prompt caching**: static prefix (style guide + few-shot examples + policy context) is cached. Only the transcript + action_summary vary per call. ~90% cost reduction on cached tokens for repeat calls within the 5-minute cache window.

---

### Stage 4 — Cross-Check (`services/pipeline/cross_check.py`)
**Model**: None (pure SQL) | **Cost**: $0

Deterministic BSP lookup — no LLM involved.

Queries the `BehaviourSupportPlan` table for the client + practice type. Returns:
- `AUTHORISED_USE` — BSP on file, practice matches, within validity window
- `UNAUTHORISED` — no BSP, expired BSP, or wrong practice type
- `NO_INCIDENT` — evaluator didn't detect an incident

---

### Stage 5 — Summary (`services/pipeline/summary.py`)
**Model**: Claude Haiku | **Runs in parallel with stages 2–4**

Generates a supervisor-facing shift overview regardless of whether a restrictive practice was detected. Includes progress observations, risk patterns, note quality score (0.0–1.0), and improvement suggestions.

---

### Stage 6 — Incident Draft (`services/pipeline/incident_draft.py`)
**Model**: Claude Sonnet | **Only runs when alert_required=True**

Generates a structured NDIS Commission incident report. Only fires when the evaluator detected an incident AND the cross-check confirmed unauthorised use. Skipped for authorised practices and clean notes.

---

### Stage 7 — Drafter (`services/pipeline/drafter.py`)
**Model**: Claude Sonnet | **Standalone endpoint: POST /draft**

Converts a raw voice transcript into the 6-section NDIS case note form. Completely separate from the evaluation pipeline — used post-dictation to structure what the worker said.

---

## RAG — How Policy Retrieval Works

### Ingestion (one-time, `scripts/ingest_ndis_policies.py`)
```
PDF → text extraction → recursive character splitting (1200 chars, 120 overlap)
    → Cohere embed (input_type="search_document") → store in NDISPolicyChunk table
```

### Query (every flagged case note)
```
triage.action_summary → Cohere embed (input_type="search_query")
    → pgvector HNSW cosine search (fetch 10)
    → distance filter (< 0.35)
    → cap at 3 chunks
    → compress (strip boilerplate)
    → pass to Evaluator
```

### pgvector HNSW index
- Algorithm: Hierarchical Navigable Small Worlds (approximate nearest neighbour)
- Distance function: cosine
- Why HNSW: O(log n) query time vs O(n) brute force. At 300 chunks the difference is negligible, but it scales cleanly to 300K chunks.

---

## Cost Optimisation — Everything We Built

### 1. Prompt Caching (Bedrock — biggest win)
**Savings: 40–60% on cached token cost**

Bedrock's `cachePoint` splits a prompt into a static prefix and a dynamic suffix. On a cache hit (within 5-minute TTL), the static tokens are charged at ~10% of normal input token price.

Applied to: triage, evaluator, summary, incident_draft, drafter.

Pattern used:
```python
# Split prompt at first dynamic placeholder
prefix_tmpl, suffix_tmpl = _PROMPT.split("{transcript}", 1)
static_prefix = prefix_tmpl.format(style_guide=..., few_shot=...)  # cached
dynamic_suffix = transcript + suffix_tmpl.format(...)               # varies

response = client.converse(
    messages=[{"role": "user", "content": [
        {"text": static_prefix},
        {"cachePoint": {"type": "default"}},   # cache boundary
        {"text": dynamic_suffix},
    ]}]
)
```

**Important**: cache only hits when the same model is called with the same static prefix within 5 minutes. In low-traffic environments, cache hit rate will be low.

### 2. Haiku Gate (triage early exit)
**Savings: ~70% of notes never touch Sonnet**

Haiku ($0.80/MTok) runs first. Only if `flagged=True` does Sonnet ($3/MTok) run. Most care notes are routine (no incident) — they cost Haiku price only.

### 3. Smarter RAG (top-10 fetch → distance filter → top-3 compressed)
**Savings: ~40% on evaluator RAG context tokens**

- Was: always return 5 chunks × ~200 tokens = 1000 tokens of policy context
- Now: fetch 10, keep only relevant ones (distance < 0.35), cap at 3 compressed = ~450 tokens
- Also: chunk compression strips 20–35% of boilerplate from each chunk

### 4. Gemini Implicit Caching
**Savings: variable (automatic in Gemini 2.5+)**

Gemini 2.5+ automatically caches repeated context. No code changes needed — the SDK handles it. Usage is tracked via `usage_metadata.cached_content_token_count`.

### 5. triage_confidence Signal (future routing)
**Current: logged only. Future: can gate incident draft.**

Triage now returns a `confidence` float (0.0–1.0). Currently used for monitoring. Future use: if `flagged=True AND confidence > 0.90 AND evaluator.confidence == HIGH`, skip incident draft (already very certain — no need for a second expensive Sonnet call).

**Why we did NOT add a Haiku evaluator path**: the evaluator requires the full transcript to extract `trigger_phrases`, `suppression_factors`, and `bsp_mention_excerpt`. Running Haiku on just the action_summary would produce fabricated phrases — unacceptable in a legal compliance context.

### What we chose NOT to do (and why)
| Approach | Why skipped |
|----------|-------------|
| Haiku evaluator for high-confidence cases | Evaluator needs full transcript for NDIS legal reporting — Haiku on 50 tokens would fabricate trigger phrases |
| Knowledge distillation | Requires model training, $30K+ cost |
| MoE routing | Too complex for ROI at current scale |
| Speculative decoding | Requires inference infrastructure control (not available on Bedrock) |
| LangSmith observability | $200-500/month — existing logs already capture all timing/token data |

---

## Token Tracking

Every LLM-backed endpoint returns a `token_usage` block:

```json
{
  "token_usage": {
    "input_tokens": 3240,
    "output_tokens": 412,
    "total_tokens": 3652
  }
}
```

### How it works (`services/usage.py`)

A `ContextVar`-based request-scoped accumulator. Each LLM call records its usage; the route reads the running total before returning.

```python
# At route entry
start_usage()

# After each LLM call (automatic — called inside triage, evaluator, etc.)
record_converse(response)   # Bedrock Converse API
record_gemini(response)     # Google Gemini

# At route return
token_usage = TokenUsage(**get_usage())
```

**Thread safety**: pipeline stages run via `asyncio.to_thread` (blocking Bedrock SDK calls offloaded to a thread pool). The accumulator uses in-place dict mutation so changes from worker threads are visible to the asyncio context. A `threading.Lock` guards concurrent stage writes.

**Why ContextVar?**: each FastAPI request runs in its own asyncio task with its own context. ContextVar is automatically scoped per-request with no manual cleanup.

**Internal cache tracking**: `get_usage_full()` returns 5 fields including `cache_read_tokens` and `cache_creation_tokens` for internal monitoring. The API only exposes 3 fields (input, output, total) — cache internals are not exposed to callers.

**IMPORTANT import rule**: always import as `from case_review.services.usage import ...`. The Docker image puts both `/app` and `/app/case_review` on `PYTHONPATH`. Importing as `services.usage` creates a second module instance with a separate ContextVar — the totals would split silently.

### Session-level tracking
`services/usage.py` also has `start_session_tracking()`, `accumulate_to_session()`, `get_session_usage()` for cumulative token totals across multiple API calls in the same session. These are implemented but not yet wired to route handlers.

---

## API Reference

### Restrictive Practices Pipeline

#### `POST /v1/restrictive-practices/evaluate`
Submit a case note for full pipeline evaluation.

**Request**:
```json
{
  "case_note_id": "uuid",
  "client_id": "string",
  "worker_id": "string",
  "transcript": "Full case note text...",
  "incident_occurred": false
}
```

**Response** (simplified):
```json
{
  "verdict": {
    "outcome": "UNAUTHORISED RESTRICTIVE PRACTICE DETECTED",
    "risk_level": "High",
    "alert_required": true
  },
  "detected_practice": {
    "category": "Physical Restraint",
    "trigger_phrases": ["held his arms"]
  },
  "reporting_obligations": {
    "must_report": true,
    "notify_within": "5 business days"
  },
  "token_usage": { "input_tokens": 3240, "output_tokens": 412, "total_tokens": 3652 }
}
```

#### `POST /v1/restrictive-practices/draft`
Convert raw voice transcript to structured NDIS form fields.

#### `POST /v1/restrictive-practices/draft/audio`
Upload audio file → Amazon Transcribe → structured form fields.

#### `POST /v1/restrictive-practices/bsp`
Create a Behaviour Support Plan record.

#### `GET /v1/restrictive-practices/bsp/{client_id}`
List all BSPs for a client.

---

### Case Review (Rolling Context)

#### `POST /v1/case-review/context`
Summarise recent case notes for a client (rolling context window).

#### `POST /v1/case-review/classify`
Classify a raw paragraph into NDIS case note fields.

---

### Voice Dictation

#### `WebSocket /v1/voice/session`
Real-time Gemini Live dictation session. Worker speaks; AI assistant guides them through form fields conversationally.

#### `POST /v1/voice/finalize`
Close a voice session and retrieve the collected note.

---

## Environment Variables

All prefixed `SENA_AI_` except where noted.

```env
# Service
SENA_AI_CASE_REVIEW_PORT=8084
SENA_AI_ENVIRONMENT=development

# Database (pgvector, port 5433)
SENA_AI_AI_DB_URL=postgresql+asyncpg://sena_ai:sena_ai@localhost:5433/sena_ai

# AWS Bedrock (Sydney — AU data residency)
SENA_AI_AWS_REGION=ap-southeast-2
SENA_AI_AWS_ACCESS_KEY_ID=
SENA_AI_AWS_SECRET_ACCESS_KEY=

# Models
SENA_AI_TRIAGE_MODEL=au.anthropic.claude-haiku-4-5-20251001-v1:0
SENA_AI_EVALUATOR_MODEL=au.anthropic.claude-sonnet-4-6
SENA_AI_EMBEDDING_MODEL=cohere.embed-english-v3

# RAG tuning
SENA_AI_RAG_TOP_K_FETCH=10          # fetch this many candidates
SENA_AI_RAG_MAX_CHUNKS=3            # keep at most this many after filtering
SENA_AI_RAG_SIMILARITY_THRESHOLD=0.35  # cosine distance cut-off

# Tiered routing
SENA_AI_TRIAGE_CONFIDENCE_THRESHOLD=0.85

# Gemini
SENA_AI_GEMINI_API_KEY=
SENA_AI_GEMINI_MODEL_ID=gemini-3.5-flash
SENA_AI_GEMINI_LIVE_MODEL_ID=gemini-3.1-flash-live-preview

# Redis (dedicated instance, separate from onboarding)
SENA_AI_CASE_REVIEW_REDIS_URL=redis://localhost:6380/0

# S3 / Transcribe (audio drafting)
S3_REGION=
S3_BUCKET=
SENA_AI_TRANSCRIPTION_BUCKET=

# Webhooks
SENA_AI_RP_WEBHOOK_URL=
SENA_AI_RP_WEBHOOK_SECRET=

# Auth
SENA_AI_AUTH_MODE=dev_header   # or jwt
```

---

## Running the Service

```bash
# From repo root
source ai-sena/bin/activate

cd services/case_review
uvicorn main:create_app --factory --host 0.0.0.0 --port 8084 --reload
```

Or via Docker Compose (always use `docker-compose.deploy.yml`, not `docker-compose.yml`):
```bash
docker compose -f docker-compose.deploy.yml up case-review
```

### Ingest NDIS policies (run once, or when PDFs change)
```bash
cd services/case_review
python scripts/ingest_ndis_policies.py
```

This chunks the 5 NDIS PDFs, embeds each chunk via Cohere, and stores them in the `ndis_policy_chunks` pgvector table.

---

## Database

**Host**: `ai-db` (PostgreSQL + pgvector extension), port 5433 (separate from main app DB on 5432).

**Key tables**:

| Table | Purpose |
|-------|---------|
| `ndis_policy_chunks` | NDIS policy text chunks with 1024-dim embeddings (HNSW cosine index) |
| `behaviour_support_plans` | Client BSP records for cross-check (Stage 4) |
| `case_note_runs` | Audit log of every pipeline run (timing, verdict, alert status) |

**Migrations**: tables are created via SQLAlchemy `create_all()` on startup (no Alembic for the AI DB). If a column is missing in production, add it with an idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` — do not run `alembic upgrade`.

---

## Project Structure

```
services/case_review/
├── main.py                          # FastAPI app factory
├── core/
│   └── settings.py                  # All env vars (pydantic-settings)
├── api/
│   ├── routes.py                    # /context, /classify endpoints
│   └── rp_routes.py                 # /evaluate, /draft, /bsp endpoints
├── models/
│   ├── schemas.py                   # All Pydantic request/response models
│   └── db.py                        # SQLAlchemy ORM (NDISPolicyChunk, BSP, CaseNoteRun)
├── services/
│   ├── usage.py                     # ★ Token accumulator (ContextVar, thread-safe)
│   ├── pipeline/
│   │   ├── graph.py                 # LangGraph wiring + run_pipeline()
│   │   ├── triage.py                # Stage 1: Haiku YES/NO gate + confidence
│   │   ├── rag.py                   # Stage 2: Smarter RAG (top-10→filter→top-3)
│   │   ├── evaluator.py             # Stage 3: Sonnet compliance verdict
│   │   ├── cross_check.py           # Stage 4: SQL BSP lookup
│   │   ├── summary.py               # Stage 5: Haiku supervisor summary
│   │   ├── incident_draft.py        # Stage 6: Sonnet NDIS incident report
│   │   ├── drafter.py               # Stage 7: Sonnet form extraction
│   │   ├── style_examples.py        # Few-shot examples + style guides (cached)
│   │   └── webhook.py               # Alert delivery (detached task)
│   ├── ingestion/
│   │   ├── embedder.py              # Cohere embed calls (async-safe via to_thread)
│   │   └── chunker.py               # Recursive character splitter (1200 chars, 120 overlap)
│   └── llm/
│       ├── classifier.py            # Gemini classifier (record_gemini called)
│       └── summarizer.py            # Gemini summariser (record_gemini called)
├── voice/
│   └── drafter.py                   # Gemini Live WebSocket handler
└── scripts/
    └── ingest_ndis_policies.py      # One-time PDF → pgvector ingest
```

---

## Realistic Cost Reduction Estimates

Based on what is actually implemented (not marketing numbers):

| Optimisation | When it saves | Estimated reduction |
|-------------|---------------|-------------------|
| Haiku triage gate | Every call | 70% of notes skip Sonnet entirely |
| Prompt caching | Cache hit within 5-min window | 40–60% on cached token cost |
| Smarter RAG (top-3 compressed) | Every flagged note | ~40% on RAG context tokens |
| Gemini implicit caching | Automatic (Gemini 2.5+) | Variable, uncontrolled |
| **Combined (busy system)** | | **~35–50% overall cost reduction** |

**To reach 10x cost reduction** you would need: pre-summarise the transcript before triage + evaluator (reducing 600-token input to ~100 tokens), high cache hit rates (>80%), and/or a fine-tuned smaller model replacing Sonnet. These have not been implemented due to compliance accuracy requirements.
