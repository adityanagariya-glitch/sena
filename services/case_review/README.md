# Case Review Service

> FastAPI + LangGraph service that automates NDIS restrictive practice detection. A support worker submits a case note (text or voice); the pipeline runs triage, retrieves NDIS policy via **hybrid RAG (BM25 + vector + Cohere reranker)**, evaluates compliance with **Bedrock tool-use structured output**, cross-checks the client's Behaviour Support Plan, and generates an incident report — all with full token tracking, per-stage stdout logging, and prompt caching across AWS Bedrock Claude. Extraction tasks (triage, classify, summarise) run on Claude Haiku; reasoning tasks (evaluate, incident draft, draft) run on Claude Sonnet; real-time voice uses Google Gemini Live.

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
    → [2] RAG (hybrid + rerank)   — BM25 + vector → RRF → Cohere rerank → parent chunks
                                     depth adapts to triage confidence (top-1 / top-3 / top-5)
    → [3] Evaluator (Sonnet)      — structured compliance verdict via tool use
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
| `au.anthropic.claude-haiku-4-5-20251001-v1:0` | AWS Bedrock | Triage, Summary, **Classifier**, **Summariser**, RAG query expansion | Fast cheap extraction — YES/NO gates, field extraction, rolling summaries |
| `au.anthropic.claude-sonnet-4-6` | AWS Bedrock | Evaluator, Incident Draft, Drafter | Complex structured reasoning, legal compliance output |
| `cohere.embed-english-v3` | AWS Bedrock | RAG embeddings | 1024-dim asymmetric embeddings for policy chunk retrieval |
| `cohere.rerank-v3-5` | AWS Bedrock (agent-runtime) | RAG reranking | Cross-encoder reranking of hybrid-search candidates |
| `gemini-3.1-flash-live-preview` | Google AI (Live API) | Voice dictation WebSocket | Real-time conversational case note collection |

**Migrated from Gemini → Bedrock Haiku**: the classifier and summariser previously called Gemini `generate_content`. They now use Bedrock Claude Haiku via **tool-use structured output** (single vendor, prompt caching, unified token tracking). The `gemini_model_id` setting is retained for backward-compat but is **passed-and-ignored** by these paths — Gemini is now used *only* for the real-time voice WebSocket (Gemini Live).

**Region**: All Bedrock calls use `ap-southeast-2` (Sydney) for Australian data residency by default (`SENA_AI_AWS_REGION`).

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
- `confidence` (0.0–1.0) **drives adaptive RAG retrieval depth** in Stage 2 (see below): high confidence fetches fewer chunks, low confidence fetches more + expands the query. It does **not** route the evaluator (Sonnet always runs on the full transcript — see "Why we did NOT add a Haiku evaluator path").
- Prompt caching: the static few-shot prefix is cached; only the transcript varies per call.

**Five regulated restrictive practices screened**:
1. Chemical Restraint — medication used to control behaviour (not for a diagnosed condition)
2. Seclusion — involuntary confinement in a room the person cannot freely leave
3. Physical Restraint — physical force restricting free movement
4. Mechanical Restraint — device used to restrict movement
5. Environmental Restraint — restricting access to parts of the environment

---

### Stage 2 — RAG (`services/pipeline/rag.py`)
**Models**: Cohere Embed English v3 (embeddings) + Cohere Rerank v3.5 (reranking) | **Vector DB**: PostgreSQL + pgvector (HNSW) + tsvector (GIN for BM25)

Retrieves the most relevant NDIS policy chunks to ground the evaluator. Uses the triage `action_summary` as the query (not the full transcript) — a clean 1-sentence description, far more semantically focused.

**Hybrid retrieval pipeline**:

```
1. Embed query → 1024-dim vector (input_type="search_query")
2. Run TWO searches in parallel:
     • Vector  — pgvector cosine (<=>) over the HNSW index   (semantic match)
     • BM25    — PostgreSQL ts_rank_cd over the tsvector GIN  (exact keyword match)
3. Merge both ranked lists with Reciprocal Rank Fusion (RRF)
4. Rerank the top candidates with Cohere Rerank v3.5 (cross-encoder)
5. For child chunks: fetch their PARENT section (full regulatory context)
6. Compress boilerplate, return the top-N to the evaluator
```

