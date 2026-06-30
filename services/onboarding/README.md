# Onboarding Voice Service

> FastAPI service that collects structured participant/staff onboarding data through a real-time voice conversation powered by Google Gemini Live. Supports session management, cross-screen context, form field extraction via tool calls, and webhook delivery on completion.

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

During participant or staff onboarding, the frontend opens a voice session with this service. A Gemini Live agent guides the user through the onboarding form in natural conversation — filling in fields like name, address, DOB, emergency contacts, and more. The session state is stored in Redis. When the form is complete, the backend calls the `/complete` endpoint, which delivers the collected data to the app backend via a signed webhook.

Two personas are supported:
- **Client onboarding** — 6 steps, gathering participant details
- **Staff onboarding** — 5 steps, gathering worker details

---

## How It Works

```
Backend (or frontend) calls POST /v1/onboarding/session
  ├─ Creates Redis session with form schema, bootstrap data, TTL
  └─ Returns: session_id + ws_url

Frontend opens WSS /ws/onboarding/{session_id}
  ├─ Sends "hello" handshake
  ├─ Server accepts — sends "ready" with initial form state
  ├─ Frontend streams PCM16 16kHz audio from microphone
  ├─ Gemini Live processes speech, updates form fields via tool calls
  │   ├─ tool_request: { tool: "update_field", args: { field_id, value } }
  │   ├─ Frontend applies update to UI, sends tool_response to confirm
  │   └─ Agent continues filling remaining fields
  └─ Agent or user signals form completion

Backend calls POST /v1/onboarding/session/{session_id}/complete
  ├─ Marks session complete
  ├─ Fires webhook: onboarding.session.completed → app backend
  └─ Returns: { completed: true, webhook_delivered: true/false }
```

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| API Framework | FastAPI + Uvicorn (port 8083) |
| Voice Agent | Google Gemini Live API (`gemini-3.1-flash-live-preview`) |
| Session Cache | Redis (all session state, TTL-based) |
| Validation | Pydantic v2 |
| Auth | None (relies on `X-Tenant-Id` + `X-Participant-Id` headers for cross-tenant isolation) |
| Webhook Signing | HMAC-SHA256 (`X-SENA-AI-Signature` header) |
| Port | 8083 |

---

## API Reference

### REST Endpoints

#### `POST /v1/onboarding/session`
Create a new voice onboarding session.

**Request Body**
```json
{
  "participant_id": "part_abc123",
  "step": "client_personal_details",
  "schema": { ... },
  "initial_state": { "values": { "first_name": "Jane" } },
  "bootstrap": { "prior_pages": [...] },
  "locale": "en-AU",
  "tenant_id": "org_xyz"
}
```

| Field | Required | Notes |
|-------|----------|-------|
| `participant_id` | Yes | Unique ID for the participant |
| `step` | Yes | Step identifier (e.g., `client_personal_details`, `staff_employment`) |
| `schema` | Yes | JSON schema describing the form fields for this step |
| `initial_state` | No | Pre-fill any already-known field values |
| `bootstrap` | No | Cross-screen context from prior steps |
| `locale` | No | Default: `en-AU` |
| `tenant_id` | No | Required when cross-screen context is enabled |

**Response**
```json
{
  "session_id": "sess_abc123",
  "ws_url": "wss://host/ws/onboarding/sess_abc123",
  "expires_at": "2026-06-01T11:00:00Z"
}
```

---

#### `GET /v1/onboarding/session/{session_id}/state`
Get current form state for a session.

**Headers (optional):** `X-Tenant-Id`, `X-Participant-Id` (enforces cross-tenant guard when present)

**Response:** Full `FormState` JSON object with current field values.

---

#### `PUT /v1/onboarding/session/{session_id}/state`
Update form state from the app (non-voice, programmatic update).

**Request Body**
```json
{ "values": { "first_name": "Jane", "last_name": "Citizen" } }
```

**Response:** Updated `FormState`.

> Returns `409 Conflict` if a WebSocket session is currently active (WS lock held).

---

#### `POST /v1/onboarding/session/{session_id}/complete`
Mark a session as complete and fire the completion webhook.

**Response**
```json
{
  "session_id": "sess_abc123",
  "completed": true,
  "webhook_delivered": true
}
```

Webhook delivery is attempted 3 times with exponential backoff (1s, 4s, 16s). If all retries fail, `webhook_delivered` is `false` — the session is still marked complete.

---

#### `POST /v1/onboarding/session/{session_id}/errors`
Report a client-side validation error for telemetry purposes.

