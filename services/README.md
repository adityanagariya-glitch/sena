# SENA AI Services — Models & Langfuse Instrumentation

Comprehensive reference for all AI models and Langfuse tracking tags across SENA services (2026-07-02).

---

## 0. Service Directory & API Docs

| Service | Port | API Docs |
|---------|------|----------|
| **ai-chatbot (gateway)** | 8003 | [http://3.111.109.14:8080/ai-chatbot/docs](http://3.111.109.14:8080/ai-chatbot/docs) |
| **staff** | 8001 | [http://3.111.109.14:8080/staff/docs](http://3.111.109.14:8080/staff/docs) |
| **policy-proc** | 8000 | [http://3.111.109.14:8080/policy/docs](http://3.111.109.14:8080/policy/docs) |
| **case-review** | 8002 | [http://3.111.109.14:8080/case-review/docs](http://3.111.109.14:8080/case-review/docs) |
| **casenote-monthly (PSR)** | 8004 | [http://3.111.109.14:8080/casenote/docs](http://3.111.109.14:8080/casenote/docs) |
| **ai-communication-log** | 8005 | [http://3.111.109.14:8080/ai-comm-log/docs](http://3.111.109.14:8080/ai-comm-log/docs) |
| **ai-text-extraction** | 8007 | [http://3.111.109.14:8080/text-extraction/docs](http://3.111.109.14:8080/text-extraction/docs) |
| **onboarding** | 8009 | [http://3.111.109.14:8080/onboarding/docs](http://3.111.109.14:8080/onboarding/docs) |
| **voice** | 8008 | [http://3.111.109.14:8080/voice/docs](http://3.111.109.14:8080/voice/docs) |
| **shift-summary** | 8006 | [http://3.111.109.14:8080/shift-summary/docs](http://3.111.109.14:8080/shift-summary/docs) |
| **doc-service** | 8010 | [http://3.111.109.14:8080/doc-service/docs](http://3.111.109.14:8080/doc-service/docs) |
| | | |
| **Infrastructure** | **Port** | **Details** |
| **ai-db** (pgvector) | 5432 | AI pipeline database with vector extensions (case_review, voice) |
| **shared-db** (PostgreSQL) | 5433 | Platform-wide shared database (user/org context, onboarding state) |
| **redis** | 6979 | Session cache + transcript persistence (voice, onboarding) |

---

### Infrastructure Components

#### ai-db (PostgreSQL pgvector)
- **Port**: 5432 (internal container network)
- **Image**: `pgvector/pgvector:pg16`
- **Database**: `sena_ai` (user: `sena_ai`)
- **Purpose**: 
  - Vector storage for RAG embeddings (pgvector extension)
  - Case review incident data, evaluations, drafts
  - Voice session metadata (DictationSession, DictationTurn, ApprovalQueueItem)
- **Used By**: case_review, voice, doc_service
- **Schema**: Created via SQLAlchemy `create_all()` from models in `models/db.py`
- **Note**: Schema drift from deployed state is common — use idempotent ALTER statements, not alembic

#### shared-db (PostgreSQL)
- **Port**: 5433 (internal container network; distinct from ai-db:5432)
- **Image**: `postgres:16-alpine`
- **Database**: `platform` (user: `shared`)
- **Purpose**:
  - Platform-wide identity: staff, participants, organizations, roles
  - Onboarding context & state: FormState, prior steps, cross-screen context
  - Shared reference data (not service-specific)
- **Used By**: onboarding, voice (for participant context)
- **Consumer**: Only voice service imports `SHARED_DB_URL` (explicitly configured in compose)

#### Redis (Cache & Session Store)
- **Port**: 6979 (internal container network)
- **Image**: `redis:7.4-alpine`
- **Purpose**:
  - Voice session state: transcript, field values, validation errors (db=0)
  - Case review Redis cache: transient data (db=1, separate namespace)
  - Fast access for real-time APIs (WebSocket, dictation)
- **Persistence**: Append-only mode (`--appendonly yes`)
- **Used By**: voice, case_review
- **Namespacing**: Separate logical databases (0, 1) prevent key collisions

---

## 1. Models & Versions

### Bedrock (AWS)

| Model | Model ID | Type | Used In |
|-------|----------|------|---------|
| Claude Sonnet 4.6 | `au.anthropic.claude-sonnet-4-6` | Text LLM | case_review, policy_proc (judge), voice, staff, casenote_monthly |
| Claude Sonnet 4.5 | `au.anthropic.claude-sonnet-4-5-20250929-v1:0` | Text LLM | ai-communication-log |
| Claude Haiku 4.5 | `au.anthropic.claude-haiku-4-5-20251001-v1:0` | Text LLM | case_review (triage/classifier/summarizer), policy_proc (generator), shift-summary |
| Amazon Nova Lite | `apac.amazon.nova-lite-v1:0` | Text/Vision LLM | ai-text-extraction |
| Amazon Nova Micro | `apac.amazon.nova-micro-v1:0` | Reranking LLM | policy_proc (nova reranker path) |
| Amazon Titan Embed | `amazon.titan-embed-text-v2:0` | Embeddings | policy_proc (RAG embeddings) |
| Cohere Embed | `cohere.embed-english-v3` | Embeddings | case_review (RAG chunk embeddings) |
| Cohere Rerank v3.5 | `cohere.rerank-v3-5:0` | Reranking | case_review (RAG cross-encoder) |
| Amazon Rerank v1 | `amazon.rerank-v1:0` | Reranking | policy_proc (amazon reranker path, default) |

### Google Gemini

| Model | Model ID | Type | Used In |
|-------|----------|------|---------|
| Gemini Flash Live 3.1 | `gemini-3.1-flash-live-preview` | Audio LLM (WebSocket) | onboarding, voice, shared |
| Gemini Flash 3.5 | `gemini-3.5-flash` | Text LLM (REST) | voice (personal details), case_review |

---

## 2. Service → Model Mapping

### onboarding
- **Gemini Live**: `gemini-3.1-flash-live-preview` (audio/voice only, WebSocket)
- **Audio pricing**: $3.00/$12.00 per 1M tokens (input/output)
- **Text pricing**: $0.75/$4.50 per 1M tokens (asymmetric split in Langfuse tags)

### voice

- **Bedrock Claude Sonnet**: `au.anthropic.claude-sonnet-4-6` (dictation / case notes)
- **Gemini (text)**: `gemini-3.5-flash` (personal details collection)
- **Gemini Live**: `gemini-3.1-flash-live-preview` (audio sessions — WebSocket only, no fallback)

### case_review

- **Bedrock Claude Sonnet**: `au.anthropic.claude-sonnet-4-6` (evaluator, incident draft)
- **Bedrock Claude Haiku**: `au.anthropic.claude-haiku-4-5-20251001-v1:0` (triage, chunking, summarizer, classifier)
- **Cohere Embed**: `cohere.embed-english-v3` (RAG embeddings, search_document + search_query asymmetric)
- **Cohere Rerank**: `cohere.rerank-v3-5:0` (RAG cross-encoder reranking, per-query billing)

### policy_proc
- **Amazon Nova Micro**: `apac.amazon.nova-micro-v1:0` (CLASSIFIER_MODEL — query classification; also RERANKER_MODEL nova path)
- **Amazon Nova Lite**: `apac.amazon.nova-lite-v1:0` (REWRITER_MODEL — query rewriting)
- **Bedrock Claude Haiku**: `au.anthropic.claude-haiku-4-5-20251001-v1:0` (GENERATION_MODEL — final answer generation)
- **Bedrock Claude Sonnet**: `au.anthropic.claude-sonnet-4-6` (JUDGE_MODEL — evaluation, quality checks)
- **Amazon Titan Embed**: `amazon.titan-embed-text-v2:0` (EMBED_MODEL — RAG embeddings)
- **Amazon Rerank**: `amazon.rerank-v1:0` (default reranker path, per-query billing; RERANK_REGION=ap-northeast-1)

### staff
- **Bedrock Claude Sonnet**: `au.anthropic.claude-sonnet-4-6` (MODEL_ID — client agent)

### casenote_monthly
- **Bedrock Claude Sonnet**: `au.anthropic.claude-sonnet-4-6` (MODEL_ID — report generation)

### ai-communication-log
- **Bedrock Claude Sonnet**: `au.anthropic.claude-sonnet-4-5-20250929-v1:0` (BEDROCK_MODEL_ID — sentiment analysis, classification; applies to both `app/` and `ai-classifier/app/` trees)

### ai-text-extraction
- **Amazon Nova Lite**: `apac.amazon.nova-lite-v1:0` (BEDROCK_MODEL_ID — document extraction; NOT a Claude model)

### shift-summary
- **Bedrock Claude Haiku**: `au.anthropic.claude-haiku-4-5-20251001-v1:0` (bedrock_model_id — consolidate/summarize shift notes)

### ai_chatbot
- **No active LLM** — pure routing gateway. Orchestrates staff, policy, and other services.
- `BEDROCK_MODEL_ID` is defined in `config_middleware.py` but the LLM call code in `router.py` (converse/invoke_model) is fully **commented out** — the gateway does not invoke Bedrock directly.

---

## 3. Langfuse Tags Dictionary

### onboarding
```python
# Service-level tags (metadata.service) — distinguished by JWT typeContext
"onboarding_staff_voice"  # Staff member using onboarding voice (userType="organizationMember" AND staffType not null)
"onboarding_client_voice" # Client/participant using onboarding voice (else)

# Session-level observations (dynamic names)
"onboarding-live-session_staff"   # Session span for staff
"onboarding-live-session_client"  # Session span for client
"onboarding-live-session_all"     # Fallback (if user type cannot be determined)

# Turn-level observations (dynamic names)
"onboarding-turn_staff"           # Per-turn generation for staff
"onboarding-turn_client"          # Per-turn generation for client
"onboarding-turn_all"             # Fallback (if user type cannot be determined)
```

### voice
```python
# Metadata tags (metadata.service) — service-level grouping
"voice_dictation"               # Bedrock Claude Sonnet (case note dictation)
"voice_personal_details_gemini" # Gemini 3.5-flash REST (personal details collection)
"voice_live"                    # Gemini Live 3.1 WebSocket (audio sessions)

# Observation spans (Langfuse @observe names) — individual operation traces
"voice-bedrock-invoke"          # Bedrock Claude invoke — synchronous API call for dictation
"personal-details-gemini"       # Gemini 3.5-flash REST call — personal details collection
"voice-live-turn"               # Gemini Live WebSocket turn — per-audio-turn processing
"voice-dictation"               # Dictation span — separate from bedrock-invoke if tracked independently
```

### ai-text-extraction
```python
# Metadata tag (metadata.service) — for filtering/grouping in dashboard
"ai-text-extraction"         # Document extraction service (Amazon Nova Lite)

# Observation spans (Langfuse @observe names) — individual operation traces
"document-extract"           # Amazon Nova Lite extraction — structured document parsing
"text-extraction"            # Top-level extraction orchestration — handles format routing & aggregation
```

### case_review (Langfuse)

```python
# Turn-level observation (shared engine)
"case-review-update"              # Per-turn generation for voice case-note dictation

# Service-level tags (metadata.service) — Gemini Live audio/text split
"case_review_voice"               # Voice dictation feature (Gemini Live 3.1)
                                  # Usage split: input/output (text), input_audio/output_audio (audio surcharge)

# Ingestion & embedding
"case_review_ingest_chunker"      # LLM-assisted section detection on ingest
"case_review_embed"               # Cohere Embed (search_document + search_query)

# RAG retrieval
"case_review_rag_query_expansion" # Query expansion for low-confidence retrievals

# Evaluation & drafting
"case_review_triage"              # Triage (incident vs non-incident)
"case_review_evaluator"           # Multi-eval (PRS, custody, drugs, risk)
"case_review_incident_draft"      # Incident report draft generation
"case_review_incident_splitter"   # Draft → narrative + findings split
"case_review_shift_summary"       # Shift context summarization
"case_review_classifier"          # Classify incident type (DISTINCT from summarizer)
"case_review_summarizer"          # Summarize support/safeguarding (DISTINCT from classifier)
"case_review_rp_drafter"          # Restrictive practice drafting (if applicable)

# Main case_review namespace (Langfuse managed prompts)
"case_review"                     # Prompt namespace — do NOT rename
```

### policy_proc (Pipeline)
```python
# Service-level tags (metadata.service) — all use _SERVICE = "policy_proc"
"policy_proc_classifier"          # Classify user query (staff vs policy) — obs: "policy-proc-classify"
"policy_proc_rewriter"            # Rewrite query for better RAG retrieval — obs: "policy-proc-rewrite"
"policy_proc_generator"           # Generate final response from retrieved docs — obs: "policy-proc-generate"
"policy_proc_reranker_amazon"     # Amazon Rerank v1.0 cross-encoder — obs: "policy-proc-rerank-amazon"
"policy_proc_reranker_nova"       # Nova Rerank alternative path — obs: "policy-proc-rerank-nova"
"policy_proc_rag"                 # RAG retrieval (implicit, not tagged separately)

# High-level pipeline orchestration (Langfuse @observe names)
"rag-pipeline-policy-proc-sync"   # Synchronous RAG pipeline — validate → classify → block-check → memory → retrieve → generate → save
"rag-pipeline-policy-proc"        # Streaming RAG pipeline — same 7-step flow but yields tokens real-time (better UX for long answers)

# Main policy_proc namespace (Langfuse managed prompts)
"policy_proc"                     # Prompt namespace — do NOT rename
```

### staff

```python
# Metadata tag (metadata.service) — for filtering/grouping in dashboard
"staff-client"               # Staff agent service — complete query → response flow

# Observation span (Langfuse @observe name) — individual operation trace
"staff-client-query"         # Client query → agent decides tools → Bedrock generates response
                             # (Agent loop: classify intent → select tools → run → loop back until done)
                             # (Covers all variants: sync, streaming, async, async+streaming internally)
```

### casenote_monthly
```python
# Metadata tag (metadata.service) — for filtering/grouping in dashboard
"casenote_monthly"           # Monthly casenote report generation (consolidated tag)

# Observation spans (Langfuse @observe names) — individual operation traces
"casenote-generate"          # Bedrock Claude Sonnet generation — synchronous API call
"casenote-monthly-section"   # Monthly section generation — api_main.py multi-section loop
"casenote-section"           # Individual section generation — run_prompts.py per-section processing
```

### shift-summary
```python
# Metadata tag (metadata.service) — for filtering/grouping in dashboard
"shift-summary"              # Consolidate/summarize shift notes (claude-haiku)

# Observation spans (Langfuse @observe names) — individual operation traces
"shift-summary-consolidate"  # Bedrock Claude Haiku consolidation — summarize shift notes across time period
```

### ai_chatbot
```python
# NO LANGFUSE INSTRUMENTATION
# Pure routing gateway — no direct LLM invocation (code is commented out)
# Downstream services (staff, policy_proc, etc.) have their own Langfuse tags
```

### ai-communication-log
```python
# Service-level tags (metadata.service) — consolidated to single _SERVICE = "ai_communication_log"
"ai_communication_log"       # Sentiment analysis & classification (both ai-classifier/ and app/ trees)
```

### ai-text-extraction
```python
"ai-text-extraction"         # Document text extraction
```

### voice (module-level; shared across services)
```python
"voice"                      # Langfuse prompt namespace — do NOT rename
```

---

## 4. Token Accounting by Model Type

### Bedrock (AWS Anthropic)
- **Input/Output**: Standard token counting via response.usage
- **Cached reads/writes**: Tracked separately (Langfuse sums automatically)
  - `input_tokens`: Direct input
  - `cache_creation_input_tokens`: Written to cache
  - `cache_read_input_tokens`: Read from cache
- **Langfuse cost**: Sums all variants into `total_tokens`; pricing applied per-token-type

### Gemini Live (Audio/WebSocket)
- **Split pricing**: Audio tokens cost 4x more than text
  - `input_audio`: 4-token cost multiplier vs text
  - `output_audio`: 4-token cost multiplier vs text
  - `input`: Text tokens (no audio surcharge)
  - `output`: Text tokens (no audio surcharge)
- **Langfuse usage_details keys**: Must match pricingTiers in model definition
- **Example (gemini-3.1-flash-live-preview)**:
  ```json
  {
    "input": 200,           // text tokens @ $0.75/1M
    "output": 50,           // text tokens @ $4.50/1M
    "input_audio": 2800,    // audio tokens @ $3.00/1M
    "output_audio": 120     // audio tokens @ $12.00/1M
  }
  ```

### Gemini REST (Text/HTTP)
- **No audio**: Standard input/output tokens only
- **Langfuse usage_details keys**: `input`, `output` (no audio variants)

### Cohere Embed
- **Billing**: Per input token only (estimate via 4-char-per-token heuristic when API response lacks usage field)
- **Langfuse usage_details keys**: `{"input": estimated_tokens}`
- **Asymmetric**: `search_document` vs `search_query` input types (different embeddings, tracked separately in metadata)

### Cohere Rerank
- **Billing**: Per query, not per token; 1 query covers up to 100 document chunks
- **Langfuse usage_details keys**: `{"queries": ceil(chunk_count / 100)}`
- **Pricing**: $0.002 per query = $2.00 per 1,000 queries

### Amazon Rerank
- **Billing**: Per query (same as Cohere Rerank)
- **Langfuse usage_details keys**: `{"queries": query_count}`
- **Pricing**: $0.001 per query = $1.00 per 1,000 queries
- **matchPattern**: `(?i)^amazon\.rerank-v1:0$` (must match actual model ID string in code)

---

## 5. Langfuse Model Definitions

### Bedrock Models
| Model | Pricing (Input/Output) | Notes |
|-------|------------------------|-------|
| claude-sonnet-4-6 | $3.00/$15.00 per 1M | General-purpose |
| claude-sonnet-4-5-20250929-v1:0 | $3.00/$15.00 per 1M | ai-communication-log |
| claude-haiku-4-5-20251001-v1:0 | $1.00/$5.00 per 1M | Lightweight |
| apac.amazon.nova-lite-v1:0 | $0.063/$0.252 per 1M | ai-text-extraction (vision-capable); APAC cross-region rate |
| apac.amazon.nova-micro-v1:0 | $0.037/$0.148 per 1M | policy_proc classifier + nova reranker; APAC cross-region rate |

### Gemini Models
| Model | Pricing (Input/Output) | Notes |
|-------|------------------------|-------|
| gemini-3.1-flash-live-preview | Text: $0.75/$4.50; Audio: $3.00/$12.00 per 1M | Audio split via usage_details keys |
| gemini-3.5-flash | $1.50/$9.00 per 1M | REST API only, text |

### Embedding & Reranking
| Model | Billing | Pricing | Notes |
|-------|---------|---------|-------|
| cohere.embed-english-v3 | Per input token | $0.10 per 1M | Asymmetric (search_document vs search_query) |
| amazon.titan-embed-text-v2:0 | Per input token | $0.02 per 1M | policy_proc RAG embeddings |
| cohere.rerank-v3-5:0 | Per query (100 docs/query) | $2.00 per 1K queries | Query-unit based |
| amazon.rerank-v1:0 | Per query (100 docs/query) | $1.00 per 1K queries | Query-unit based |

---

## 6. How to Query Langfuse by Service

### Filter by Langfuse Service Tag

```bash
# Langfuse CLI
export LANGFUSE_PUBLIC_KEY="pk-lf-..."
export LANGFUSE_SECRET_KEY="sk-lf-..."
export LANGFUSE_HOST="https://cloud.langfuse.com"

# List all generations for a specific service
npx langfuse-cli api observations --limit 100 --filter 'metadata.service = "onboarding_staff_voice"'

# List case_review pipeline stages
npx langfuse-cli api observations --limit 100 --filter 'metadata.service contains "case_review_"'
```

### Langfuse Dashboard Filters

| Service | Filter |
|---------|--------|
| **Onboarding (all)** | `metadata.service contains "onboarding"` |
| **Onboarding (staff only)** | `metadata.service = "onboarding_staff_voice"` |
| **Onboarding (client only)** | `metadata.service = "onboarding_client_voice"` |
| **Voice Live Audio** | `metadata.service = "voice_live"` |
| **Case Review (all)** | `metadata.service contains "case_review"` |
| **Case Review Embedding** | `metadata.service = "case_review_embed"` |
| **Case Review Evaluation** | `metadata.service = "case_review_evaluator"` |
| **Policy Proc (all)** | `metadata.service contains "policy_proc"` |
| **Staff Agent** | `metadata.service = "staff"` |

---

## 7. Common Gotchas & Fixes

### Naming Consistency
- **Do**: Use distinct service tags for different models/features in the same codebase
  - `case_review_classifier` vs `case_review_summarizer` (same service, different models)
  - `voice_personal_details_gemini` vs `voice_dictation_bedrock` (same capability, different models)
- **Don't**: Use generic tags that collide across services
  - Both files named `bedrock_service.py` shouldn't use generic `"voice"` tag

### Audio vs Text Token Split (Gemini Live)
- **Langfuse usage_details keys** must match **model pricingTiers**
  - Use `input`, `output`, `input_audio`, `output_audio` (keys match pricingTiers)
  - Don't mix `input_text`/`output_text` with `input_audio`/`output_audio`
- **Why**: Langfuse calculates cost = sum(usage[key] * pricingTiers[key])
  - If key is missing from pricingTiers, token count is silently ignored (cost = $0)

### Rerank Query Counting
- **Amazon & Cohere Rerank**: Billed per query, not per token
  - `usage_details = {"queries": ceil(chunk_count / 100)}`
  - Don't use `{"input": chunk_count}` (would be massive cost)
- **Why**: 1 query covers up to 100 document chunks; overhead is amortized per-query

### Prompt Namespace vs Service Tag
- **Langfuse managed prompts** use `_SERVICE` variable (prompt namespace, not dashboard tag)
  - `case_review` — prompt namespace (must NOT rename, breaks managed-prompt lookups)
  - `case_review_classifier` — dashboard tag (distinct from `case_review_summarizer`)
- **Lesson**: Keep them separate; namespace is for prompt git-syncing, tag is for dashboard filtering

### JWT Role Extraction (Onboarding Staff vs Client)
- **Staff**: `typeContext.userType = "organizationMember"` & `typeContext.staffType != null`
  - Tags as: `"onboarding_staff_voice"`
- **Client**: `typeContext.userType = "serviceProvider"` OR `staffType = null`
  - Tags as: `"onboarding_client_voice"`
- **How to check**: JWT decoded payload in Langfuse → click trace → metadata.service

---

## 8. Quick Reference: Service → Tag → Model

```
┌─────────────────────────────────────────────────────────────────────────┐
│ ONBOARDING                                                              │
├─────────────────────────────────────────────────────────────────────────┤
│ Tag: onboarding_staff_voice / onboarding_client_voice                   │
│ Model: gemini-3.1-flash-live-preview                                   │
│ Billing: Audio-only, $3.00/$12.00 per 1M (input_audio/output_audio)    │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│ VOICE                                                                   │
├─────────────────────────────────────────────────────────────────────────┤
│ Tag: voice_dictation (case note dictation)                             │
│ Model: claude-sonnet-4-6                                               │
│ Billing: $3.00/$15.00 per 1M                                           │
│                                                                         │
│ Tag: voice_personal_details_gemini (personal details collection)       │
│ Model: gemini-3.5-flash                                                │
│ Billing: $1.50/$9.00 per 1M                                            │
│                                                                         │
│ Tag: voice_live (Gemini Live WebSocket audio sessions)                 │
│ Model: gemini-3.1-flash-live-preview                                   │
│ Billing: Audio $3.00/$12.00, Text $0.75/$4.50 per 1M                   │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│ CASE_REVIEW (10-component pipeline)                                     │
├─────────────────────────────────────────────────────────────────────────┤
│ Ingestion:                                                              │
│   case_review_ingest_chunker → claude-haiku                            │
│   case_review_embed → cohere.embed-english-v3 ($0.10/1M)               │
│                                                                         │
│ Evaluation:                                                             │
│   case_review_triage → claude-haiku                                    │
│   case_review_evaluator → claude-sonnet ($3.00/$15.00/1M)              │
│   case_review_incident_draft → claude-sonnet                           │
│   case_review_incident_splitter → claude-haiku                         │
│   case_review_shift_summary → claude-haiku                             │
│   case_review_classifier → claude-haiku                                │
│   case_review_summarizer → claude-haiku                                │
│                                                                         │
│ RAG:                                                                    │
│   case_review_rag_query_expansion → claude-haiku (low-confidence)      │
│   case_review_embed → cohere.rerank-v3-5:0 ($2.00/1K queries)          │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│ POLICY_PROC (5-stage RAG)                                               │
├─────────────────────────────────────────────────────────────────────────┤
│ policy_proc_classifier → nova-micro-v1:0 (staff/policy/both)           │
│ policy_proc_rewriter → nova-lite-v1:0 (query rewrite)                  │
│ policy_proc_rag → titan-embed-text-v2:0 (vector search embeddings)     │
│ policy_proc_reranker_amazon → amazon.rerank-v1:0 ($1.00/1K queries)    │
│ policy_proc_reranker_nova → nova-micro-v1:0 (LLM-based rerank)         │
│ policy_proc_generator → claude-haiku-4-5 (final response)              │
│ (JUDGE_MODEL claude-sonnet-4-6 — offline eval only, not in hot path)   │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│ STAFF (Agent)                                                           │
├─────────────────────────────────────────────────────────────────────────┤
│ Tag: staff                                                              │
│ Model: claude-sonnet-4-6                                               │
│ Billing: Tool-calling loop, $3.00/$15.00 per 1M                        │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│ CASENOTE_MONTHLY                                                        │
├─────────────────────────────────────────────────────────────────────────┤
│ Tag: casenote_monthly_report                                            │
│ Model: claude-sonnet-4-6                                               │
│ Billing: $3.00/$15.00 per 1M                                           │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│ AI-COMMUNICATION-LOG                                                    │
├─────────────────────────────────────────────────────────────────────────┤
│ Tag: ai_communication_log                                               │
│ Model: claude-sonnet-4-5-20250929-v1:0                                 │
│ Billing: $3.00/$15.00 per 1M                                           │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│ AI-TEXT-EXTRACTION                                                      │
├─────────────────────────────────────────────────────────────────────────┤
│ Tag: ai-text-extraction                                                 │
│ Model: apac.amazon.nova-lite-v1:0 (NOT Claude)                         │
│ Billing: $0.063/$0.252 per 1M                                          │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│ SHIFT-SUMMARY                                                           │
├─────────────────────────────────────────────────────────────────────────┤
│ Tag: shift-summary                                                      │
│ Model: claude-haiku-4-5                                                │
│ Billing: $1.00/$5.00 per 1M                                            │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│ AI_CHATBOT (Gateway)                                                    │
├─────────────────────────────────────────────────────────────────────────┤
│ Tag: ai-chatbot                                                         │
│ Model: NONE — LLM code commented out, pure routing gateway             │
│ Billing: n/a (routes to staff / policy / other services)              │
└─────────────────────────────────────────────────────────────────────────┘
```