**Why hybrid?** Vector search alone misses exact strings ("section 5.2.4", "NDIS Act"); BM25 alone misses synonyms ("seclusion" vs "isolation"). Running both and fusing them catches what either signal misses on its own.

**Reciprocal Rank Fusion (RRF)** — how the two lists merge:
```
score(chunk) = Σ_i  1 / (k + rank_i(chunk))      k = 60, rank starts at 1
```
A chunk near the top of *both* the vector and BM25 lists scores highest. RRF needs only the rank position (not the raw, non-comparable cosine vs ts_rank scores), so it fuses heterogeneous signals cleanly. Each (query × signal) list is fused independently, so a chunk surfaced by several signals wins.

**Cohere Rerank v3.5 (cross-encoder)**: RRF orders by rank agreement, but a cross-encoder reads the query and each chunk *together* and scores true relevance — more accurate than any metric that embeds them separately. Called via `bedrock-agent-runtime.rerank`. If the Rerank API is unavailable in the region it **degrades gracefully** to RRF order (logs a warning, never crashes).

**Parent-child chunking**: child chunks (~300 chars) are embedded for precise retrieval; once a child matches, its **parent** (the full ~800–1500 char regulatory section) is sent to the evaluator so it sees complete context, not a truncated fragment. Legacy flat chunks (no parent) pass through unchanged.

**Adaptive retrieval depth** — driven by `triage_confidence`:

| Triage confidence | Behaviour | Rationale |
| --- | --- | --- |
| `> 0.95` | top-1 chunk, fetch 3 | Explicit violation — evaluator already knows what it is; minimal grounding |
| `0.80 – 0.95` | top-3 chunks (default) | Normal path |
| `< 0.80` | top-5 + **query expansion** | Ambiguous wording — needs more context |

**Query expansion** (low-confidence only): a small Haiku call rewrites `action_summary` into 2 alternative regulatory queries (one targeting the practice category, one the BSP/authorisation angle). Each variant is embedded **and** keyword-searched — so expansion widens *both* the semantic and keyword signals, then all lists feed RRF. Falls back to the single query if expansion fails.

**Asymmetric embeddings**: chunks are indexed with `input_type="search_document"`, queries use `input_type="search_query"`. Cohere v3 is trained on asymmetric pairs — meaningfully better retrieval than symmetric embeddings.

**Chunk compression**: before chunks reach the evaluator, boilerplate is stripped (version headers, dates, page refs, consecutive duplicate sentences) — ~20–35% smaller per chunk without losing regulatory content.

**Corpus**: 5 official NDIS government PDFs, chunked into parent sections + embedded children:
- Regulated Restrictive Practice Guide
- NDIS Practice Standards and Quality Indicators
- Code of Conduct — Provider Guidance
- Code of Conduct — Worker Guidance
- Incident Management Systems — Detailed Guidance

---

### Stage 3 — Evaluator (`services/pipeline/evaluator.py`)
**Model**: Claude Sonnet | **Max tokens out**: 8192 | **Temperature**: 0.0

Full compliance analysis grounded in the retrieved policy chunks.

**Structured output via tool use** (not prompt-and-parse): the evaluator defines a `compliance_verdict` Bedrock tool with a JSON schema and forces `toolChoice` to it. Claude must return all fields in the schema — there is **no JSON parsing or regex repair**, and malformed-output failures are eliminated. The 12 required fields are validated at the tool-call layer.

**Output** (the `compliance_verdict` tool input):
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
PDF → text extraction → semantic SECTION detection (regex; or Haiku with --llm-assist)
    → parent chunks  = full sections (~800–1500 chars, is_parent=true, no embedding)
    → child chunks   = ~300-char splits of each section (embedded for retrieval)
    → Cohere embed children (input_type="search_document")
    → store both in rp_ndis_policy_chunks (+ search_vector tsvector for BM25)
