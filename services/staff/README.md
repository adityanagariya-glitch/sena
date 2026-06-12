# Staff AI Agent Service

> FastAPI service that powers the Sena staff-facing AI assistant. Provides multi-turn conversational access to shift, client, roster, and profile data via a tool-using AWS Bedrock (Claude Sonnet 4.6) agent with streaming SSE responses. Supports both staff queries (shifts, rosters) and client queries (client info, guardians, support history).

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

Support workers and coordinators ask questions like "What shifts do I have this week?", "Who are my clients tomorrow?", or "What's the contact number for Client X's guardian?" This service answers those questions by:

1. Classifying the query (META recall / CHAT greeting / API data lookup / HYBRID)
2. Routing to the right tool group (staff tools or client tools)
3. Calling the Sena backend API via the appropriate tools
4. Streaming the response back token-by-token via SSE

Two separate query endpoints exist — `/staff/query/stream` (shift/roster queries) and `/client/query/stream` (client data queries) — with isolated tool sets for each context.

---

## How It Works

```
POST /staff/query/stream  (or /client/query/stream)
  ├─ Validate JWT, extract user_id + org_id + role
  ├─ Check AgentCore memory for prior session context (if available)
  ├─ Classify intent: META / CHAT / API / HYBRID
  │
  ├─ [META] → Recall from conversation history → stream answer
  ├─ [CHAT] → Direct Claude response (no API calls) → stream answer
  ├─ [API]  → Detect best tool → call Sena backend API → stream answer
  └─ [HYBRID] → Mix of memory + API call → stream answer
  │
  ├─ Stream tokens via SSE (type: "token")
  ├─ Persist turn to DynamoDB (if configured)
  └─ Return: meta, tokens, usage, done events
```

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| API Framework | FastAPI + Uvicorn |
| AI Model | AWS Bedrock — Claude Sonnet 4.6 (`au.anthropic.claude-sonnet-4-6`) |
| Streaming | Server-Sent Events (SSE) |
| Memory | AWS AgentCore (24h session memory, optional) |
| Audit Log | AWS DynamoDB (30-day TTL, optional) |
| Auth | JWT Bearer (HS256) |
| Backend API | Sena backend (`https://dev-api.isena.org/api`) |
| Port | 8000 (default) |

---

## API Reference

### `POST /auth/login` (Dev Only)

**Purpose:** Development login using `fake_users.json`. Not for production.

**Request Body**
```json
{
  "login_id": "sarah.jones",
  "password": "dev-password-123"
}
```

**Response**
```json
{
  "token": "eyJhbGci...",
  "user_id": "user_321",
  "org_id": "org_abc",
  "role": "support_worker",
  "full_name": "Sarah Jones",
  "login_id": "sarah.jones"
}
```

---

### `POST /staff/query/stream`
Ask a question about shifts, roster, org staff, or personal profile.

**Headers**
```
Authorization: Bearer <jwt-token>
Content-Type: application/json
```

**Request Body**
```json
{
  "question": "What shifts do I have this week?",
  "session_id": "sess_abc123",
  "session_title": "My Shifts Week of June 9",
  "is_new_chat": false
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `question` | string | Yes | Max 10,000 characters |
| `session_id` | string | No | Resume prior session; server creates new if absent |
| `session_title` | string | No | Label for this conversation session |
| `is_new_chat` | boolean | No | `true` to start fresh (clears session history) |

**Response:** Server-Sent Events (SSE) stream

```
data: {"type":"meta","session_id":"sess_abc123"}