**Request Body**
```json
{
  "error_type": "format_mismatch",
  "error_message": "Date of birth must be DD/MM/YYYY",
  "input_method": "voice",
  "field_id": "date_of_birth",
  "attempted_value": "June 15th 1990",
  "ts": "2026-06-01T10:30:00Z"
}
```

**Response:** 204 No Content. Errors are stored for 7 days (telemetry only).

---

#### `GET /health/live`
```json
{ "status": "ok" }
```

#### `GET /health/ready`
```json
{ "status": "ok", "redis": "connected" }
```
Returns `503` if Redis is unavailable.

---

### WebSocket Endpoint

#### `WSS /ws/onboarding/{session_id}[?resume=<handle>]`

**Query param:** `resume` — optional UUID4 handle to resume an interrupted session.

**Headers (optional):** `X-Tenant-Id`, `X-Participant-Id` for cross-tenant isolation.

**Client → Server Frames**

| Frame | Format | Description |
|-------|--------|-------------|
| Handshake | JSON `{"type":"hello","client_proto":"v2"}` | Must be first text frame |
| Audio | Binary PCM16 16kHz mono | Continuous microphone audio |
| Text input | JSON `{"type":"user_text","text":"..."}` | Alternative to audio (typed input) |
| Tool response | JSON `{"type":"tool_response","id":"<tool_call_id>","result":{"success":true}}` | App confirms a field update |
| Screen state | JSON `{"type":"screen_state","data":{...}}` | Current visible form state (max 16384 bytes) |
| Validation failed | JSON `{"type":"validation_failed","section_id":"...","field_id":"...","reason_human":"...","code":"..."}` | Inject validation error into agent context |
| Validation cleared | JSON `{"type":"validation_cleared","section_id":"...","field_id":"..."}` | Notify agent validation error is resolved |
| Stop | JSON `{"type":"stop"}` | Graceful disconnect |

**Server → Client Frames**

| Frame | Format | Description |
|-------|--------|-------------|
| Ready | JSON `{"type":"ready","state":{...},"prompt_version":"v2","coverage":[...]}` | Session accepted |
| Audio | Binary PCM16 24kHz mono | Agent voice — play immediately |
| Turn start | JSON `{"type":"turn_start"}` | Agent started speaking |
| Turn complete | JSON `{"type":"turn_complete"}` | Agent finished speaking |
| Interrupted | JSON `{"type":"interrupted"}` | User interrupted the agent |
| Tool request | JSON `{"type":"tool_request","tool":"update_field","id":"tc_001","args":{"field_id":"first_name","value":"Jane"}}` | Agent wants to set a field |
| User said | JSON `{"type":"user_said","text":"..."}` | Transcribed user speech |
| Agent said | JSON `{"type":"agent_said","text":"..."}` | Agent transcript |
| Go away | JSON `{"type":"go_away","time_left_ms":30000}` | Session expiring — resume before timeout |
| Resumable | JSON `{"type":"resumable","handle":"<uuid>","ttl_sec":600}` | Resume handle issued on disconnect |
| Error | JSON `{"type":"error","code":"...","message":"..."}` | Error |

**WS Lock:** Only one active WebSocket per `session_id`. A second connection attempt receives `{"type":"error","code":"session_locked"}` and is closed with code 4009.

**Tool calls the agent makes:**

| Tool | Description |
|------|-------------|
| `update_field` | Set a specific form field value |
| `clear_field` | Clear a field (set to null) |
| `add_row` | Add a row to a repeatable section (e.g., emergency contacts) |
| `delete_row` | Remove a row from a repeatable section |
| `submit_step` | Signal that the current step is complete (forward only; backward disabled by voice) |
| `get_current_state` | Request the current form state from the app |

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SENA_AI_REDIS_URL` | Yes | `redis://localhost:6379` | Redis connection URL |
| `SENA_AI_GEMINI_API_KEY` | Yes | — | Google Generative AI API key |
| `SENA_AI_APP_WEBHOOK_URL` | Yes (prod) | `https://mock.example.com/webhooks/sena` | Backend webhook URL for completion events |
| `SENA_AI_APP_WEBHOOK_SECRET` | No | — | HMAC-SHA256 signing secret for webhook |
| `SENA_AI_ONBOARDING_PORT` | No | `8083` | Service port |
| `SENA_AI_GEMINI_LIVE_MODEL_ID` | No | `gemini-3.5-flash` | Gemini Live model ID |
| `SENA_AI_ONBOARDING_SESSION_MAX_MIN` | No | `60` | Hard session cap in minutes |
| `SENA_AI_ONBOARDING_SILENCE_TIMEOUT_SEC` | No | `8` | Seconds of silence before check-in prompt |
| `SENA_AI_ONBOARDING_CROSS_SCREEN_CONTEXT_ENABLED` | No | `true` | Share context across steps |
| `SENA_AI_ONBOARDING_TOOL_STATE_CHANNEL` | No | `true` | Option D: state passed in each tool_response |
| `SENA_AI_SCREEN_STATE_MAX_BYTES` | No | `8192` | Max size of screen_state payload |
| `SENA_AI_RESUMPTION_HANDLE_TTL_SEC` | No | `600` | Resumption handle TTL (10 min) |
| `SENA_AI_RESUMPTION_REPLAY_TURNS` | No | `4` | Turns to replay on session resume |
| `SENA_AI_ENVIRONMENT` | No | `development` | `development` / `production` |
| `SENA_AI_DEBUG` | No | `true` | Debug mode |