```

Section detection is regex-based by default (NDIS PDFs use numbered headings `1.`, `1.1`, ALL-CAPS). Pass `--llm-assist` to have Haiku identify section boundaries for reformatted/scanned PDFs — a one-time cost during ingest only. Sections shorter than ~200 chars are stored as flat retrievable chunks (no parent/child split).

### Query (every flagged case note)
```
triage.action_summary  →  embed (search_query)  +  (low-confidence: Haiku query expansion)
    → parallel:  vector cosine search  +  BM25 ts_rank_cd search   (per query variant)
    → Reciprocal Rank Fusion over all ranked lists
    → Cohere Rerank v3.5 (cross-encoder) → top-N
    → swap matched children for their PARENT sections
    → compress boilerplate
    → pass to Evaluator
```

### Indexes
- **pgvector HNSW** (`embedding`) — cosine, approximate nearest neighbour. O(log n) query vs O(n) brute force; scales cleanly from ~300 to 300K chunks. Only child/flat chunks are embedded (parents are fetched by FK).
- **GIN** (`search_vector`) — PostgreSQL tsvector for BM25 full-text search, populated at ingest via `to_tsvector('english', text)`.
- **Partial B-tree** (`parent_chunk_id WHERE NOT NULL`) — fast parent lookups during retrieval.

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

### 3. Hybrid RAG + reranker + parent-child (precision, fewer chunks)
**Savings: ~40% on evaluator RAG context tokens; higher recall than vector-only**

- Hybrid BM25 + vector with RRF catches matches either signal alone would miss
- Cohere cross-encoder reranking puts the genuinely-relevant chunks first, so a smaller top-N is enough
- Parent-child means we embed precise 300-char children but send the evaluator the full parent section once (deduped) — better context, no duplicate fragments
- Chunk compression strips 20–35% of boilerplate per chunk

### 4. Adaptive retrieval depth (triage_confidence — now ACTIVE, not just logged)
**Savings: ~70% fewer RAG tokens on high-confidence cases**

`triage_confidence` now actively scales RAG depth: `>0.95` fetches a single chunk (explicit violations need minimal grounding), `0.80–0.95` fetches the default 3, and `<0.80` widens to 5 and runs Haiku query expansion. Most real violations are explicit (high confidence), so the common case is the cheapest.

### 5. Single-vendor extraction on Haiku (classifier + summariser)
**Savings: consolidation + prompt caching on previously-uncached Gemini paths**

The classifier and summariser moved from Gemini `generate_content` to Bedrock Haiku tool use. This unifies token tracking, enables Bedrock prompt caching on their static prefixes, and removes a second vendor SDK from the hot path. (Gemini remains only for the real-time voice WebSocket.)

**Why we did NOT add a Haiku evaluator path**: the evaluator requires the full transcript to extract `trigger_phrases`, `suppression_factors`, and `bsp_mention_excerpt`. Running Haiku on just the action_summary would produce fabricated phrases — unacceptable in a legal compliance context. The evaluator always runs Sonnet on the full transcript; `triage_confidence` only tunes *retrieval depth*, never the evaluator itself.

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
record_and_print_converse("evaluator", response)  # Bedrock Converse — records + prints

# At route return
token_usage = TokenUsage(**get_usage())
```

> All active token recording goes through `record_and_print_converse` (every Bedrock stage). `record_gemini()` still exists in `usage.py` for the Gemini response shape but is **not currently called** — the only remaining Gemini path is the real-time voice WebSocket, whose usage is tracked by the shared `sena_common.voice` engine, not this accumulator.

**Per-stage stdout logging**: every Bedrock stage now calls `record_and_print_converse(stage, response)`, which records the usage **and** prints a one-line breakdown to stdout (captured in Docker logs). All 8 Bedrock stages print: `triage`, `evaluator`, `summary`, `incident_draft`, `drafter`, `classifier`, `summarizer`, `voice_drafter`.

```text
[tokens/triage      ] in=  245  out=  48  cached=1,840 (78% hit)  total=293
[tokens/evaluator   ] in=4,523  out= 312  cached=3,102 (41% hit)  total=4,835
```