data: {"type":"token","text":"You "}
data: {"type":"token","text":"have "}
data: {"type":"token","text":"three "}
data: {"type":"token","text":"shifts "}
...
data: {"type":"usage","input_tokens":487,"output_tokens":112}
data: {"type":"done"}
```

| Event Type | Fields | Description |
|------------|--------|-------------|
| `meta` | `session_id` | First event — confirms session ID |
| `token` | `text` | Streamed response token |
| `usage` | `input_tokens`, `output_tokens` | Final token count |
| `done` | — | Stream complete |
| `error` | `text` | Error message |

---

### `POST /client/query/stream`
Ask a question about clients, their guardians, support workers, or service details.

Same request/response shape as `/staff/query/stream`. Uses a different tool set (client-domain tools).

---

### `GET /health`

```json
{ "status": "ok" }
```

---

## Available Tools (20+)

The agent selects tools automatically based on query intent.

**Staff tools:**
- `list_my_shifts` — list the authenticated user's upcoming shifts
- `get_shift_details` — full details for a specific shift
- `list_org_shifts` — all shifts in the org (coordinator/admin only)
- `list_shifts_for_person` — shifts for a specific worker
- `list_org_staff` — all staff in the organisation

**Client tools:**
- `list_my_clients` — clients assigned to the authenticated worker
- `get_client_details` — full client profile
- `get_client_guardians` — guardian/emergency contacts for a client
- `get_client_support_workers` — support workers assigned to a client
- `search_clients` — search clients by name/criteria
- `list_org_clients` — all clients in the org (coordinator/admin only)

**Profile tools:**
- `my_profile` — authenticated user's own profile
- `get_user_type` — current role and permissions
- `set_my_timezone` — save preferred timezone
- `remember_about_me` — persist personal preferences

**Meta tools:**
- `recall_conversation` — search prior session turns
- `get_current_time` — current date/time in user's timezone
- `cannot_help` — gracefully decline out-of-scope queries
- `clarify_with_user` — ask a follow-up question when intent is ambiguous

---

## Environment Variables

> **Note:** `config.py` hardcodes the `.env` path as `/home/main/SENA/.env`. Update this if deploying on a different machine.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SENA_AI_VERBOSE` | No | `false` | Verbose debug logging (`1`/`true`/`yes` to enable) |
| `SENA_AI_BEDROCK_GUARDRAIL_IDS` | No | — | Comma-separated `id:version` guardrail pairs |
| `SENA_AI_BEDROCK_GUARDRAIL_ID` | No | — | Single guardrail ID fallback |
| `SENA_AI_BEDROCK_GUARDRAIL_VERSION` | No | `DRAFT` | Guardrail version |
| `BEDROCK_API_KEY` | No | — | Bedrock bearer token (optional) |
| `SENA_AI_AGENTCORE_MEMORY_ID` | No | — | AgentCore memory ID for 24h session storage |
| `SENA_AI_AGENTCORE_SESSION_TTL_HOURS` | No | `24` | AgentCore session TTL |
| `SENA_AI_CHAT_AUDIT_TABLE` | No | — | DynamoDB table name for 30-day audit log |
| `SENA_AI_CHAT_AUDIT_TTL_DAYS` | No | `30` | Audit log row TTL |
| `SENA_AI_SESSION_TABLE` | No | — | DynamoDB session table (multi-process session continuity) |
| `SENA_AI_SESSION_ROW_TTL_DAYS` | No | `90` | Session row TTL |
| `SENA_AI_AGENT_MODE` | No | `off` | Agent loop mode toggle (experimental) |

**Hardcoded values in `config.py` (update before production):**

| Value | Current | Notes |
|-------|---------|-------|
| `API_BASE_URL` | `https://dev-api.isena.org/api` | Must update to production backend URL |
| `MODEL_ID` | `au.anthropic.claude-sonnet-4-6` | Claude Sonnet 4.6 AUS region |
| `REGION` | `ap-southeast-2` | AUS data residency — do not change |

**AWS IAM permissions required:**
```json
{
  "Effect": "Allow",
  "Action": [
    "bedrock:InvokeModelWithResponseStream",
    "bedrock:ApplyGuardrail"
  ],
  "Resource": "*"
}
```

---

## Running the Service

**Install dependencies**
```bash
cd staff
pip install -r requirements.txt
```

**Development**
```bash
uvicorn api_main:app --reload --host 0.0.0.0 --port 8000
```

