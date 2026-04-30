# Handoff — SENA Voice Onboarding Integration

> **For the parent session (Flutter app):** Read this file first. It tells you exactly what the backend does, what's built, what changed, and what you need to wire up on the Flutter side.

> ✅ **2026-04-29 — v2 verified 15/16.** Backend aligned to the real Flutter codebase. All v2 modules verified live: `screen_state_v2` message type, `field_apply` envelope, `add_repeatable_row` tool + `row_added` emit, `voice_coverage` enforcement, `about_me` field rename, `coverage` array in ready envelope. v1 `screen_state` still accepted via `from_v1()` adapter — no Flutter migration required to start. **One known gap:** WS close code **4011** (`policy_block`) for grounding-required policy questions when grounding is off — not yet implemented.

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
| C | Tool calling: `update_field`, `get_session_context`, `advance_step`, `escalate_incident`, **`add_repeatable_row`** (v2) | ✓ 48/48 tests |
| D | `screen_state` JSON ingest → `screen_context.py` → Gemini text injection | ✓ |
| E | Session resumption (`resumable` envelope, GETDEL handle, close 4010) + Google Search grounding (flag-gated) | ✓ |
| F | OpenAPI `/docs` + `WS_PROTOCOL.md` + `postman_collection.json` + browser harness at `/harness` | ✓ |
| v2 | `screen_state_v2` typed contract, `field_apply` envelope, `voice_coverage` enforcement, `coverage` in ready, `prompt_version:"v2"`, `about_me` field rename | ✓ verified 2026-04-29 |
| — | Close code **4011** (`policy_block`) | ❌ pending |

**Run backend:**
```bash
cd SENA/sena-ai/services/onboarding
pip install -e .
uvicorn src.onboarding.main:create_app --factory --reload --port 8083
```

---

## Plan change — Screen ingress scrapped (DONE)

**Original Phase D** was going to send camera/screen frames as binary blobs over WS.
**Shipped approach:** Flutter sends a **live JSON snapshot** of the current screen state. Backend deduplicates by payload hash, validates, and injects into Gemini as a text turn (`render_injection_text`).

Two shapes are accepted:
- **v1** `screen_state` — generic `{current_screen, visible_fields, prefilled, app_context}`. Routed through `from_v1()` adapter — keep working until you migrate.
- **v2** `screen_state_v2` — typed, GetX-shaped: `{step_id, focused_section, focused_field, field_status, repeatable_rows, ui_flags}`. **Preferred.**

Per-message size cap: `SCREEN_STATE_MAX_BYTES` (default 8192).

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
| Code | Meaning | Status |
|------|---------|--------|
| 4004 | Session not found / schema missing | ✓ |
| 4008 | Protocol error (first msg wasn't `start`) | ✓ |
| 4009 | Session locked (another WS already open) | ✓ |
| 4010 | Resumption error (handle invalid/expired) | ✓ |
| 4011 | `policy_block` — grounding-required NDIS policy question while grounding is off | ❌ planned |

### Resumption (Phase E)

Server may emit a one-shot `resumable` envelope before close, containing a single-use handle. To resume:

```json
// Reconnect with handle in start payload
{"type": "start", "resume": "<handle>"}
```

The server redeems via Redis GETDEL (single-use), replays last N turns, and continues. Handle TTL is `RESUMPTION_HANDLE_TTL_SEC` (default 600s). Replay window is `RESUMPTION_REPLAY_TURNS` (default 4).

### Grounding (Phase E, flag-gated)

`SENA_AI_ONBOARDING_GROUNDING_ENABLED` (default `false`). When on, `build_live_tools` adds the `GoogleSearch` tool so the agent can answer NDIS policy questions citing live sources. When off, the model must defer with a graceful "I can't answer policy questions right now" — and (once 4011 lands) the server will close with code 4011 if the user pushes for a policy answer.

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

Phases A–F + v2 contract are done. Remaining gap:

1. **Implement WS close code 4011 (`policy_block`)** in `services/gemini_live.py` — fires when grounding is disabled and the user asks a grounding-required NDIS policy question (model defers, server closes).

After that: production hardening (data residency sign-off for Gemini Live AU, ephemeral browser-side tokens, JWT auth seam activation) — see `.planning/PRD_REMAINING_PHASES.md`.

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