Tail them live:
```bash
docker compose -f docker-compose.deploy.yml logs -f case-review | grep "\[tokens/"
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

#### `POST /v1/restrictive-practices/voice/session`
Create a tenant-scoped RP voice session; returns a `session_id` and the WebSocket URL.

#### `WebSocket /v1/restrictive-practices/voice/ws/{session_id}`
Real-time Gemini Live dictation. Worker speaks; the assistant guides them through the case-note form conversationally.

#### `POST /v1/case-review/voice/session` · `POST /v1/case-review/voice/draft`
Case-review voice session create + transcript-to-fields draft (Gemini Live).

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

# Models (extraction → Haiku, reasoning → Sonnet)
SENA_AI_TRIAGE_MODEL=au.anthropic.claude-haiku-4-5-20251001-v1:0
SENA_AI_EVALUATOR_MODEL=au.anthropic.claude-sonnet-4-6
SENA_AI_CLASSIFIER_MODEL=au.anthropic.claude-haiku-4-5-20251001-v1:0
SENA_AI_SUMMARIZER_MODEL=au.anthropic.claude-haiku-4-5-20251001-v1:0
SENA_AI_EMBEDDING_MODEL=cohere.embed-english-v3
# Reranker model is not env-configurable — pinned to cohere.rerank-v3-5 in embedder.py

# RAG tuning
SENA_AI_RAG_TOP_K_FETCH=10          # fetch this many candidates per signal
SENA_AI_RAG_MAX_CHUNKS=3            # default top-N after rerank (normal-confidence path)
SENA_AI_RAG_SIMILARITY_THRESHOLD=0.35  # cosine distance cut-off (legacy filter helper)
# Adaptive-depth thresholds (>0.95 → top-1, <0.80 → top-5+expansion) are code
# constants in rag.py (_HIGH_CONF_THRESHOLD / _LOW_CONF_THRESHOLD), not env vars.

# triage_confidence_threshold — retained in settings but NOT used for routing
# (the rejected Haiku-evaluator path). Adaptive RAG depth uses the rag.py constants.
SENA_AI_TRIAGE_CONFIDENCE_THRESHOLD=0.85

# Gemini (voice WebSocket only — classifier/summariser now run on Bedrock Haiku)
SENA_AI_GEMINI_API_KEY=
SENA_AI_GEMINI_MODEL_ID=gemini-3.5-flash   # passed-and-ignored by classify/summarise
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

### Startup behaviour (automatic)
On boot, `main.py`'s lifespan runs two steps before serving traffic:
1. **`alembic upgrade head`** — applies any pending migrations (idempotent; safe every boot).
2. **First-boot policy ingest** — if `rp_ndis_policy_chunks` is **empty**, it ingests the 5 NDIS PDFs with LLM-assisted chunking (**~3–5 min on first boot**; Haiku generates optimal section boundaries for the most accurate parent-child split). If the table already has rows it returns instantly. Failures are caught and logged — they never block startup.

**First Docker run will be slow** due to policy ingest. Monitor startup logs:
```bash
docker compose -f docker-compose.deploy.yml logs -f case-review | grep -E "\[startup\]|migration|NDIS|ingest"
```
Once you see `[startup] NDIS policy ingest complete`, the service is ready. Subsequent starts skip ingest entirely (table already has data).

### Ingest NDIS policies (manual — only needed if PDFs change or to force re-ingest)

**Must run inside the container.** The AI database (`ai-db-internal:5432`) is only on the Docker network — it is never published to the host, so a host-side `python scripts/...` cannot reach it (`ConnectionRefusedError` on `localhost:5433`).

```bash
cd services
docker compose -f docker-compose.deploy.yml exec sena-case-review \
  python scripts/ingest_ndis_policies.py --llm-assist   # Haiku-assisted section detection