**Production**
```bash
uvicorn api_main:app --host 0.0.0.0 --port 8000 --workers 4
```

**Quick smoke test (after deployment):**
```bash
python smoke_test.py
```

**Swagger UI** — http://localhost:8000/docs

---

## Integration Guide

### For Backend Teams

The Sena backend is the **data provider** for this service. This service calls the backend API using the authenticated user's JWT to fetch shift and client data.

**Backend must expose these endpoints** (used by agent tools):
```
GET  /organization/shift/list-view/type      — list shifts (with filters)
GET  /shift/{id}/details                     — get single shift details
GET  /staff/{id}                             — get staff profile
GET  /client/{id}                            — get client profile
GET  /auth/user-type                         — fetch authoritative user type/role
```

The bearer token forwarded from the frontend is used for all backend calls. Ensure the backend accepts the same JWT that the frontend uses.

### For Frontend Teams

The frontend integrates with two streaming endpoints using SSE.

**SSE client example (JavaScript):**
```javascript
const eventSource = new EventSource('/staff/query/stream', {
  method: 'POST',   // some SSE clients require a custom wrapper
});

// Or use fetch with ReadableStream:
const response = await fetch('/staff/query/stream', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({ question, session_id, is_new_chat: false }),
});

const reader = response.body.getReader();
const decoder = new TextDecoder();

while (true) {
  const { done, value } = await reader.read();
  if (done) break;

  const text = decoder.decode(value);
  const lines = text.split('\n').filter(l => l.startsWith('data: '));
  for (const line of lines) {
    const event = JSON.parse(line.slice(6));
    if (event.type === 'token') appendToMessage(event.text);
    if (event.type === 'done') finaliseMessage();
    if (event.type === 'error') showError(event.text);
  }
}
```

**Session management:**
- Store `session_id` from the `meta` event in local/session storage
- Pass `session_id` on subsequent messages to maintain conversation continuity
- Set `is_new_chat: true` when the user starts a new topic or clicks "New Chat"
- Display a typing indicator while `type: "token"` events are flowing

**Do not call `/auth/login` in production.** Frontend should use the main Sena authentication flow and pass the resulting JWT to this service.

---

### Pre-Integration Checklist

- [ ] `API_BASE_URL` updated in `config.py` to production backend URL
- [ ] Sena backend exposes the required API endpoints (shifts, clients, staff, user-type)
- [ ] Backend JWT is compatible — same token works for both this service and the backend API
- [ ] AWS credentials or IAM role with `bedrock:InvokeModelWithResponseStream` permission
- [ ] Frontend implements SSE reading loop with `token`, `done`, `error` event handling
- [ ] Frontend stores `session_id` and passes it on subsequent messages
- [ ] Frontend shows typing indicator during streaming
- [ ] `/auth/login` and `fake_users.json` not exposed in production
- [ ] `.env` path updated in `config.py` if not deploying on `/home/main/SENA/`

### What to Confirm Before Integration

1. **JWT format compatibility** — Confirm the backend issues JWTs with the required claims (`user_id`, `org_id`, `role`) that this service expects.
2. **Backend API paths** — Confirm all tool-used paths (`/shift/list-view/type`, `/client/{id}`, etc.) exist on the production backend.
3. **Role-based access** — Coordinators can call `list_org_shifts`/`list_org_clients`; support workers cannot. Confirm role values match what this service expects (`support_worker`, `coordinator`, `superadmin`).
4. **AgentCore and DynamoDB** — Optional but recommended for production. Confirm AWS region and table names before enabling.
5. **Agent mode** — `SENA_AI_AGENT_MODE=off` by default. The new tool-based agent loop is not fully wired. Do not enable in production yet.

---

## QA & Testing

### Manual Test Scenarios

