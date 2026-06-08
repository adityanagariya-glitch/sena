# SENA ai_chatbot — Gateway API Guide

> **This is the authoritative, current documentation for the ai_chatbot gateway.**
> The other markdown files in this folder predate the chip-only / independent-section
> redesign and may be out of date.

The **ai_chatbot gateway** is the single HTTP entry point for the SENA assistant.
A client sends one message; the gateway authenticates it, routes it to the correct
backend section based on the tapped UI chip, and streams the answer back as
Server-Sent Events (SSE). It fronts two backends:

- **Staff service** (`api_main.py`, port `8601`) — two independent sections:
  *Shifts* (the worker's own work) and *Client* (participant info).
- **Policy service** (`policy_proc`, port `8000`) — organisational policy & procedures.

---

## 1. Key design rules

1. **Chip-driven routing only.** Every request carries `context.category` (the chip the
   user tapped). There is **no free-text classification** — a request with no category
   is treated as out of scope.
2. **Sections are completely independent.** A *Shifts* request can never reach client
   data, and a *Client* request can never reach shift data. This is enforced at five
   layers (tools, dispatcher, skills, prompt, conversation history).
3. **Cross-section questions are refused with guidance.** Ask a client question while
   in the Shifts chip and you get: *"That looks like a 'Client's information' question…
   please switch to 'Client's information'."* — no data is returned.
4. **The gateway is a pass-through for auth.** It forwards the caller's Bearer token
   unchanged; each backend validates it.

---

## 2. Running the stack

```bash
# From services/ai_chatbot/
SENA_AI_AGENT_MODE=on python gateway.py
```

- `SENA_AI_AGENT_MODE=on` is **required** (see config table) — it enables the
  tool-based agent that powers the independent Shifts/Client sections. The gateway
  passes its own environment to the child services, so set it before launching.
- With `MANAGE_CHILDREN=true` (default) the gateway also starts and health-checks the
  staff and policy services, then waits until they report healthy.
- The gateway needs Bedrock credentials. They are read from `services/staff/.env`
  (`BEDROCK_API_KEY`) and/or the ambient AWS credentials, same as the staff service.

Once up: gateway on **http://localhost:9000**, interactive docs at **/docs**.

---

## 3. Authentication

All requests to `POST /api/route` require a bearer token:

```
Authorization: Bearer <JWT>
```

- **Production token:** the ISENA token from `POST https://dev-api.isena.org/api/auth/ai/login`
  (email + password). This is the same login used across SENA.
- The gateway forwards the token to the backend. The backend validates it and derives
  the user's identity (`user_id`, `org_id`, role) from the token claims.
- A user's **role** comes from the token; ISENA roles are opaque IDs, so an ISENA user
  is treated as a regular member (non-admin) unless the role matches a known admin role.
- The **policy service accepts both** token types: the ISENA token *and* its own
  dev/test token minted via `POST :8000/auth/login` (see config table for
  `ISENA_JWT_SECRET`).

Missing/invalid token → `401`.

---

## 4. The API

### `POST /api/route` — route a message and stream the answer

**Request body**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `question` | string | yes* | The user's message. May be empty when a chip is tapped with no text — the section's default question is used. |
| `context.category` | string | yes | The tapped chip — decides routing. One of `shifts`, `client`, `policy`, `procedure`. |
| `context.session_id` | string | no | Continue an existing conversation thread. |
| `context.session_title` | string | no | Title for a new conversation. |
| `context.is_new_chat` | bool | no | `true` starts a fresh conversation. |

```json
{
  "question": "What are my shifts this week?",
  "context": { "category": "shifts", "is_new_chat": true }
}
```

**Chip → backend mapping**

| `category` | Backend | Section | Covers |
|------------|---------|---------|--------|
| `shifts` | staff (`8601`) | **Staff** | shifts, rosters, shift details, staff/team directory |
| `client` | staff (`8601`) | **Client** | client list, details, support workers, guardians, search |
| `policy` | policy (`8000`) | — | organisational policy |
| `procedure` | policy (`8000`) | — | compliance procedures |

No `category` (or an unknown one) → the stream returns a single guidance message
asking the user to choose a section.

### `GET /healthz`

Returns gateway + child health: `{"gateway": true, "children": {"staff_api": true, "policy_api": true}}`.

### `GET /`

Service banner with the endpoint list.

---

## 5. SSE response — event reference

The response is `text/event-stream`. Each line is `data: <json>`. Events arrive in order:

| `type` | Fields | Meaning |
|--------|--------|---------|
| `meta` | `routing` / `session_id` | Routing decided. Emitted immediately so the client can show a status. |
| `token` | `text` | The answer. (Currently delivered as one block per response.) |
| `usage` | `input_tokens`, `output_tokens` | **Bedrock token usage for this question.** Emitted just before `done`. |
| `done` | — | Stream finished. |
| `error` | `text` | Something went wrong; a friendly message for the user. |

Example stream:

```
data: {"type": "meta", "routing": {"target_services": ["staff"], "routing_reason": "Category 'shifts' routed to staff."}}

data: {"type": "token", "text": "Here are your shifts this week: ..."}

data: {"type": "usage", "input_tokens": 2496, "output_tokens": 320}

data: {"type": "done"}
```

**Cross-section refusal** (e.g. a client question under the `shifts` chip) returns a
single directive `token` then `done`:

```
data: {"type": "token", "text": "That looks like a “Client's information” question, but you're in the “Check Shifts” section. ... please switch to “Client's information”."}

data: {"type": "done"}
```

> Note: because the gateway emits its own `meta`/`done` and also forwards the
> backend's, a client may currently see the `meta`/`done` types twice. Parse
> defensively (treat the first `done` as end-of-stream, or ignore duplicates).

---

## 6. Configuration — environment variables

All are optional; defaults shown. Set them before launching the gateway.

### Behaviour flags — what to set and when

| Variable | Default | Set to… | When |
|----------|---------|---------|------|
| `SENA_AI_AGENT_MODE` | `off` | **`on`** | **Always, in normal operation.** Enables the tool-based agent that powers the independent Shifts/Client sections. With `off`, the staff service falls back to a legacy path and section independence is **not** guaranteed. |
| `MANAGE_CHILDREN` | `true` | `true` | Local / one-command runs — the gateway starts & monitors the staff and policy services for you. |
| | | `false` | Production / when each service is deployed and scaled separately — the gateway only proxies to already-running services. |
| `ISENA_JWT_SECRET` (policy) | *(empty)* | *(leave empty)* | Dev/test, or when the gateway is the trust boundary — ISENA tokens are decoded without signature verification (still expiry-checked). |
| | | *(set the secret)* | Production hardening — enables full ISENA signature verification on the policy service. No code change needed. |
| `SENA_AI_VERBOSE` (staff) | *(off)* | `1` | Verbose timing/diagnostic logs. |

### Ports & networking

| Variable | Default | Meaning |
|----------|---------|---------|
| `GATEWAY_HOST` | `0.0.0.0` | Gateway public bind address. |
| `GATEWAY_PORT` | `9000` | Gateway port (the only port clients hit). |
| `CHILD_HOST` | `127.0.0.1` | Children bind to loopback only — reachable solely via the gateway. |
| `STAFF_PORT` | `8601` | Staff FastAPI port. |
| `POLICY_API_PORT` | `8000` | Policy FastAPI port. |
| `POLICY_PORT` | `8602` | Policy Streamlit port (test UI only; not the API). |
| `CHILD_HEALTH_TIMEOUT` | `60` | Seconds to wait for each child to report healthy at startup. |
| `STAFF_DIR` / `POLICY_DIR` | *(auto)* | Override backend source locations. |

### Auth / secrets

| Variable | Where | Meaning |
|----------|-------|---------|
| `BEDROCK_API_KEY` | `services/staff/.env` | Bedrock bearer token; exported as `AWS_BEARER_TOKEN_BEDROCK`. Shared by staff and gateway. |
| `JWT_SECRET` | policy | Signs/verifies the policy service's own dev tokens (`/auth/login`). |

---

## 7. Backend service reference

The gateway calls these internally; documented here for completeness and direct testing.

### Staff service (`:8601`) — independent sections

| Endpoint | Section | Tools available |
|----------|---------|-----------------|
| `POST /staff/query/stream` | Staff | shifts, rosters, shift details, staff/team directory (+ general identity tools) |
| `POST /client/query/stream` | Client | client list/details, support workers, guardians, search/filter (+ general identity tools) |
| `POST /query/stream` | *(deprecated)* | Alias → Staff section. Use the explicit endpoints. |
| `GET /health` | — | Liveness. |

Each accepts the same body as the gateway's `question`/`session_id`/`session_title`/
`is_new_chat`, and streams the same SSE events (incl. `usage`).

### Policy service (`:8000`)

| Endpoint | Meaning |
|----------|---------|
| `POST /query/stream` | Policy/procedure Q&A over the org's knowledge base. Same SSE events (incl. `usage`); also `blocked` for guardrail interventions. |
| `POST /auth/login` | Mint a dev/test token from `{login_id, password}` (test accounts only). |
| `GET /health` | Liveness. |

> **Auth ≠ data for policy:** a valid token authenticates, but answers only come back
> if that org's policy documents are ingested into the knowledge base. An org with no
> ingested docs authenticates fine but returns "no documents."

---

## 8. Interactive docs (Swagger / ReDoc)

| Service | Swagger UI | ReDoc | OpenAPI JSON |
|---------|-----------|-------|--------------|
| Gateway | `:9000/docs` | `:9000/redoc` | `:9000/openapi.json` |
| Staff | `:8601/docs` | `:8601/redoc` | `:8601/openapi.json` |
| Policy | `:8000/docs` | `:8000/redoc` | `:8000/openapi.json` |

---

## 9. Example client usage

Any HTTP client that can read a streaming response works. Example with `curl`:

```bash
TOKEN="<ISENA JWT>"

curl -N -X POST http://localhost:9000/api/route \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question": "What are my shifts this week?", "context": {"category": "shifts"}}'
```

Consuming the stream in a client:

1. Open a streaming POST to `/api/route` with the JSON body.
2. Read the response line by line; split on the blank line (`\n\n`) between events.
3. For each `data: <json>` line, parse the JSON and switch on `type`:
   - `meta` → show a "routing…" status;
   - `token` → render/append the answer text;
   - `usage` → record `input_tokens` / `output_tokens` for cost/metrics;
   - `done` → close the stream;
   - `error` → show the message.

---

## 10. Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| `401` from `/api/route` | Missing/invalid `Authorization: Bearer <token>` header. |
| Stream returns only the "choose a section" message | No `context.category` was sent. |
| "switch to … section" message | A cross-section question (expected — sections are independent). |
| Staff answers ignore section boundaries | `SENA_AI_AGENT_MODE` is not `on`. |
| Policy returns "no documents" | That org has no policy docs ingested in the KB (auth is fine). |
| `incomplete chunked read` / read timeout on policy | Policy generation exceeded the gateway read window on a cold start; retry. |
