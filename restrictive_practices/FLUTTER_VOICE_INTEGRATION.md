# Flutter Voice Integration — Case Note Voice Assistant

This document describes the WebSocket contract between the Flutter app and the case-note voice assistant API.

---

## Overview

The voice assistant fills missing case-note fields in real time. It receives the current form state at session creation, asks only about empty fields, and updates the form as the worker answers.

**The assistant never auto-submits.** When all required fields are filled and the worker confirms, the server emits `session_complete`. The worker presses the Submit button on-screen to call `/evaluate`.

---

## 1. Session Lifecycle

### Step 1 — Create Session

```
POST /v1/restrictive-practices/voice/session
Content-Type: application/json
Authorization: Basic <base64(user:pass)>   # only if SENA_AI_BASIC_AUTH_USER is set

{
  "case_note_id": "<uuid>",
  "worker_id": "w-123",
  "client_id": "liam-001",
  "tenant_id": "t-1",                       // optional
  "worker_display_name": "Sarah",           // optional — used for greeting
  "initial_values": {                        // pre-filled fields (from /draft or manual entry)
    "shift": {
      "shift_date": "2026-05-21",
      "shift_time": "07:00-15:00",
      "worker_position": "Support Worker"
    },
    "activities": {
      "assisted": "morning routine, breakfast"
    }
  },
  "readonly_paths": [                        // fields the agent may NOT overwrite
    "shift.shift_date",
    "shift.worker_id",
    "shift.client_id"
  ]
}
```

Response:
```json
{
  "session_id": "<uuid>",
  "ws_url": "wss://host/v1/restrictive-practices/voice/ws/<uuid>?token=<opaque>",
  "expires_at": "2026-05-21T18:00:00Z"
}
```

### Step 2 — Connect WebSocket

Open `ws_url` verbatim (token is embedded in query param). Accept binary and text frames.

### Step 3 — Stream audio

Send raw PCM16 audio as **binary frames**:
- Sample rate: 16 kHz
- Channels: 1 (mono)
- Bit depth: 16-bit, little-endian
- Chunk size: 100ms (1600 samples, 3200 bytes) recommended

Receive PCM16 audio back as **binary frames**:
- Sample rate: 24 kHz
- Channels: 1 (mono)

### Step 4 — Session ends

When the worker confirms completion, receive `session_complete`. The WS closes naturally. Show the "Submit" button — do NOT auto-submit.

---

## 2. Text Events (JSON, sent as text frames)

### Server → Client events

| Event type | When | Payload |
|-----------|------|---------|
| `turn_start` | Agent starts speaking | — |
| `turn_complete` | Agent finishes speaking | — |
| `interrupted` | Worker spoke over agent | — |
| `user_said` | Worker speech transcribed | `{"text": "..."}` |
| `agent_said` | Agent speech transcribed | `{"text": "..."}` |
| `field_updated` | Field value captured | see below |
| `state` | Completion stats updated | `{"completion": {...}}` |
| `validation_rejection` | Field rejected by server | `{"section_id", "field_id", "code", "reason_human"}` |
| `session_complete` | All required fields done + confirmed | see below |
| `escalated` | Incident escalation logged | `{"reason", "transcript_excerpt", "session_id"}` |
| `go_away` | Gemini connection about to drop | `{"time_left_ms": <int>}` |
| `error` | Server-side error | `{"code", "message"}` |
| `screen_state_ack` | Debug only (SENA_AI_DEBUG=true) | `{"accepted", "version"}` |

#### `field_updated` payload

```json
{
  "type": "field_updated",
  "section_id": "wellbeing",
  "field_id": "mood",
  "value": "settled",
  "confidence": 0.95,
  "pending_confirmation": false
}
```

When `pending_confirmation: true`, the agent is reading back a low-confidence capture and waiting for the worker to confirm. Mirror the value tentatively in the UI.

#### `session_complete` payload

```json
{
  "type": "session_complete",
  "session_id": "<uuid>",
  "case_note_id": "<uuid>",
  "payload": {
    "case_note_id": "<uuid>",
    "client_id": "liam-001",
    "worker_id": "w-123",
    "shift_date": "2026-05-21",
    "shift_time": "07:00-15:00",
    "worker_position": "Support Worker",
    "describe": "Morning shift at Liam's house...",
    "assisted": "personal care, breakfast",
    "practised_skill": null,
    "participants_level_of_independence": null,
    "observations": null,
    "mood": "settled",
    "behavioural_events": null,
    "any_concerns": null,
    "what_went_well": "Liam was engaged and cooperative.",
    "what_needs_further_support": null,
    "participant_comments": null,
    "medication_reminders_given": null,
    "safety_hazards_observed": null,
    "any_injuries": false,
    "injury_description": null,
    "uploaded_documents": null,
    "carer_feedback": null,
    "incident_occurred": false
  },
  "completion": {
    "required_total": 6,
    "required_filled": 6,
    "optional_total": 14,
    "optional_filled": 3
  }
}
```

