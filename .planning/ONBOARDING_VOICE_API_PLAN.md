---
title: SENA Voice Onboarding API — Implementation Plan
scope: Tasks #3–#8 consolidated (form-aware prompt, tool calling, camera/screen frames, session resumption, Google Search grounding) delivered as an API service for the existing SENA mobile app
status: draft — awaiting approval
author: Claude + user
created: 2026-04-20
updated: 2026-04-20
---

# SENA Voice Onboarding API — Implementation Plan

## 1. Overview

The SENA mobile app already exists. Screens in `SENA SCREENS ONBORDING/` show the real, shipped onboarding flow: 5 steps (Personal Information, Participant Requirements, NDIS Plan Details, Documents, Medical Information) plus a separate Consent Sharing flow.

We build a **standalone Python service** that the mobile app integrates with to deliver a voice-driven alternative path through the same form. The service handles:

- Real-time voice conversation with Gemini Live
- Per-turn derivation of form values via tool calls
- Session state + transcript persistence (Redis, ephemeral)
- Event stream over WebSocket to the app
- Webhook to the app backend on step completion

The mobile app keeps ownership of: UI, final persistence, authentication, file/photo uploads, and business rules.

This plan consolidates six previously separate tasks (#3 form-aware prompt, #4 tool calling, #5 camera frames, #6 screen frames, #7 session resumption, #8 Google Search grounding) into a single cohesive delivery.

### Goals

1. Zero frontend obligation — the mobile app integrates directly; test harness is disposable.
2. Clean HTTP + WS API surface documented for mobile engineers.
3. All six planned capabilities shipped behind the same session model.
4. Incremental phases that each produce a working, demoable artifact.

### Non-goals (MVP)

- Authentication (documented seam, no implementation)
- Document/photo uploads via voice (app handles separately)
- Multi-tenant isolation beyond a pass-through `tenant_id`
- Postgres persistence of onboarding data (webhook-only; app owns the database)
- LiveKit (direct browser-grade WS is sufficient for MVP)

---

## 2. Integration Model

```
┌─────────────────┐       ┌───────────────────────────┐       ┌──────────────┐
│                 │ HTTPS │                           │ HTTPS │              │
│  SENA mobile    │─────► │  SENA AI Voice Service    │──────►│  App Backend │
│  app            │  WSS  │  (this repo, new service) │       │  (mock URL)  │
│                 │◄─────►│                           │       │              │
└─────────────────┘       └─────────────┬─────────────┘       └──────────────┘
                                        │
                                        │ WSS
                                        ▼
                              ┌───────────────────┐
                              │  Gemini Live API  │
                              │  (Google)         │
                              └───────────────────┘
```

**Session lifecycle (one voice session = one onboarding step):**

1. Mobile app completes REST `POST /v1/onboarding/session` with participant_id, step, and the step's schema (supplied by the app backend).
2. App receives `session_id` + `ws_url`.
3. App opens WS, sends `{"type":"start"}`, streams microphone audio as binary frames.
4. Gemini agent conducts dialog. Each field it captures triggers a tool call, which our service turns into a `field_updated` event streamed back to the app.
5. When the agent has filled all required fields and the user confirms, agent calls `advance_step` → we fire the webhook to the app backend and send `step_completed` to the app.
6. App closes WS, opens a new session for the next step.

---

## 3. Decisions (locked) and Defaults

| # | Decision | Value | Source |
|---|----------|-------|--------|
| 1 | Webhook target | Mock URL via `SENA_AI_APP_WEBHOOK_URL` env var | user |
| 2 | Authentication | Skip MVP; pluggable middleware stub for later | user |
| 3 | Session scope | One session == one onboarding step | user |
| 4 | Schema ownership | App backend owns it; passes inline in session-create payload | user |
| 5 | FormState writer during session | Voice only; app may PUT only when WS closed | user |
| 6 | File/photo capture via voice | Skipped; app handles separately | user |
| 7 | Locale | `en-AU` (Australian English) | user |
| 8 | Multi-tenant | Deferred; `tenant_id` is a pass-through field only | inferred |
| 9 | Gender enum (fallback) | Male, Female, Non-binary, Prefer not to say, Other | default |
| 10 | Plan Management enum | "Plan Managed", "Self Managed", "Agency Managed" | default |
| 11 | AU State enum | NSW, VIC, QLD, WA, SA, TAS, ACT, NT | default |
| 12 | Emergency contacts | Min 1, max 5 (configurable per schema) | default |
| 13 | Interpreter language | Conditional: only if `interpreter_required == true` | inferred |
| 14 | Service Address shortcut | `same_as_home: boolean` field on schema | inferred |
| 15 | Session TTL | 15 min inactivity, 60 min absolute max | default |
| 16 | Resumption handle TTL | 30 min | default |
| 17 | Model | `gemini-3.1-flash-live-preview` | CLAUDE.md rule |
| 18 | Audio in/out | 16 kHz PCM in, 24 kHz PCM out (client upsamples) | existing demo |

Enum defaults (9–11) are **fallbacks only**. The schema the app sends overrides these per session. The service stays dumb about the exact enum values.

---

## 4. API Contract

### 4.1 REST

#### Create session
```
POST /v1/onboarding/session
Content-Type: application/json
```
Request body:
```jsonc
{
  "participant_id": "uuid",
  "step": "personal_information",          // step identifier (one of app's 5)
  "schema": { /* Schema object — see §5.1 */ },
  "initial_state": { /* partial FormState if resuming this step */ },
  "locale": "en-AU",
  "tenant_id": "optional-opaque-string"
}
```
Response `201`:
```jsonc
{
  "session_id": "uuid",
  "ws_url": "wss://<host>/ws/onboarding/<session_id>",
  "expires_at": "2026-04-20T10:15:00Z",
  "resumption_handle": null
}
```

#### Get state
```
GET /v1/onboarding/session/{session_id}/state → 200 FormState
```

#### Update state (app-side edits between voice sessions)
```
PUT /v1/onboarding/session/{session_id}/state
```
Returns `409 Conflict` if an active WS holds the session lock.

#### Complete / finalize
```
POST /v1/onboarding/session/{session_id}/complete
```
Marks session complete, fires webhook, closes WS. Usually triggered by the `advance_step` tool, but available as an explicit REST call for fallback.

#### Health
```
GET /health/live, GET /health/ready
```

### 4.2 WebSocket

**Endpoint:** `wss://<host>/ws/onboarding/{session_id}`

**Frame types:**
- **Binary frames** → raw audio PCM only. Client → server: 16 kHz mono. Server → client: 24 kHz mono.
- **Text frames** → JSON envelopes. All control, media (non-audio), transcripts, tool events, state.

This split keeps audio low-overhead and every other interaction structured/inspectable.

#### Client → Server JSON messages

```jsonc
// Open session (first text message after WS open)
{"type":"start", "resumption_handle": null}

// Typed user input (alternative to voice, optional)
{"type":"user_text", "text":"My name is Aditya."}

// Camera frame (JPEG, base64). Max 2 fps enforced server-side.
{"type":"camera_frame", "data":"<b64>", "mime_type":"image/jpeg"}

// Screen frame (JPEG, base64) showing current form view
{"type":"screen_frame", "data":"<b64>", "mime_type":"image/jpeg"}

// Manual end-of-utterance override
{"type":"audio_end"}

// Client-initiated stop
{"type":"stop"}
```

#### Server → Client JSON messages

```jsonc
// Session is live
{"type":"ready", "state": <FormState>, "prompt_version": "v1"}

// Transcripts (from Gemini input/output transcription)
{"type":"user_said", "text":"My name is Aditya"}
{"type":"agent_said", "text":"Thanks, Aditya. What's your date of birth?"}

// Field captured (from update_field tool call)
{"type":"field_updated",
 "section":"basics",
 "field":"full_name",
 "value":"Aditya",
 "repeatable_index": null,
 "confidence": 0.95,
 "turn_id": 3}

// Full state snapshot after every mutation
{"type":"state", "state": <FormState>}

// Step done (from advance_step tool call)
{"type":"step_completed", "state": <FormState>}

// Escalation (from escalate_incident tool)
{"type":"escalated",
 "reason":"abuse|self_harm|safety|other",
 "transcript_excerpt":"..."}

// Resumption handle (emitted periodically + on disconnect)
{"type":"resumption_handle", "handle":"<opaque>"}

// Errors
{"type":"error", "code":"schema_invalid", "message":"..."}
```

### 4.3 Webhook (server → app backend)

```
POST <SENA_AI_APP_WEBHOOK_URL>
Content-Type: application/json
X-SENA-AI-Event: onboarding.session.completed
X-SENA-AI-Signature: <hmac-sha256-hex>       // stub in MVP
```
Body:
```jsonc
{
  "event": "onboarding.session.completed",
  "session_id": "uuid",
  "participant_id": "uuid",
  "tenant_id": "...",
  "step": "personal_information",
  "state": { /* final FormState */ },
  "transcript": [{"speaker":"user","text":"..."}, {"speaker":"agent","text":"..."}],
  "started_at": "...",
  "completed_at": "..."
}
```
Retry policy: 3 attempts, exponential backoff (1s → 4s → 16s). Terminal failure logs to `wiki/log.md` for operator review; no persistent dead-letter in MVP.

---

## 5. Data Models

### 5.1 Schema spec (what the app sends)

```jsonc
{
  "version": "v1",
  "step_id": "personal_information",
  "step_label": "Personal Information",
  "progress_percent": 20,
  "sections": [
    {
      "id": "basics",
      "label": "About you",
      "fields": [
        {"id":"full_name", "type":"text", "required":true, "label":"Full Name"},
        {"id":"email", "type":"email", "required":true},
        {"id":"phone", "type":"phone", "format":"+61", "required":true},
        {"id":"date_of_birth", "type":"date", "required":true},
        {"id":"gender", "type":"enum",
         "options":["Male","Female","Non-binary","Prefer not to say","Other"],
         "required":true},
        {"id":"bio", "type":"textarea", "required":true, "label":"A bit about me"},
        {"id":"preferred_language", "type":"text", "required":true},
        {"id":"interpreter_required", "type":"boolean", "required":true},
        {"id":"interpreter_language", "type":"text", "required":false,
         "visible_if": {"interpreter_required": true}}
      ]
    },
    {
      "id": "home_address",
      "label": "Home address",
      "fields": [
        {"id":"address", "type":"text", "required":true},
        {"id":"state", "type":"enum",
         "options":["NSW","VIC","QLD","WA","SA","TAS","ACT","NT"], "required":true},
        {"id":"city", "type":"text", "required":true},
        {"id":"zip_code", "type":"text", "pattern":"^\\d{4}$", "required":true}
      ]
    },
    {
      "id": "service_address",
      "label": "Service address",
      "copy_from_if_flagged": "home_address",
      "flag_field": {"id":"service_same_as_home", "type":"boolean", "default":true},
      "fields": [ /* same shape as home_address */ ]
    },
    {
      "id": "emergency_contacts",
      "label": "Emergency contacts",
      "repeatable": {"min":1, "max":5},
      "item_fields": [
        {"id":"name", "type":"text", "required":true},
        {"id":"relation", "type":"enum",
         "options":["Parent","Sibling","Partner","Friend","Carer","Other"], "required":true},
        {"id":"email", "type":"email", "required":true},
        {"id":"phone", "type":"phone", "format":"+61", "required":true}
      ]
    }
  ]
}
```

Field types supported: `text`, `textarea`, `email`, `phone`, `date`, `time`, `number`, `currency`, `boolean`, `enum`, `multi_enum`.

### 5.2 FormState

```jsonc
{
  "session_id": "uuid",
  "step_id": "personal_information",
  "started_at": "...",
  "updated_at": "...",
  "values": {
    "basics": {
      "full_name": {"value":"Aditya", "source":"voice", "confidence":0.95, "turn_id":3},
      "email": null,
      "interpreter_required": {"value":false, "source":"voice", "confidence":0.99, "turn_id":5}
    },
    "home_address": { /* ... */ },
    "emergency_contacts": [
      {"name": {"value":"Sarah Brown", "source":"voice", "turn_id":9}, "relation": null, ... }
    ]
  },
  "completion": {
    "required_total": 12,
    "required_filled": 3,
    "optional_total": 2,
    "optional_filled": 0,
    "complete": false
  },
  "transcript_count": 14,
  "escalations": []
}
```

Every captured value is wrapped in a `FieldValue` object with `source` ("voice"|"app"|"system") and `confidence`. App can show low-confidence values in a review UI before committing.

### 5.3 Redis keys

| Key | Type | TTL | Purpose |
|-----|------|-----|---------|
| `sena:onboarding:session:{sid}` | JSON string | 60m | FormState blob |
| `sena:onboarding:session:{sid}:transcript` | List<JSON> | 60m | Ordered transcript log |
| `sena:onboarding:session:{sid}:schema` | JSON string | 60m | Schema for this session |
| `sena:onboarding:session:{sid}:last_frame:camera` | Binary | 5m | Most recent camera frame (for debug) |
| `sena:onboarding:session:{sid}:last_frame:screen` | Binary | 5m | Most recent screen frame |
| `sena:onboarding:resumption:{handle}` | String | 30m | handle → session_id mapping |
| `sena:onboarding:ws_lock:{sid}` | String | 60m | Single-writer lock for active WS |

---

## 6. System Prompt

Template (stored at `services/onboarding/prompts/onboarding_system.md`, rendered per session):

```
You are Sena, an Australian voice assistant helping NDIS participants complete
their onboarding in Australian English. Your current task: collect the
"{step_label}" step ({progress_percent}% of onboarding).

CRITICAL RULES
- Speak Australian English. Use local phrasing and spelling ("mum", "mobile", "postcode").
- Ask ONE question at a time. Wait for the answer. Briefly confirm before moving on.
- Only ask about fields in the SCHEMA below. Follow section order, then field order.
- Every time the user supplies a value, call `update_field` with that value.
- For ambiguous input, ask the user to confirm before calling `update_field`.
- Respect `visible_if`: skip fields whose condition is not met.
- For repeatable sections, ask if the user wants to add another before exiting.
- If the user asks an NDIS policy question you don't know, offer to look it up
  (Google Search grounding available).
- If the user reports abuse, safety concern, or self-harm, call
  `escalate_incident` immediately, then continue calmly.
- When every required field is filled and the user confirms, call `advance_step`.

TONE
- Warm, respectful, unhurried. Concise. Do not over-explain.
- Never read the raw schema to the user.
- Do not read back every value — confirm at section boundaries only.

SCHEMA
{schema_json}

CURRENT STATE (values already captured)
{current_state_json}

If CURRENT STATE has filled values, skip those fields unless the user asks to
change them. Continue from the first unfilled required field.
```

The prompt is re-rendered at session start (and on resumption) with the live `CURRENT STATE`, not every turn.

---

## 7. Tool Declarations

```python
FUNCTION_DECLS = [
    {
        "name": "update_field",
        "description": "Record a value the user provided for a field. Call every time you capture a value.",
        "parameters": {
            "type": "object",
            "properties": {
                "section": {"type": "string"},
                "field": {"type": "string"},
                "value": {"type": "string"},
                "repeatable_index": {"type": "integer", "nullable": True},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["section", "field", "value"],
        },
    },
    {
        "name": "get_session_context",
        "description": "Fetch current FormState and schema. Call if unsure what has been filled.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "advance_step",
        "description": "Call when every required field is filled and the user confirms this step is complete.",
        "parameters": {
            "type": "object",
            "properties": {"confirmation_transcript": {"type": "string"}},
        },
    },
    {
        "name": "escalate_incident",
        "description": "User reported abuse, a safety concern, or self-harm.",
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "enum": ["abuse", "self_harm", "safety", "other"]},
                "transcript_excerpt": {"type": "string"},
            },
            "required": ["reason"],
        },
    },
]
```

`google_search` grounding is added as a separate `types.Tool(google_search=types.GoogleSearch())` entry, gated by `SENA_AI_ONBOARDING_GROUNDING_ENABLED`.

Vision (camera/screen frames) is **not a tool** — frames are piped directly into `send_realtime_input(video=Blob(...))` and are implicit context for the model. The app just sends them.

---

## 8. Build Phases

Each phase ends with a demoable acceptance criterion.

### Phase A — Scaffold + REST (foundation)

- New service at `sena-ai/services/onboarding/` mirroring the `voice/` layout.
- Pydantic models for Schema and FormState (`models/`).
- Redis-backed `FormStateRepo` (`repositories/state_repo.py`).
- REST routes: create, get, put, complete, health (`api/routes.py`).
- Webhook dispatcher with retry (`services/webhook.py`).
- Fixture schemas for each of the 5 steps under `fixtures/`.
- Unit tests: schema validation, state transitions, webhook retry, conflict on active WS.

**Acceptance:** `curl` through session create → put state → complete; mock webhook receives payload.

### Phase B — WS + Gemini Live + system prompt (#3)

- WS route at `/ws/onboarding/{session_id}`.
- `GeminiLiveSession` wrapper ported from working demo, using `send_realtime_input(audio=Blob)` pattern. **No legacy `session.send()` path.**
- System prompt builder (`services/prompt_builder.py`) injecting schema + current state.
- VAD config + input/output transcription enabled.
- Broadcasts `user_said`, `agent_said` on every transcript event.
- WS lock: exactly one active WS per session (409/close on second).

**Acceptance:** Test harness opens WS, speaks name, Sena asks next question. Transcripts stream.

### Phase C — Tool calling (#4)

- `ToolDispatcher` (`services/tools.py`) with four handlers.
- `update_field`: validate against schema → write Redis → emit `field_updated` + fresh `state`.
- `get_session_context`: return condensed FormState + section progress.
- `advance_step`: validate completion → fire webhook → emit `step_completed` → close WS cleanly.
- `escalate_incident`: append to escalations list → emit `escalated` → continue session.
- Confidence threshold: values with < 0.6 confidence annotated in state but surfaced to app anyway.

**Acceptance:** Multi-turn dialog fills all required fields → webhook hits mock URL with final state.

### Phase D — Vision ingress (#5 + #6)

- WS handler accepts `camera_frame` and `screen_frame` JSON messages.
- Server decodes base64 → forwards via `send_realtime_input(video=Blob(..., "image/jpeg"))`.
- Rate limit: 2 fps per frame type (token bucket in Redis).
- Prompt addendum: "When a camera or screen image is shown, you may reference it if relevant."

**Acceptance:** Hold up a handwritten note — on request, agent reads it. Sending screen of current form — agent can point out which field is focused.

### Phase E — Resumption + Grounding (#7 + #8)

- Enable `session_resumption` in `LiveConnectConfig`.
- Capture `session_resumption_update.new_handle`; persist in Redis (30 min TTL); emit `resumption_handle` event to client periodically.
- On `{"type":"start","resumption_handle":"..."}`, look up handle → reopen Live connection with `types.SessionResumptionConfig(handle=...)`.
- Add `google_search` tool to config when `SENA_AI_ONBOARDING_GROUNDING_ENABLED=true`.
- Prompt addendum: "You may use Google Search for current NDIS policy questions. Cite the source in your answer."

**Acceptance:** Kill WS mid-session → reconnect with handle → agent recalls prior turn. Ask an NDIS policy question → grounded answer with citation.

### Phase F — Integration surface

**Partial delivery (2026-04-21) — browser test harness shipped early:**
- `test_harness.html` — Phase A/B/C panels (session create, voice, live form render + completion bar) ✓
- `GET /harness` + `GET /harness/fixtures/{step_id}` routes in `main.py` ✓ (path-traversal guarded)
- Access: `http://localhost:8083/harness` (requires `pip install -e .` before uvicorn)
- Phases D/E panels are placeholder stubs — will be wired as those phases ship

**Remaining F work:**
- OpenAPI auto-docs at `/docs` (FastAPI default).
- Hand-written `docs/WS_PROTOCOL.md` covering every frame type and error.
- `docs/INTEGRATION.md` — happy-path recipe for mobile team.
- Postman collection at `docs/postman/onboarding.postman_collection.json`.
- Update `test_harness.html` with Phase D (camera/screen) + Phase E (resumption) panels.

**Acceptance:** Mobile engineer can integrate by reading docs alone. Postman runs the happy path end-to-end against the mock webhook.

---

## 9. File Layout (new)

```
sena-ai/services/onboarding/
├── pyproject.toml
├── src/onboarding/
│   ├── main.py                      # FastAPI factory
│   ├── core/
│   │   ├── settings.py              # pydantic-settings, SENA_AI_ prefix
│   │   └── logging.py
│   ├── api/
│   │   ├── routes.py                # REST
│   │   ├── ws_routes.py             # WebSocket
│   │   └── deps.py
│   ├── models/
│   │   ├── schema_spec.py           # Schema + Field Pydantic
│   │   └── form_state.py            # FormState + FieldValue Pydantic
│   ├── repositories/
│   │   └── state_repo.py            # Redis I/O
│   ├── services/
│   │   ├── gemini_live.py           # Gemini Live session wrapper (ported from demo)
│   │   ├── prompt_builder.py
│   │   ├── tools.py                 # Tool dispatcher
│   │   ├── webhook.py               # Outbound webhook with retry
│   │   └── transcript_store.py
│   ├── prompts/
│   │   └── onboarding_system.md
│   └── fixtures/
│       ├── schema_personal_information.json
│       ├── schema_participant_requirements.json
│       ├── schema_ndis_plan_details.json
│       ├── schema_documents.json
│       └── schema_medical_information.json
└── tests/
    ├── test_schema.py
    ├── test_state_repo.py
    ├── test_ws_flow.py
    ├── test_tools.py
    └── test_webhook.py

docs/
├── WS_PROTOCOL.md
├── INTEGRATION.md
└── postman/onboarding.postman_collection.json
```

No changes to existing `voice/` service. `demo_live_server.py` stays as-is (reference), may be updated in Phase F to target the new service for harness purposes.

---

## 10. Environment Variables

```
SENA_AI_GEMINI_API_KEY=...                               # existing
SENA_AI_GEMINI_LIVE_MODEL_ID=gemini-3.1-flash-live-preview
SENA_AI_ONBOARDING_PORT=8083
SENA_AI_APP_WEBHOOK_URL=https://mock.example.com/webhooks/sena
SENA_AI_APP_WEBHOOK_SECRET=                              # stub MVP
SENA_AI_ONBOARDING_SESSION_TTL_MIN=15
SENA_AI_ONBOARDING_SESSION_MAX_MIN=60
SENA_AI_ONBOARDING_RESUMPTION_TTL_MIN=30
SENA_AI_ONBOARDING_GROUNDING_ENABLED=true
SENA_AI_ONBOARDING_FRAME_FPS_LIMIT=2
SENA_AI_REDIS_URL=redis://localhost:6379
```

---

## 11. Open Questions (non-blocking for MVP)

| # | Question | Blocking? | Owner |
|---|----------|-----------|-------|
| 1 | Does the app backend already have a draft schema shape we must conform to, or do we propose §5.1 and they conform? | No — our shape is the proposal | app team |
| 2 | Final auth scheme (JWT from app? API key? Both?) | No | security |
| 3 | HMAC rotation strategy for the webhook signature | No | ops |
| 4 | Multi-tenant isolation pattern beyond `tenant_id` pass-through | No | eng |
| 5 | Should `escalate_incident` also page a human (PagerDuty/email)? | No — log only MVP | product |
| 6 | Is Google Search grounding acceptable for NDIS policy answers? Cost + content-safety implications | No | product |
| 7 | AU data residency for Gemini Live (production blocker, not MVP) | Eventually | legal |

---

## 12. Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Gemini Live hard-caps WS at ~10 min | Phase E session resumption |
| Hallucinated field values | `confidence` on every `update_field`; app shows review UI |
| Schema drift between app and service | App sends schema per session; we validate against Pydantic |
| High voice latency breaks conversational feel | Keep working demo's async architecture; test on LTE and WiFi |
| Webhook target down | Retry with backoff; log terminal failure; no silent data loss |
| Proactive audio not supported on `gemini-3.1-flash-live-preview` | User must speak first; greeting triggered by first utterance (documented in CLAUDE.md) |
| WS lock thrashing on flaky networks | TTL on lock; resumption handle bypasses fresh-create |

---

## 13. Out of Scope (this plan)

- Postgres persistence (app backend owns the DB of record)
- OAuth / JWT authentication
- Rate limiting (added with auth)
- LiveKit integration
- Flow B (case-note dictation) — separate service
- Consent Sharing flow (screens 7–14) — can be added as a 6th `step_id` later using the same infrastructure; the schema spec already supports it

---

## 14. Acceptance Summary

The plan is done when:

1. Mobile engineer can create a voice onboarding session with a POST, open a WS, and watch fields populate as the user speaks.
2. On step completion, the app backend mock receives a signed webhook with the final FormState and transcript.
3. Camera and screen frames flow end-to-end; the agent can reference them.
4. A mid-session disconnect is fully recoverable via the resumption handle.
5. NDIS policy questions are answerable with a grounded web search when enabled.
6. `docs/INTEGRATION.md` is sufficient for integration without direct engineering support.