# drop --llm-assist for fast regex-only section detection
```

This chunks the 5 NDIS PDFs into parent sections + embedded children, embeds children via Cohere, populates the BM25 `search_vector`, and upserts into the `rp_ndis_policy_chunks` pgvector table. Idempotent — safe to re-run.

> **DB config note:** the runtime data path (`config.py` → `rp_database_url`) reads `SENA_AI_RP_DATABASE_URL`, falling back to the shared `SENA_AI_AI_DB_URL` (what compose sets). Both must resolve to `ai-db-internal:5432`. If you ever see the ingest or pipeline hit `localhost:5433`, that fallback chain is broken — check the container env.

### Docker Testing

The service runs behind nginx. Test endpoints via:

**Health check** (runs immediately):
```bash
curl http://localhost/case-review/health/live
# Expected: {"status":"ok","service":"case-review","version":"0.1.0"}
```

**Watch token logging live** (per-stage breakdown):
```bash
docker compose -f docker-compose.deploy.yml logs -f case-review 2>&1 | grep "\[tokens/"
# Expected output:
#   [tokens/triage      ] in=  245  out=  48  cached=1,840 (78% hit)  total=293
#   [tokens/evaluator   ] in=4,523  out= 312  cached=3,102 (41% hit)  total=4,835
```

**Full pipeline test** — flagged note (triggers triage → RAG → evaluator):
```bash
curl -s -X POST http://localhost/case-review/v1/restrictive-practices/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "transcript": "During the afternoon shift, participant became agitated. Staff physically held the participant by the arms and guided him to his bedroom, locking the door from the outside for approximately 20 minutes until he calmed down. No behaviour support plan was referenced.",
    "worker_id": "worker-001",
    "client_id": "client-001",
    "case_note_id": "test-001",
    "tenant_id": "tenant-test"
  }' | python3 -m json.tool
# Expected in response:
#   verdict.outcome → "REPORTABLE_INCIDENT"
#   detected_practice.category → "Physical Restraint"
#   reporting_obligations.reporting_required → true
#   token_usage.total_tokens → (sum across triage, evaluator, etc.)
```

**Clean note** (should exit at triage; no RAG or evaluator):
```bash
curl -s -X POST http://localhost/case-review/v1/restrictive-practices/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "transcript": "Assisted participant with morning routine. Made breakfast together. Participant was in good spirits and chose to watch TV. Prompted hydration. Shift ended without incident.",
    "worker_id": "worker-001",
    "client_id": "client-001",
    "case_note_id": "test-002",
    "tenant_id": "tenant-test"
  }' | python3 -m json.tool
# Expected: verdict.outcome → "NOT_FLAGGED", minimal token usage
```

**Ambiguous note** (confidence < 0.80; triggers query expansion):
```bash
curl -s -X POST http://localhost/case-review/v1/restrictive-practices/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "transcript": "Participant was upset after lunch. Staff redirected him to the lounge area and stayed nearby. He settled after some time.",
    "worker_id": "worker-001",
    "client_id": "client-001",
    "case_note_id": "test-003",
    "tenant_id": "tenant-test"
  }' | python3 -m json.tool
# Expected: triage.confidence < 0.80, RAG runs with 2 query expansions
```

**Check migration ran**:
```bash
docker compose -f docker-compose.deploy.yml logs case-review 2>&1 | grep -i "migration\|alembic"
# Expected: lines showing "alembic upgrade head" and "database migrations applied"
```

**For production server** (replace `localhost` with `http://3.111.109.14:8080/case-review`):
```bash
curl http://3.111.109.14:8080/case-review/health/live
```

---

## Database

**Host**: `ai-db` (PostgreSQL + pgvector extension), port 5433 (separate from main app DB on 5432).

**Key tables**:

| Table | Purpose |
|-------|---------|
| `rp_ndis_policy_chunks` | NDIS policy chunks: parent sections + embedded children. Columns include `embedding` HALFVEC(1024) (HNSW cosine, nullable for parents), `search_vector` TSVECTOR (GIN, BM25), `parent_chunk_id` (self-FK), `is_parent` |
| `behaviour_support_plans` | Client BSP records for cross-check (Stage 4) |
| `rp_case_note_runs` | Audit log of every pipeline run (timing, verdict, alert status) |

**Migrations**: managed by **Alembic** under `migrations/versions/` (`0001`→`0005`, single linear head). `main.py` runs `alembic upgrade head` on every startup — each migration is idempotent (`CREATE TABLE / ADD COLUMN ... IF NOT EXISTS`), so it is safe to run repeatedly.