**Staff query scenarios:**
| Question | Expected Tool | Expected Behaviour |
|----------|--------------|-------------------|
| "What shifts do I have this week?" | `list_my_shifts` | Lists upcoming shifts for auth user |
| "What happened in my last shift?" | `list_my_shifts` + `get_shift_details` | Retrieves and summarises last shift |
| "Who's working tomorrow?" (coordinator) | `list_org_shifts` | Lists all org shifts for tomorrow |
| "Who's working tomorrow?" (support worker) | `cannot_help` | Role-blocked; only coordinator allowed |
| "What's today's date?" | `get_current_time` | Returns current date in user's timezone |
| "Hi, how are you?" | CHAT (no tool) | Polite conversational response |

**Client query scenarios:**
| Question | Expected Tool | Expected Behaviour |
|----------|--------------|-------------------|
| "Who are my clients?" | `list_my_clients` | Lists assigned clients |
| "What's Sarah Chen's address?" | `get_client_details` | Returns client address |
| "Who are Client X's guardians?" | `get_client_guardians` | Lists guardian contacts |

**Session continuity:**
| Scenario | Expected |
|----------|----------|
| Same `session_id` across multiple questions | Remembers context from prior turns |
| `is_new_chat: true` | Starts fresh, ignores prior turns |
| No `session_id` provided | Creates new session, returns session_id in `meta` event |

### Known Edge Cases

- **Ambiguous queries** — Model may call `clarify_with_user` tool to ask a follow-up. Frontend must handle a clarifying question as a normal streamed response (not a special UI event).
- **Timezone-dependent queries** ("What shifts do I have today?") — If user has not set a timezone, defaults to `Australia/Sydney`. May show wrong shifts for users in other states.
- **Large organisation data** — Coordinators querying `list_org_shifts` for large orgs may see token-heavy responses. The service paginates tool calls, but response time increases.
- **API spec JSON files** — The service uses static `common_apis.json`, `staff_apis.json`, `clients_apis.json` to inform the agent about available API routes. If the backend changes an endpoint, these files must be updated manually.

---

## Implementation Status

### Done
- POST /staff/query/stream — fully functional
- POST /client/query/stream — fully functional
- POST /auth/login (dev mode with fake_users.json)
- GET /health
- 20+ domain tools across staff, clients, profile, meta, memory domains
- Intent classification (META / CHAT / API / HYBRID)
- SSE streaming
- JWT authentication + role-based tool access
- Bedrock Guardrails (optional, multi-level)
- Prompt injection defence (NFKC normalisation, invisible codepoint stripping)
- DynamoDB audit log (optional)
- AgentCore 24h memory (optional)
- Australian English style guide enforcement

### Missing / Not Yet Implemented

| Item | Impact | Notes |
|------|--------|-------|
| `API_BASE_URL` points to dev | Critical | Must update `config.py` before production |
| `fake_users.json` in production | High | Dev-only login must not be exposed; production auth must come from Sena auth service |
| Agent mode (`SENA_AI_AGENT_MODE`) | Medium | Toggle exists but new agent loop not fully wired — keep `off` |
| JWT secret hardcoded? | High | Confirm JWT secret is from env var, not hardcoded in `api_routes.py` |
| `.env` path hardcoded | Medium | `config.py:8` hardcodes `/home/main/SENA/.env` — update for deployment |
| API spec JSON files | Low | Static files — must be manually updated if backend routes change |

---

## Integration Requirements

**Mandatory before production integration:**

1. **Update `API_BASE_URL`** in `config.py` to production backend URL
2. **Remove or gate `/auth/login`** — must not be accessible in production; frontend uses main Sena auth
3. **Sena backend endpoints** — all tool-called paths must exist and return expected data shapes
4. **JWT compatibility** — same token format and claims as used by the backend
5. **AWS credentials** — `bedrock:InvokeModelWithResponseStream` in `ap-southeast-2`
6. **Update `.env` path** in `config.py` if not deploying on `/home/main/SENA/`
7. **Frontend SSE client** — must handle `token`, `meta`, `usage`, `done`, `error` event types

**Optional but recommended:**
- AWS DynamoDB tables for audit log and session continuity
- AWS AgentCore memory ID for 24h context retention
- Bedrock Guardrails ID for input/output safety filtering
