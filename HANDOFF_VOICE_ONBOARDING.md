# Handoff — SENA Voice Onboarding Integration

> **For the parent session (Flutter app):** Read this file first. It tells you exactly what the backend does, what's built, what changed, and what you need to wire up on the Flutter side.

> ✅ **2026-04-29 — v2 implemented.** Backend is now aligned to the real Flutter codebase. Key changes: `screen_state_v2` message type, `field_apply` envelope, `add_repeatable_row` tool, `voice_coverage` enforcement, `about_me` field rename. The WS server still accepts v1 `screen_state` via adapter. See §v2 changes below.

---

## What this service is

An AI voice agent that interviews a participant during NDIS onboarding. The Flutter app opens a WebSocket, streams mic audio, and Gemini Live handles the conversation. The agent fills out a structured form by calling tools as the user speaks. When all required fields are captured, a webhook fires and the WS closes automatically.

**Backend repo:** `SENA/sena-ai/services/onboarding/` (port 8083)  
**Backend plan:** `SENA/.planning/ONBOARDING_VOICE_API_PLAN.md`  
**Flutter integration guide:** `SENA/FLUTTER_VOICE_INTEGRATION.md` ← full Dart code samples

---

## What's built and working (backend)

| Phase | What | Status |
|-------|------|--------|
| A | REST: session create/read/write/complete + Redis FormState | ✓ 36/36 tests |
| B | WebSocket + Gemini Live audio bridge + form-aware system prompt | ✓ |
| C | Tool calling: `update_field`, `get_session_context`, `advance_step`, `escalate_incident` | ✓ 48/48 tests |
| F (partial) | Browser test harness at `GET /harness` | ✓ |

**Run backend:**
```bash
cd SENA/sena-ai/services/onboarding
pip install -e .
uvicorn src.onboarding.main:create_app --factory --reload --port 8083
```

---

## Plan change — Screen ingress scrapped