- **`0002`** creates `rp_ndis_policy_chunks` (id, chunk_id UNIQUE, text, embedding, HNSW index).
- **`0005`** adds the hybrid-search + parent-child columns: `parent_chunk_id` (self-FK, `ON DELETE CASCADE`), `is_parent` (default false), `search_vector` (TSVECTOR + GIN index), a partial index on `parent_chunk_id`, backfills `search_vector` for existing rows, and relaxes `embedding` to nullable. **Purely additive — zero-downtime on a live DB.**

`scripts/migrate_rag_schema.py` contains the same `0005` SQL as a standalone runner, for applying the schema change outside the Alembic flow if ever needed.

---

## Project Structure

```
services/case_review/
├── main.py                          # FastAPI app factory + lifespan (migrate + first-boot ingest)
├── core/
│   └── settings.py                  # All env vars (pydantic-settings)
├── api/
│   ├── routes.py                    # /context, /classify endpoints
│   └── rp_routes.py                 # /evaluate, /draft, /bsp, /voice endpoints
├── models/
│   ├── schemas.py                   # All Pydantic request/response models
│   └── db.py                        # SQLAlchemy ORM (NDISPolicyChunk +parent/child/tsvector, BSP, CaseNoteRun)
├── migrations/
│   └── versions/                    # Alembic 0001→0005 (0005 = hybrid-search + parent-child schema)
├── services/
│   ├── usage.py                     # ★ Token accumulator (ContextVar) + record_and_print_converse
│   ├── pipeline/
│   │   ├── graph.py                 # LangGraph wiring + run_pipeline()
│   │   ├── triage.py                # Stage 1: Haiku YES/NO gate + confidence (drives RAG depth)
│   │   ├── rag.py                   # Stage 2: hybrid BM25+vector → RRF → rerank → parent-fetch
│   │   ├── evaluator.py             # Stage 3: Sonnet verdict via tool-use structured output
│   │   ├── cross_check.py           # Stage 4: SQL BSP lookup
│   │   ├── summary.py               # Stage 5: Haiku supervisor summary
│   │   ├── incident_draft.py        # Stage 6: Sonnet NDIS incident report
│   │   ├── drafter.py               # Stage 7: Sonnet form extraction
│   │   ├── style_examples.py        # Few-shot examples + style guides (cached)
│   │   └── webhook.py               # Alert delivery (detached task)
│   ├── ingestion/
│   │   ├── embedder.py              # Cohere embed + rerank_chunks + upsert (search_vector/parent/child)
│   │   └── chunker.py               # Semantic parent-child chunking (regex / Haiku --llm-assist)
│   └── llm/
│       ├── classifier.py            # Bedrock Haiku classifier (tool use + cachePoint)
│       └── summarizer.py            # Bedrock Haiku summariser (tool use + cachePoint)
├── voice/
│   └── drafter.py                   # Gemini Live WebSocket handler
└── scripts/
    ├── ingest_ndis_policies.py      # PDF → pgvector ingest (--llm-assist optional)
    └── migrate_rag_schema.py        # Standalone 0005 schema migration (Alembic alternative)
```

---

## Realistic Cost Reduction Estimates

Based on what is actually implemented (not marketing numbers):

| Optimisation | When it saves | Estimated reduction |
|-------------|---------------|-------------------|
| Haiku triage gate | Every call | 70% of notes skip Sonnet entirely |
| Prompt caching | Cache hit within 5-min window | 40–60% on cached token cost |
| Hybrid RAG + rerank + compression | Every flagged note | ~40% on RAG context tokens (fewer, better chunks) |
| Adaptive retrieval depth | High-confidence flagged notes | ~70% fewer RAG tokens (top-1 vs top-3/5) |
| Haiku for classify/summarise + caching | Context + classify endpoints | Single vendor; cacheable static prefixes |
| **Combined (busy system)** | | **~35–50% overall cost reduction** |

**To reach 10x cost reduction** you would need: pre-summarise the transcript before triage + evaluator (reducing 600-token input to ~100 tokens), high cache hit rates (>80%), and/or a fine-tuned smaller model replacing Sonnet. These have not been implemented due to compliance accuracy requirements.