---

## Running the Service

**Install dependencies**
```bash
cd onboarding
pip install -e .      # installs from pyproject.toml
```

**Start Redis (local dev)**
```bash
docker run -p 6379:6379 redis:7
```

**Run service**
```bash
uvicorn onboarding.main:create_app --factory --reload --host 0.0.0.0 --port 8083
```

**For dev behind a proxy (Flutter/mobile):**
```bash
uvicorn src.onboarding.main:create_app --factory --reload --host 0.0.0.0 --port 8089 --forwarded-allow-ips='*' --proxy-headers
```

**Health checks:**
- Liveness: http://localhost:8083/health/live
- Readiness: http://localhost:8083/health/ready (checks Redis)

**Browser test harness:** http://localhost:8083/harness

---

## Integration Guide

### For Backend Teams

The backend:
1. Creates sessions via `POST /v1/onboarding/session` with the form schema and any pre-known field values
2. Passes `ws_url` from the response to the frontend
3. Can read or update form state at any time via `GET/PUT /v1/onboarding/session/{id}/state`
4. Calls `POST /v1/onboarding/session/{id}/complete` when the user confirms submission
5. Receives the collected data via webhook (`onboarding.session.completed`)

**Webhook payload structure:**
```json
{
  "event": "onboarding.session.completed",
  "session_id": "sess_abc123",
  "participant_id": "part_abc123",
  "tenant_id": "org_xyz",
  "step": "client_personal_details",
  "state": { "values": { "first_name": "Jane", ... } },
  "transcript": [ ... ],
  "started_at": "2026-06-01T10:00:00Z",
  "completed_at": "2026-06-01T10:12:00Z"
}
```

**Webhook verification (Python):**
```python
import hmac, hashlib

signature = hmac.new(
    WEBHOOK_SECRET.encode(),
    request.body,
    hashlib.sha256
).hexdigest()

assert signature == request.headers["X-SENA-AI-Signature"]
```

### For Frontend Teams

The frontend handles:
1. Opening the WebSocket with the `ws_url` received from the backend
2. Streaming microphone audio (PCM16 16kHz mono)
3. Playing back agent audio (PCM16 24kHz mono) in real time
4. Handling `tool_request` frames by updating the form UI and sending `tool_response`
5. Sending `screen_state` updates when the user navigates between form sections
6. Sending `validation_failed` / `validation_cleared` when the app validates a field

**Audio requirements:**
- Capture: PCM16, 16 kHz, mono — use `AudioWorklet` or `ScriptProcessorNode`
- Playback: PCM16, 24 kHz, mono — buffer and play via Web Audio API

**Tool response (must send after every tool_request):**
```json
{
  "type": "tool_response",
  "id": "<id from tool_request>",
  "result": { "success": true }
}
```
If you do not send a `tool_response`, the agent will stall waiting for confirmation.

**Session resumption flow:**
- On unexpected WebSocket close, check for `{"type":"resumable","handle":"<uuid>"}` frame
- Store the `handle` locally
- On reconnect, open `WSS /ws/onboarding/{session_id}?resume=<handle>`
- Agent will replay the last 4 turns for context continuity

---

### Pre-Integration Checklist

- [ ] Redis running and accessible (`SENA_AI_REDIS_URL` set)
- [ ] `SENA_AI_GEMINI_API_KEY` set to a valid Google AI API key
- [ ] `SENA_AI_APP_WEBHOOK_URL` set to the backend webhook endpoint
- [ ] `SENA_AI_APP_WEBHOOK_SECRET` set and backend validates webhook signature
- [ ] Form schema for each onboarding step agreed between frontend and backend
- [ ] Frontend can produce PCM16 16kHz mono audio
- [ ] Frontend handles `tool_request` frames and sends `tool_response` confirmations
- [ ] Frontend handles binary PCM16 24kHz audio playback
- [ ] Backend saves collected form state from webhook payload
- [ ] Cross-screen context enabled/disabled setting agreed (`SENA_AI_ONBOARDING_CROSS_SCREEN_CONTEXT_ENABLED`)

