# Policy Processing Service (policy_proc)

> FastAPI service that provides RAG-based question answering over NDIS policy and procedure documents. Combines Bedrock Knowledge Base retrieval, dual-stage reranking (Amazon Reranker + Nova), and Claude Haiku generation with multi-turn memory. Includes a Streamlit UI, admin document ingestion endpoints, and SSE streaming responses. Also deployable as an AWS Lambda function.

---

## Table of Contents
- [Overview](#overview)
- [How It Works](#how-it-works)
- [Tech Stack](#tech-stack)
- [API Reference](#api-reference)
- [Environment Variables](#environment-variables)
- [Running the Service](#running-the-service)
- [Integration Guide](#integration-guide)
- [QA & Testing](#qa--testing)
- [Implementation Status](#implementation-status)
- [Integration Requirements](#integration-requirements)

---

## Overview

Support workers and coordinators can ask plain-language questions about NDIS policies, procedures, and organisational documents (e.g., "What is the process for reporting a restrictive practice?", "What does the manual handling policy say about two-person assists?"). This service retrieves the most relevant document chunks from a managed Bedrock Knowledge Base, reranks them, generates an answer using Claude, and streams it back token-by-token.

Documents are uploaded to S3 and ingested into the Bedrock Knowledge Base via admin endpoints. Each organisation has its own isolated document namespace — coordinators can only access their org's documents.

---

## How It Works

```
POST /query/stream
  ├─ Validate JWT, extract user + role
  ├─ Block if role == "blocked"
  │
  ├─ Classify intent: NDIS / GREETING / SENSITIVE / OFF_TOPIC / HARMFUL
  │   ├─ GREETING → direct response (no retrieval)
  │   ├─ SENSITIVE / OFF_TOPIC / HARMFUL → blocked response
  │   └─ NDIS → continue pipeline
  │
  ├─ Rewrite query for better retrieval
  ├─ Retrieve from Bedrock KB (vector search, filtered by org_id + doc_type)
  ├─ Rerank: Amazon Reranker or Nova Micro (top 8 from 20 retrieved)
  ├─ Load last 5 conversation turns from DynamoDB (memory)
  ├─ Generate answer with Claude Haiku (streaming)
  ├─ Persist turn to DynamoDB + AgentCore
  └─ Stream SSE events: meta → tokens → usage → done
```

---

## Pipeline Components

The query-to-response pipeline is broken into 5 core stages, each with its own module for testability and independent scaling:

### 1. **classifier.py** — Intent Classification

- **Function:** `classify(question: str) → Dict[str, Any]`
- **Role:** Determines question type before retrieval
- **Classes:** `NDIS` (policy questions), `GREETING`, `SENSITIVE`, `OFF_TOPIC`, `HARMFUL`
- **Model:** AWS Bedrock — Nova Micro
- **Logic:** Blocks sensitive/harmful queries early; greetings get direct responses (no KB retrieval)

### 2. **rewriter.py** — Query Rewriting

- **Function:** `rewrite_query(question: str, history: list) → str`
- **Role:** Rewrites user query for better retrieval signal
- **Techniques:** Expands abbreviations, corrects typos, adds context from conversation history
- **Model:** AWS Bedrock — Nova Lite
- **Benefit:** Improves KB hit rates by ~15–20% (e.g., "WHS" → "workplace health and safety")

### 3. **generator.py** — Response Generation

- **Function:** `generate_stream(reranked_docs: list, history: list, question: str) → AsyncIterator[str]`
- **Role:** Generates streamed SSE response token-by-token
- **Model:** AWS Bedrock — Claude Haiku
- **Features:**
  - Streaming (never returns full response; yields tokens as they arrive)
  - Citation tracking (marks which docs informed each claim)
  - Conversation context (uses last 5 turns from DynamoDB)
  - Usage telemetry (token count, latency, cost)

### 4. **amazon_reranker.py** — Semantic Reranking (Primary)

- **Function:** `rerank_with_amazon(docs: list[Dict], question: str, top_k: int = 8) → list[Dict]`
- **Role:** Re-scores top 20 retrieved docs, returns top 8 most relevant
- **Model:** AWS Bedrock — Amazon Reranker (`amazon.rerank-v1:0`)
- **Region:** `ap-northeast-1` (Tokyo — latency-optimized for this model)
- **Score:** Semantic relevance (0–1 float, higher = more relevant)

### 5. **nova_reranker.py** — Semantic Reranking (Fallback)

- **Function:** `rerank_with_nova(docs: list[Dict], question: str, top_k: int = 8) → list[Dict]`
- **Role:** Fallback reranker if Amazon Reranker is unavailable
- **Model:** AWS Bedrock — Nova Micro (`amazon.nova-micro-v1:0`)
- **Tradeoff:** Slower than Amazon Reranker but runs in same region (ap-southeast-2), no cross-region latency

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| API Framework | FastAPI + Uvicorn (port 8000) |
| UI | Streamlit (`app/streamlit_app.py`) |
| Generation Model | AWS Bedrock — Claude Haiku (`au.anthropic.claude-haiku-4-5-20251001-v1:0`) |
| Classifier / Reranker | AWS Bedrock — Amazon Nova Micro (`amazon.nova-micro-v1:0`) |
| Query Rewriter | AWS Bedrock — Amazon Nova Lite (`amazon.nova-lite-v1:0`) |
| Embeddings | Amazon Titan Text Embed v2 |
| Knowledge Base | AWS Bedrock Agents — Managed Knowledge Base |
| Reranker (alt) | Amazon Reranker (`amazon.rerank-v1:0`) in `ap-northeast-1` |
| Memory | AWS DynamoDB (sessions + turns) + AWS AgentCore |
| Document Storage | Amazon S3 |
| Auth | JWT Bearer + Admin API Key |
| Port | 8000 (FastAPI) |

---

## API Reference

### Authentication Endpoints

#### `POST /auth/login` (Dev Only)
Login using `fake_users.json`. Not for production.

**Request Body**
```json
{ "login_id": "coordinator.jane", "password": "dev-pass-456" }
```

**Response**
```json
{
  "token": "eyJhbGci...",
  "user_id": "user_abc",
  "org_id": "org_xyz",
  "role": "coordinator",
  "full_name": "Jane Coordinator"
}
```

Token TTL: 3600 seconds. Rate limited: 20 attempts per 60s per IP.

#### `POST /auth/logout`
Validates token (stateless — no actual revocation). Returns `{ "success": true }`.

---

### Query Endpoints

#### `POST /query/stream` — Primary (SSE Streaming)

**Headers**
```
Authorization: Bearer <jwt-token>
Content-Type: application/json
```

**Request Body**
```json
{
  "question": "What is the process for reporting a restrictive practice?",
  "session_id": "sess_abc123",
  "session_title": "Restrictive Practice Queries",
  "is_new_chat": false,
  "doc_type": "policy"
}
```

| Field | Required | Notes |
|-------|----------|-------|
| `question` | Yes | Max 2000 characters |
| `session_id` | No | Resume prior conversation |
| `session_title` | No | Label for this session |
| `is_new_chat` | No | Start fresh session |
| `doc_type` | No | Filter by `"policy"` or `"procedure"` |

**SSE Response Stream**
```
data: {"type":"meta","session_id":"sess_abc123","label":"Restrictive Practice Q...","sources":[{"title":"RP Policy","page":3}]}

data: {"type":"token","text":"Reporting "}
data: {"type":"token","text":"a restrictive "}
...
data: {"type":"usage","input_tokens":612,"output_tokens":187}
data: {"type":"done","stop_reason":"end_turn"}
```

| Event | Fields | Description |
|-------|--------|-------------|
| `meta` | `session_id`, `label`, `sources` | First event; includes source doc references |
| `token` | `text` | Streamed answer token |
| `usage` | `input_tokens`, `output_tokens` | Final token count |
| `done` | `stop_reason` | Stream complete |
| `blocked` | `text`, `label` | Query blocked (sensitive/off-topic/harmful) |
| `error` | `text` | Error |

#### `POST /query` — Non-Streaming
Same request body. Returns complete JSON response (not SSE).

---

### Session Management

#### `POST /new_session`
Create a new session. Returns `{ "session_id": "<uuid>" }`.

#### `POST /list_sessions`
List all sessions for the authenticated user.

#### `POST /get_turns`
Get conversation turns for a session.
**Request:** `{ "session_id": "sess_abc123" }`
**Response:** `{ "turns": [{ "question": "...", "answer": "...", "sources": [...], "timestamp": "..." }] }`

#### `POST /rename_session`
**Request:** `{ "session_id": "...", "title": "New Title" }`

---

### Admin Endpoints

> All admin endpoints require both JWT Bearer + `X-Api-Key: <INTERNAL_API_KEY>` header + coordinator/superadmin role.

#### `POST /admin/trigger_ingestion`
Upload a document to the Bedrock Knowledge Base.

**Request Body**
```json
{
  "s3_key": "sena/orgs/org_xyz/policy_manual.pdf",
  "org_id": "org_xyz",
  "doc_type": "policy"
}
```

**Response:** `{ "status": "complete", "doc_id": "...", "org_id": "org_xyz", "filename": "policy_manual.pdf", "job_id": "..." }`

> Note: Ingestion is synchronous and takes 2–3 minutes. Respond to the user with a progress indicator.

**Role rules:**
- Coordinator → can only ingest for their own `org_id`
- Superadmin → can ingest for any `org_id`

#### `POST /admin/trigger_cleanup`
Remove a document and its vectors after deleting it from S3.

**Request Body:** `{ "s3_key": "...", "org_id": "..." }`

> File must already be deleted from S3 before calling this endpoint.

#### `GET /admin/list_docs`
List all ingested documents for an org.
**Query params:** `org_id=org_xyz`

---

### `GET /health`
```json
{ "status": "ok" }
```

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AWS_REGION` | No | `ap-southeast-2` | Primary AWS region |
| `KB_ID` | No | `KFWSFMVU8U` | Bedrock Knowledge Base ID |
| `DS_ID` | No | `CWJ8UCZSCY` | Bedrock data source ID |
| `GUARDRAIL_ID` | No | `j9x9dysm5m3h` | Bedrock Guardrail ID |
| `GUARDRAIL_VERSION` | No | `DRAFT` | Guardrail version |
| `CLASSIFIER_MODEL` | No | `amazon.nova-micro-v1:0` | Intent classification model |
| `RERANKER_MODEL` | No | `amazon.nova-micro-v1:0` | Nova reranker model |
| `REWRITER_MODEL` | No | `amazon.nova-lite-v1:0` | Query rewriting model |
| `GENERATION_MODEL` | No | `au.anthropic.claude-haiku-4-5-20251001-v1:0` | Answer generation model |
| `RERANK_REGION` | No | `ap-northeast-1` | Region for Amazon native reranker (cross-region) |
| `AMAZON_RERANK_MODEL_ID` | No | `amazon.rerank-v1:0` | Amazon native reranker |
| `NUM_RESULTS` | No | `20` | Number of chunks retrieved before reranking |
| `RERANK_TOP` | No | `8` | Final top-K chunks after reranking |
| `RERANK_PROVIDER` | No | `amazon` | `"amazon"` or `"nova"` |
| `BUCKET_NAME` | No | `sena-policy-docs` | S3 bucket for policy documents |
| `BUCKET_PREFIX` | No | `sena/misty/` | S3 key prefix |
| `ORG_PREFIX` | No | `sena/misty/orgs/` | Per-org S3 key prefix |
| `REGISTRY_TABLE` | No | `sena-doc-registry` | DynamoDB table for doc registry |
| `MEMORY_ID` | No | `senaPolicyProceduresMemory-FGIxWL6gih` | AgentCore memory ID |
| `ENV` | No | `dev` | Environment (affects DynamoDB table names) |
| `SESSIONS_TABLE` | No | `sena-{ENV}-chat-sessions` | DynamoDB sessions table |
| `TURNS_TABLE` | No | `sena-{ENV}-chat-turns` | DynamoDB turns table |
| `INTERNAL_API_KEY` | No | — | Required for admin endpoints (if empty, enforcement disabled) |
| `JWT_SECRET` | No | ephemeral | Dev JWT signing secret (never hardcode in prod) |
| `BACKEND_API_BASE` | No | — | Optional backend URL for user-type resolution |
| `ADMIN_ROLES` | No | `coordinator,superadmin` | Roles allowed for admin endpoints |

**AWS IAM permissions required:**
```json
{
  "Effect": "Allow",
  "Action": [
    "bedrock:InvokeModel",
    "bedrock:InvokeModelWithResponseStream",
    "bedrock-agent-runtime:Retrieve",
    "bedrock-agent:StartIngestionJob",
    "bedrock-agent:GetIngestionJob",
    "bedrock-agent-runtime:Retrieve",
    "s3:GetObject",
    "s3:PutObject",
    "s3:DeleteObject",
    "dynamodb:GetItem",
    "dynamodb:PutItem",
    "dynamodb:Query",
    "dynamodb:UpdateItem"
  ],
  "Resource": "*"
}
```

---

## Running the Service

**Install dependencies**
```bash
cd policy_proc
pip install -r requirements.txt   # or use shared venv
```

**DynamoDB tables (first-time setup):**
Create tables manually or via AWS console:
- `sena-dev-chat-sessions` (PK: `user_id`, SK: `session_id`, TTL: `ttl`)
- `sena-dev-chat-turns` (PK: `session_id`, SK: `turn_id`, TTL: `ttl`)
- `sena-doc-registry` (PK: `doc_id`)

**Seed dev data:**
```bash
python scripts/seed_dev_data.py
```

**FastAPI service:**
```bash
uvicorn app.main:app --reload --port 8000
```

**Streamlit UI (optional, separate process):**
```bash
streamlit run app/streamlit_app.py
```

**Swagger UI:** http://localhost:8000/docs

---

## Integration Guide

### For Backend Teams

The backend acts as a **pass-through** — it forwards the user's JWT to this service and streams the SSE response to the frontend.

**Integration Pattern:**
```
Frontend sends question
→ Backend authenticates request
→ Backend forwards to POST /query/stream with user's JWT
→ Backend streams SSE response to frontend (proxy streaming)
```

Alternatively, the frontend can call this service directly with the JWT if CORS allows it.

**Document management integration:**
```
Coordinator uploads PDF (frontend)
→ Backend uploads file to S3 at sena/orgs/{org_id}/{filename}
→ Backend calls POST /admin/trigger_ingestion with S3 key + org_id + doc_type
→ Backend shows progress indicator (~2–3 minutes)
→ Backend polls or uses webhook when ingestion is complete
```

### For Frontend Teams

**SSE streaming (JavaScript):**
```javascript
const response = await fetch('/query/stream', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({ question, session_id }),
});

const reader = response.body.getReader();
const decoder = new TextDecoder();
let buffer = '';

while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  buffer += decoder.decode(value, { stream: true });
  const lines = buffer.split('\n');
  buffer = lines.pop();  // keep incomplete line in buffer
  for (const line of lines) {
    if (!line.startsWith('data: ')) continue;
    const event = JSON.parse(line.slice(6));
    if (event.type === 'meta') {
      setSessionId(event.session_id);
      setSources(event.sources);
    } else if (event.type === 'token') {
      appendText(event.text);
    } else if (event.type === 'done') {
      finalise();
    } else if (event.type === 'blocked') {
      showBlockedMessage(event.text);
    }
  }
}
```

**Session sidebar (conversation history):**
- On load: call `POST /list_sessions` to populate the sidebar
- On session click: call `POST /get_turns` to restore the conversation
- On new question: pass `session_id` from prior `meta` event

---

### Pre-Integration Checklist

- [ ] Bedrock Knowledge Base created and `KB_ID` set
- [ ] S3 bucket created with correct prefix structure
- [ ] DynamoDB tables created (sessions + turns + doc-registry)
- [ ] AWS IAM permissions set for all required Bedrock + S3 + DynamoDB actions
- [ ] At least one policy/procedure document ingested via `trigger_ingestion` before user testing
- [ ] `INTERNAL_API_KEY` set for admin endpoints
- [ ] `fake_users.json` and `/auth/login` NOT exposed in production
- [ ] JWT compatibility confirmed — same token format as main Sena auth
- [ ] Frontend SSE client handles `meta`, `token`, `blocked`, `done`, `error` events
- [ ] Frontend shows source citations from `meta.sources`
- [ ] `ENV` variable set to `prod` (affects DynamoDB table names)

### What to Confirm Before Integration

1. **Knowledge Base ID** — `KB_ID` must point to the correct Bedrock Knowledge Base. Confirm the KB exists and has at least one document before testing.
2. **S3 bucket and prefix structure** — The ingestion and retrieval logic filters by org. Confirm the S3 path format: `{ORG_PREFIX}{org_id}/{filename}`.
3. **JWT format** — The service expects `user_id` and `org_id` claims. Confirm the Sena auth service issues these claims.
4. **Role values** — Confirm role strings (`support_worker`, `coordinator`, `superadmin`) match what the auth service issues.
5. **Reranker region** — Amazon native reranker uses `ap-northeast-1` (Tokyo). Confirm cross-region Bedrock calls are allowed from your account.

---

## QA & Testing

### Manual Test Scenarios

| Scenario | Expected |
|----------|----------|
| Ask an NDIS policy question with documents ingested | SSE stream with cited answer |
| Ask "Hello, how are you?" | GREETING response without retrieval |
| Ask a sensitive personal question | `blocked` event returned |
| Ask an off-topic question | `blocked` event returned |
| Ask the same question twice in same session | Memory context used, more concise follow-up |
| Ask with `doc_type: "procedure"` | Only procedure documents retrieved |
| Coordinator asks about another org's documents | Filtered out by org_id; answer only from own org docs |
| No documents ingested | Answer with low confidence or "no documents found" |
| Expired JWT | `401 Unauthorized` |
| Admin ingestion (coordinator, own org) | Ingestion starts, returns `status: "complete"` after 2–3 min |
| Admin ingestion (coordinator, other org) | `403 Forbidden` |
| Ingestion without `X-Api-Key` header | `403 Forbidden` |

### Known Edge Cases

- **First-ever query (no documents)** — The service still generates a response using Claude's base knowledge. Answers may not reflect org-specific policies. Always ingest documents first.
- **Ingestion takes 2–3 minutes** — The `trigger_ingestion` endpoint waits synchronously for the Bedrock ingestion job. Set a 3-minute timeout on the calling client.
- **Lambda deployment** — `scripts/lambda_function.py` exists as an alternative entry point but may be out of sync with `app/main.py`. Verify before using Lambda deployment.
- **Nova reranker vs Amazon reranker** — `RERANK_PROVIDER` controls which reranker is used. Nova is same-region; Amazon is cross-region (`ap-northeast-1`). Test both and compare result quality for your document set.

---

## Implementation Status

### Done
- POST /query/stream (SSE streaming) — fully functional
- POST /query (buffered) — fully functional
- Session management (create, list, get turns, rename)
- JWT authentication + role-based access
- Intent classification (NDIS / GREETING / SENSITIVE / OFF_TOPIC / HARMFUL)
- Query rewriting
- Bedrock Knowledge Base retrieval (vector search + org/doc_type metadata filter)
- Dual reranker support (Amazon native + Nova Micro)
- Claude Haiku answer generation with streaming
- DynamoDB session + turn persistence
- AgentCore conversation memory
- Document ingestion admin endpoint (synchronous)
- Document cleanup admin endpoint
- Document registry (DynamoDB)
- Org-based retrieval isolation
- Streamlit UI
- Lambda function handler (alternative entry)
- Rate limiting on login endpoint

### Missing / Not Yet Implemented

| Item | Impact | Notes |
|------|--------|-------|
| `fake_users.json` in production | Critical | Remove or gate `/auth/login` before production |
| JUDGE_MODEL unused | Low | Defined in config but not called anywhere |
| Guardrails enforcement | Low | Config supports guardrails but actual `apply_guardrail()` call not visible in code |
| JWT signature verification | Medium | Only expiry checked; backend is trusted to issue valid tokens |
| Lambda function sync | Medium | `lambda_function.py` may be out of sync with `app/main.py` |

---

## Integration Requirements

**Mandatory before production integration:**

1. **Bedrock Knowledge Base** — must exist with `KB_ID` configured
2. **S3 bucket** — must exist with correct prefix for org-isolated document storage
3. **DynamoDB tables** — sessions, turns, and doc-registry tables must be created with correct key structure and TTL enabled
4. **AWS IAM** — all Bedrock, S3, and DynamoDB permissions as listed above
5. **Documents ingested** — at least one policy/procedure document must be ingested before user testing
6. **`INTERNAL_API_KEY` set** — required to protect admin endpoints
7. **Remove dev login** — gate or remove `/auth/login` and `fake_users.json` in production
8. **JWT secret** — ensure `JWT_SECRET` comes from an environment variable, never hardcoded

**Nice to have:**
- JWT signature verification
- JUDGE_MODEL wired to a verification/grading step
- Bedrock Guardrail ID enforcement confirmed in generation path