Use `payload` to update the form fields before showing the Submit button.

### Client → Server events (text frames)

| Message type | When to send | Payload |
|-------------|-------------|---------|
| `audio_end` | User lifted finger from mic (optional) | `{"type": "audio_end"}` |
| `user_text` | Text input fallback | `{"type": "user_text", "text": "..."}` |
| `screen_state_v2` | On focus change or `any_injuries` toggle | see below |
| `validation_failed` | Client-side validation rejects a field | `{"type": "validation_failed", "section_id", "field_id", "reason_human", "code"}` |
| `validation_cleared` | Validation error resolved | `{"type": "validation_cleared", "section_id", "field_id"}` |
| `stop` | User taps the end-session button | `{"type": "stop"}` |

---

## 3. `screen_state_v2` Contract

Send whenever the visible set of fields changes — particularly when `any_injuries` toggles (which shows/hides `injury_description`).

```json
{
  "type": "screen_state_v2",
  "data": {
    "step_id": "case_note",
    "fields": [
      {"section_id": "shift", "field_id": "shift_date", "status": "filled"},
      {"section_id": "shift", "field_id": "shift_time", "status": "empty"},
      {"section_id": "safety", "field_id": "any_injuries", "status": "filled"},
      {"section_id": "safety", "field_id": "injury_description", "status": "empty"}
    ],
    "field_errors": {}
  }
}
```

Field `status` values:
- `"filled"` — field has a value (treated as already captured; agent skips it)
- `"empty"` — field is visible and empty (agent may ask)

Fields absent from the `fields` list are treated as not rendered — agent will not ask about them.

---

## 4. Audio Protocol Notes

- Do NOT implement client-side echo cancellation by gating mic on agent speech — this breaks VAD. The server uses `START_OF_ACTIVITY_INTERRUPTS` which handles barge-in natively.
- Send audio continuously while the mic is open. Stop when the user lifts their finger or session ends.
- Binary audio frames and JSON text frames can be interleaved freely.

---

## 5. Error Codes

| WS close code | Meaning |
|--------------|---------|
| 4004 | Session not found (expired or invalid session_id) |
| 4009 | Another WebSocket is already connected for this session |
| 4011 | Invalid or expired session token |

---

## 6. Security Notes

- The session token is in the WebSocket query param (`?token=…`). It is a single-use opaque UUID. Do not log or display it.
- Upgrade path for production: move token to `Sec-WebSocket-Protocol` subprotocol header to prevent URL logging by reverse proxies.
- Sessions expire after `SENA_AI_VOICE_SESSION_MAX_SEC` seconds (default: 3600). After expiry, the WS closes with 4004 on next connect.

---

## 7. Environment Variables (server-side)

| Var | Default | Notes |
|-----|---------|-------|
| `SENA_AI_GEMINI_API_KEY` | `""` | **Required** for voice |
| `SENA_AI_GEMINI_LIVE_MODEL_ID` | `gemini-3.1-flash-live-preview` | Live model |
| `SENA_AI_REDIS_URL` | `redis://localhost:6379/0` | Session state |
| `SENA_AI_VOICE_SESSION_MAX_SEC` | `3600` | Session TTL (seconds) |
| `SENA_AI_VOICE_SILENCE_TIMEOUT_SEC` | `8` | Silence watchdog threshold; 0 to disable |
| `SENA_AI_VOICE_GROUNDING_ENABLED` | `false` | Enable Google Search grounding |

---

## 8. Field Sections Reference

| Section ID | Fields |
|-----------|--------|
| `shift` | `shift_date`*, `shift_time`*, `worker_position`* |
| `summary` | `describe`* |
| `activities` | `assisted`*, `practised_skill`, `participants_level_of_independence`, `observations` |
| `wellbeing` | `mood`*, `behavioural_events`, `any_concerns` |
| `outcomes` | `what_went_well`, `what_needs_further_support`, `participant_comments` |
| `safety` | `medication_reminders_given`, `safety_hazards_observed`, `any_injuries`, `injury_description`† |
| `incidents` | `carer_feedback`, `incident_occurred` |

\* Required field — must be filled before `finish_session` succeeds  
† Required only when `any_injuries = true` (`visible_if` conditional)