### What to Confirm Before Integration

1. **Form schema format** — The schema passed in `POST /session` defines what fields the agent collects. Confirm the schema structure with the backend team before integration.
2. **Step identifiers** — `client_personal_details`, `staff_employment`, etc. — confirm all step IDs.
3. **Who calls `/complete`?** — Backend triggers completion (not the voice agent). Confirm the backend flow for when to call this endpoint.
4. **Backward navigation** — Voice-based backward navigation is disabled. If a user wants to go back, they must use the UI. Confirm UX flow.
5. **Webhook reliability** — If webhook delivery fails after 3 retries, data is only in Redis (with TTL). Confirm whether the backend also polls for session state as a fallback.

---

## QA & Testing

### Test Scenarios

| Scenario | Expected |
|----------|----------|
| Full onboarding flow (all fields) | All fields populated, webhook delivered |
| Partial completion, disconnect, resume | Session state preserved; agent replays last 4 turns |
| Second WebSocket on same session | `error: session_locked` + close 4009 |
| Agent asks for field already provided | Agent skips, moves to next field |
| User says "I don't know" for optional field | Field left null, agent proceeds |
| User says "Go back" | Agent says back navigation is paused, asks to use UI |
| Silence > 8 seconds | Agent asks "Are you still there?" |
| Session expires during call | Server sends `go_away` with time remaining |
| Webhook delivery fails 3 times | `webhook_delivered: false`; session still marked complete |
| Missing `tool_response` from frontend | Agent stalls — confirm frontend always sends response |

### Known Edge Cases

- **Audio format mismatch** — If frontend sends anything other than PCM16 16kHz mono, Gemini Live will produce garbled output or errors. Confirm audio pipeline carefully.
- **Large schema** — Very complex form schemas may slow down prompt construction. Monitor first-response latency.
- **Cross-screen context** — If a prior step's data is incomplete, the agent may ask questions already answered in a previous step. Verify bootstrap data is populated correctly.
- **Repeatable rows** (`add_row` / `delete_row`) — Test adding and removing emergency contacts or other repeatable sections via voice — edge cases exist around index tracking.

---

## Implementation Status

### Done
- Session lifecycle (create, get state, update state, complete, errors)
- Gemini Live WebSocket bridge (v2 protocol)
- PCM16 audio streaming (16kHz in, 24kHz out)
- Tool calls: update_field, clear_field, add_row, delete_row, submit_step, get_current_state
- Redis session state (FormState, schema, bootstrap, transcript, WS lock)
- Cross-screen context (step summary bucket, participant name resolution)
- Webhook delivery with 3-retry exponential backoff + HMAC signing
- Session resumption (resume handle, turn replay)
- Silence monitoring
- Field validators (field-level, cross-field, sequencing)
- Client validation error telemetry
- Readiness probe (checks Redis)
- Browser test harness (`/harness`)

### Missing / Not Yet Implemented

| Item | Impact | Notes |
|------|--------|-------|
| Authentication | High | No auth middleware — relies on headers only (no verification of token) |
| Voice backward navigation | Medium | Disabled — user must use UI back button |
| Gemini tool grounding | Low | Feature-flagged off (`SENA_AI_ONBOARDING_GROUNDING_ENABLED=false`) — pending compliance sign-off |
| Debug log cleanup | Low | Temp debug log in `POST /session` — "Remove after Flutter bootstrap shape confirmed" |
| Dockerfile | Medium | Not present — container deployment not set up |

---

## Integration Requirements

**Mandatory before production integration:**

1. **Redis** — must be running and accessible from the service
2. **`SENA_AI_GEMINI_API_KEY`** — valid Google AI API key with Gemini Live access
3. **`SENA_AI_APP_WEBHOOK_URL`** — backend endpoint that receives completion webhooks
4. **`SENA_AI_APP_WEBHOOK_SECRET`** — signing secret; backend must verify `X-SENA-AI-Signature`
5. **Form schemas** — one per onboarding step, passed by backend when creating sessions
6. **Frontend audio pipeline** — PCM16 16kHz mono capture + PCM16 24kHz mono playback
7. **Frontend tool_response handling** — every `tool_request` must be answered
8. **Dockerfile** — required for containerised deployment

**Nice to have:**
- Authentication middleware (API key or JWT) before production
- Gemini data residency pinning to `australia-southeast1`
- Grounding enabled after compliance sign-off