**Original Phase D** was going to send camera/screen frames as binary blobs over WS.  
**New approach:** The Flutter app maintains a **live JSON object** representing the current screen state (what's visible, what step, what fields are pre-filled from the app side). This JSON is sent to the backend so Gemini has context about what the user sees — no frame capture, no image processing.

**What this means for backend:** A new WS message type (e.g. `{"type": "screen_state", "data": {...}}`) needs to be handled. Backend injects the screen JSON into Gemini's context as a text turn or tool response.

**What this means for Flutter:** The app needs to:
1. Maintain the current screen state as a JSON snapshot
2. Send it over the open WS when it changes (or on demand)
3. The backend will handle the rest

**This replaces Phase D entirely.** Phase D is no longer blocked.

---

## The WS protocol (what Flutter must implement)

### Connect + handshake
```
WSS ws://<host>:8083/ws/onboarding/{session_id}
```
First message Flutter sends after connect:
```json
{"type": "start"}
```
Server replies:
```json
{
  "type": "ready",
  "state": { "...FormState..." },
  "prompt_version": "v2",
  "coverage": ["basics.full_name", "basics.date_of_birth", "basics.phone", "basics.email", "basics.about_me"]
}
```
`coverage` — list of dotted `section_id.field_id` paths that the voice agent is allowed to fill. Flutter should use this to show/hide the mic affordance per field.

### Audio streaming
- Flutter → server: **binary frames** — raw PCM16, 16kHz, mono
- Server → Flutter: **binary frames** — raw PCM16, 24kHz, mono (Gemini output)

### New message Flutter needs to send (screen state)
```json
{
  "type": "screen_state",
  "data": {
    "current_screen": "personal_information",
    "visible_fields": ["full_name", "date_of_birth", "phone"],
    "prefilled": {
      "full_name": "John Smith"
    },
    "app_context": "user is on step 1 of 5"
  }
}
```
> Shape of `data` is flexible — backend will relay it to Gemini as context. Define the exact schema collaboratively.

### Server → Flutter events (already implemented)
| `type` | When |
|--------|------|
| `ready` | Handshake complete — includes `prompt_version` and `coverage` array |
| `user_said` | Transcription of user speech |
| `agent_said` | Transcription of AI reply |
| `field_updated` | AI captured a field (`section`, `field`, `value`, `confidence`) — legacy |
| `field_apply` | **v2** — drive GetX controller directly: `{type, section_id, field_id, row_index, value, source:"voice", confidence}` |
| `state` | Full FormState after any mutation |
| `row_added` | Repeatable row added: `{type, section_id, new_index}` |
| `step_completed` | All required fields done, webhook fired, WS closes |
| `escalated` | Safety flag — session continues, do NOT close |
| `screen_state_ack` | Debug only — echoed when `screen_state` or `screen_state_v2` accepted |
| `error` | Error with `code` + `message` |

### New Flutter → Server messages (v2)
```json
{
  "type": "screen_state_v2",
  "data": {
    "step_id": "personal_information",
    "focused_section": "basics",
    "focused_field": "phone",
    "field_status": {
      "basics.full_name": "filled",
      "basics.date_of_birth": "filled",
      "basics.phone": "empty",
      "basics.email": "empty",
      "basics.about_me": "empty"
    },
    "repeatable_rows": {},
    "ui_flags": {}
  }
}
```
> v1 `screen_state` is still accepted via an adapter — no Flutter migration required yet.

### WS close codes
| Code | Meaning |
|------|---------|
| 4004 | Session not found / schema missing |
| 4008 | Protocol error (first msg wasn't `start`) |
| 4009 | Session locked (another WS already open) |

---

## FormState shape (what the backend tracks)

```json
{
  "session_id": "uuid",
  "step_id": "personal_information",
  "completed": false,
  "values": {
    "basics": {
      "full_name":     { "value": "John Smith", "source": "voice", "confidence": 0.95 },
      "date_of_birth": { "value": null, "source": null },
      "phone":         { "value": null, "source": null }
    }
  },
  "completion": {
    "required_filled": 1,
    "required_total": 3,
    "complete": false
  }
}
```

---

## REST endpoints Flutter uses

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/v1/onboarding/session` | Create session — pass `step_id` + full schema inline |
| `GET`  | `/v1/onboarding/session/{id}/state` | Read current FormState |
| `PUT`  | `/v1/onboarding/session/{id}/state` | Pre-fill fields (only when WS is NOT active — returns 409 otherwise) |
| `POST` | `/v1/onboarding/session/{id}/complete` | Force-complete + fire webhook (REST fallback) |

**Session create body:**
```json
{
  "tenant_id": "org-uuid",
  "participant_id": "participant-uuid",
  "step_id": "personal_information",
  "schema": { ...full StepSchema JSON... }
}
```
Schemas for all 5 steps are at `SENA/sena-ai/services/onboarding/fixtures/schema_<step_id>.json`.

---

## What needs to happen next (backend side)

1. **Handle `screen_state` WS message** — parse `data`, relay to Gemini as a context injection (text turn or inline tool response). Agree on exact `data` schema with Flutter dev first.
2. **Phase E** — session resumption (reconnect with handle, agent recalls prior turn) + Google Search grounding for NDIS policy questions.
3. **Phase F** — OpenAPI docs + Postman collection for mobile team.

---

## Key files in backend repo

```
sena-ai/services/onboarding/
├── src/onboarding/
│   ├── api/routes.py          # REST endpoints
│   ├── api/ws_routes.py       # WebSocket handler ← main file
│   ├── services/gemini_live.py # Gemini Live bridge (b2g/g2b tasks)
│   ├── services/tools.py      # 4 tool handlers
│   ├── services/prompt_builder.py # System prompt renderer
│   ├── repositories/state_repo.py # Redis FormState store
│   └── models/
│       ├── form_state.py      # FormState, FieldValue
│       └── schema_spec.py     # StepSchema, FieldSpec, visible_if
├── fixtures/
│   ├── schema_personal_information.json
│   ├── schema_participant_requirements.json
│   ├── schema_ndis_plan_details.json
│   ├── schema_documents.json
│   └── schema_medical_information.json
└── test_harness.html          # Browser test client at /harness
```

---

## Auth (MVP)

Currently `dev_header` mode — no JWT. Pass `X-User-Id` and `X-User-Roles` headers.  
JWT mode is a pluggable seam, not yet activated.

---

## Who to talk to

Backend AI layer: `SENA/` repo (this session).  
Flutter app + screens: parent repo (your session).  
Shared API contract: `SENA/api_contracts.py`.
