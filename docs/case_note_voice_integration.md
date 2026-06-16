# Case Note Voice Assistant — Master Integration Guide

**For:** Flutter Frontend Developer  
**Service:** Case Review Service (port 8084) — NOT the onboarding service  
**Feature:** Voice-dictated case note for staff after a shift  
**Source of truth:** `services/case_review/api/voice_routes.py`, `services/case_review/voice/`, `services/shared/src/sena_common/voice/`  
**Last updated:** 2026-06-16

> This document is generated from actual backend code. Every field name, type, status code, and message is verified against source files. No assumptions.

---

## Table of Contents

1. [Base URL](#1-base-url)
2. [Auth](#2-auth)
3. [REST API — POST /session](#3-rest-api--post-session)
4. [REST API — POST /draft (optional pre-fill)](#4-rest-api--post-draft-optional-pre-fill)
5. [WebSocket Connection](#5-websocket-connection)
6. [WebSocket Close Codes](#6-websocket-close-codes)
7. [Server → Flutter messages](#7-server--flutter-messages)
8. [Flutter → Server messages](#8-flutter--server-messages)
9. [Audio Format](#9-audio-format)
10. [Tool Request Protocol — MUST IMPLEMENT](#10-tool-request-protocol--must-implement)
11. [All 4 Tools — Exact Shapes](#11-all-4-tools--exact-shapes)
12. [Full Field Schema (from casenote_schema.py)](#12-full-field-schema-from-casenote_schemapy)
13. [Mic Muting — Echo Prevention (MANDATORY)](#13-mic-muting--echo-prevention-mandatory)
14. [Full Session Lifecycle](#14-full-session-lifecycle)
15. [Flutter Dart Skeleton](#15-flutter-dart-skeleton)

---

## 1. Base URL

```
http://3.111.109.14:8080
```

| Endpoint | Full URL |
|----------|----------|
| Create session | `POST http://3.111.109.14:8080/case-review/v1/case-review/voice/session` |
| Draft from transcript | `POST http://3.111.109.14:8080/case-review/v1/case-review/voice/draft` |
| WebSocket | `ws://3.111.109.14:8080/case-review/ws/case-review/voice/{session_id}` |
| Swagger docs | `http://3.111.109.14:8080/case-review/docs` |

> **No TLS on this IP** — `http://` and `ws://` (not https/wss). If nginx adds TLS later, switch to `https://` and `wss://`.

---

## 2. Auth

All requests require these headers. For the WebSocket, send as **headers on the upgrade request** (Flutter `WebSocket.connect` headers map). Browsers cannot set WS upgrade headers — use query params for web-based testing only.

| Header | Required | Value |
|--------|----------|-------|
| `X-Tenant-Id` | **YES** | Tenant UUID — session is scoped to this. Missing = 4401 close |
| `X-Participant-Id` | recommended | Staff member UUID — used for ownership check |
| `X-User-Roles` | **YES** | `worker` or `staff` or `support_worker` or `admin` (comma-separated if multiple). Not staff = 403 / 4403 |

**Query param fallback (WS only, for browser demo harness):**
```
ws://3.111.109.14:8080/case-review/ws/case-review/voice/{session_id}?tenant_id=...&participant_id=...&roles=worker
```

---

## 3. REST API — POST /session

Creates a tenant-scoped ephemeral voice session in Redis. Must be called before opening the WebSocket.

### Request

```
POST http://3.111.109.14:8080/case-review/v1/case-review/voice/session
Content-Type: application/json
X-Tenant-Id: <tenant UUID>
X-Participant-Id: <staff UUID>
X-User-Roles: worker
```

**Body (JSON):**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `client_id` | string | **YES** | The client/participant UUID the case note is about |
| `shift_id` | string | **YES** | The shift UUID this note covers |
| `initial_values` | `dict[str, dict[str, any]]` | no (default `{}`) | Pre-filled field values (from `/draft` or manual entry). Keys are section IDs, values are field-ID→value maps |

**Example body (empty session):**
```json
{
  "client_id": "4f2a1b3c-...",
  "shift_id": "7e8d9f0a-...",
  "initial_values": {}
}
```

**Example body (pre-filled from /draft):**
```json
{
  "client_id": "4f2a1b3c-...",
  "shift_id": "7e8d9f0a-...",
  "initial_values": {
    "summary": {
      "summaryOfShift": "Assisted James with morning routine and medication"
    },
    "activitiesAndSkill": {
      "assisted": "Morning hygiene, breakfast preparation"
    }
  }
}
```

### Response 201 Created

```json
{
  "session_id": "a3f1c2d4e5b6...",
  "ws_url": "/ws/case-review/voice/a3f1c2d4e5b6..."
}
```

> `ws_url` is a relative path. Prepend `ws://3.111.109.14:8080/case-review` to get the full URL.  
> Full WS URL: `ws://3.111.109.14:8080/case-review/ws/case-review/voice/{session_id}`

### Error Responses

| Status | Body | Cause |
|--------|------|-------|
| 403 | `{"code":"not_staff","message":"Voice case notes are staff-only"}` | Role not in {worker, staff, support_worker, admin} |

---

## 4. REST API — POST /draft (optional pre-fill)

Extracts case note fields from a text transcript using Bedrock Claude Sonnet. Use this if you have a pre-recorded audio transcript and want to pre-fill the form before the live voice session starts.

**This endpoint is optional.** If you don't have a transcript, skip it and pass `initial_values: {}` to `/session`.

### Request

```
POST http://3.111.109.14:8080/case-review/v1/case-review/voice/draft
Content-Type: application/json
X-Tenant-Id: <tenant UUID>
X-User-Roles: worker
```

**Body (JSON):**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `transcript` | string | **YES** | Raw text of the shift transcript |

```json
{
  "transcript": "Today I assisted James with his morning routine. He was in a good mood. We practised his cooking skills. Medication reminder was given at 8am..."
}
```

### Response 200 OK

| Field | Type | Description |
|-------|------|-------------|
| `initial_values` | `dict[str, dict[str, any]]` | Extracted fields, keyed by section/field. Pass directly to `/session` |
| `gaps_note` | `string \| null` | Human-readable note about fields Bedrock could not fill |
| `filled_count` | int | Number of fields extracted |

```json
{
  "initial_values": {
    "summary": { "summaryOfShift": "Assisted James with morning routine..." },
    "activitiesAndSkill": { "assisted": "Morning hygiene, breakfast" },
    "safetyAndHealth": { "medicationReminderGiven": true }
  },
  "gaps_note": "Handover note and behavioural events were not mentioned.",
  "filled_count": 8
}
```

### Error Responses

| Status | Body | Cause |
|--------|------|-------|
| 403 | `{"code":"not_staff","message":"Voice case notes are staff-only"}` | Not staff role |

---

## 5. WebSocket Connection

### URL

```
ws://3.111.109.14:8080/case-review/ws/case-review/voice/{session_id}
```

### Connection sequence

1. Open WebSocket with auth headers
2. If rejected → receive `{"type":"error","code":"...","message":"..."}` then close with a 4xxx code (see §6)
3. If accepted → **immediately send the handshake message:**

**Flutter → Server (first message, required):**
```json
{"type": "hello"}
```
or
```json
{"type": "start"}
```
Either is accepted. Any other type or malformed JSON → server closes with 4008.

4. Server responds with `ready` event (see §7)
5. Start streaming mic audio as binary frames

---

## 6. WebSocket Close Codes

The server sends `{"type":"error","code":"...","message":"..."}` text frame **before** closing. Always listen for error frames before the close event.

| Code | Reason string | Cause |
|------|--------------|-------|
| `4401` | `unauthenticated` | Missing `X-Tenant-Id` header/param |
| `4403` | `not_staff` | Role not in staff set |
| `4403` | `forbidden` | Session belongs to a different tenant |
| `4004` | `session_not_found` | Session expired or wrong tenant |
| `4009` | `session_locked` | Another WebSocket already open for this session |
| `4008` | `protocol_error` | First message was not `{"type":"hello"}` or `{"type":"start"}` |
| `1011` | `internal_error` | Unhandled server exception |

---

## 7. Server → Flutter Messages

### Text frames (JSON)

#### `ready` — session live, start mic

Sent immediately after the server receives `{"type":"hello"}`.

```json
{
  "type": "ready",
  "state": { /* FormState JSON — current field values */ },
  "prompt_version": "v2",
  "coverage": [
    "summary.summaryOfShift",
    "activitiesAndSkill.assisted",
    "activitiesAndSkill.practisedSkill",
    "activitiesAndSkill.participantsLevelOfIndependence",
    "activitiesAndSkill.observation",
    "wellbeingAndBehaviour.mood",
    "wellbeingAndBehaviour.behaviouralEvents",
    "wellbeingAndBehaviour.anyConcerns",
    "outcomesAndProgress.whatWentWell",
    "outcomesAndProgress.furtherSupport",
    "outcomesAndProgress.participantsComments",
    "safetyAndHealth.medicationReminderGiven",
    "safetyAndHealth.safetyHazardObserved",
    "safetyAndHealth.anyInjuries",
    "safetyAndHealth.injuryDetails",
    "feedback.careFeedback",
    "feedback.anyIncident",
    "handover.handover"
  ]
}
```

> `coverage` = all voice-eligible field paths. All 18 fields are voice-eligible.

---

#### `turn_start` — agent started speaking

```json
{"type": "turn_start"}
```

**Flutter action required:** Set `_agentSpeaking = true`. Mute the microphone (stop sending audio frames or gate them). Also send `{"type":"audio_end"}` to flush Gemini's VAD buffer of any echo frames already in flight.

---

#### `turn_complete` — agent finished speaking

```json
{"type": "turn_complete"}
```

**Flutter action required:** Set `_agentSpeaking = false`. Unmute the microphone.

---

#### `interrupted` — user interrupted agent

```json
{"type": "interrupted"}
```

**Flutter action required:** Set `_agentSpeaking = false`. Clear the audio playback queue. Unmute mic.

---

#### `user_said` — user speech transcript

```json
{"type": "user_said", "text": "I'm done for today, please submit"}
```

Display in transcript UI.

---

#### `agent_said` — agent speech transcript

```json
{"type": "agent_said", "text": "Got it — I've saved the summary. What's next?"}
```

Display in transcript UI.

---

#### `go_away` — Gemini session expiring

```json
{"type": "go_away", "time_left_ms": 30000}
```

Gemini Live sessions have a ~10 minute lifetime. This fires when expiry is close. **Flutter action:** show a warning or trigger session resumption before `time_left_ms` elapses. If the session closes without resumption, the user loses the unsaved state.

---

#### `error` — server error

```json
{"type": "error", "code": "internal_error", "message": "Internal server error"}
```

Always sent as a text frame before the WS close frame.

---

#### `tool_request` — Gemini wants Flutter to do something

**This is the most important message.** See §10 and §11 for full details.

```json
{
  "type": "tool_request",
  "request_id": "3f7a2b1c-...",
  "tool": "update_field",
  "args": {
    "section": "summary",
    "field": "summaryOfShift",
    "value": "Assisted James with his morning routine"
  }
}
```

**Flutter must respond within 5 seconds.** Timeout = `{ok: false}` returned to Gemini.

---

### Binary frames

Raw PCM audio from Gemini (agent speech). **Format: 16-bit signed little-endian PCM, mono, 24kHz.**

Decode and play through the device speaker. Do NOT play audio when `_agentSpeaking = false` — only play between `turn_start` and `turn_complete`/`interrupted`.

---

## 8. Flutter → Server Messages

### Binary frames

Raw mic audio. **Format: 16-bit signed little-endian PCM, mono, 16kHz.**

Send continuously while mic is active and `_agentSpeaking == false`.

---

### Text frames (JSON)

#### `audio_end` — signal mic paused

```json
{"type": "audio_end"}
```

Send whenever the mic is paused or muted (including on `turn_start`). This flushes Gemini's VAD buffer to prevent echo from being processed as user speech.

---

#### `tool_response` — reply to a `tool_request`

```json
{
  "type": "tool_response",
  "request_id": "3f7a2b1c-...",
  "result": {
    "ok": true,
    "state": { /* current FormState */ }
  }
}
```

`request_id` must match the `tool_request`. See §10 and §11 for full result shapes per tool.

---

#### `user_text` — optional text input

```json
{"type": "user_text", "text": "My name is James"}
```

Send if the user types instead of speaking.

---

#### `screen_state` — optional screen context injection (v1)

```json
{
  "type": "screen_state",
  "data": {
    "current_screen": "case_note",
    "visible_fields": ["summary.summaryOfShift"],
    "prefilled": {}
  }
}
```

Optional. Injects current screen context into Gemini's prompt so it knows what the user is looking at.

---

#### `screen_state_v2` — optional screen context (v2)

```json
{
  "type": "screen_state_v2",
  "turn": { /* TurnPayload */ },
  "data": {
    "step_id": "staff_case_note",
    "focused_section": "summary",
    "focused_field": "summaryOfShift",
    "field_status": {},
    "field_errors": {}
  }
}
```

---

#### `validation_failed` — client-side validation failed

```json
{
  "type": "validation_failed",
  "section_id": "handover",
  "field_id": "handover",
  "reason_human": "Handover note must be at least 5 characters",
  "code": "min_length",
  "repeatable_index": null
}
```

Send when Flutter-side validation rejects a value. The server injects this as text into Gemini's context so it can tell the user what's wrong.

---

#### `validation_cleared` — client validation cleared

```json
{
  "type": "validation_cleared",
  "section_id": "handover",
  "field_id": "handover",
  "repeatable_index": null
}
```

Send when the previously failed field is now valid.

---

#### `stop` — end session early

```json
{"type": "stop"}
```

Send if the user explicitly dismisses the voice session before `finalize_note` completes.

---

## 9. Audio Format

| Direction | Format | Sample Rate | Bit Depth | Channels |
|-----------|--------|-------------|-----------|----------|
| Flutter → Server (mic) | Raw PCM, little-endian signed | **16kHz** | 16-bit | Mono |
| Server → Flutter (agent) | Raw PCM, little-endian signed | **24kHz** | 16-bit | Mono |

MIME type for mic audio: `audio/pcm;rate=16000`

---

## 10. Tool Request Protocol — MUST IMPLEMENT

### How it works

When Gemini wants to save a field, clear a field, read state, or submit the note, the server sends a `tool_request` over the WebSocket. **Flutter is the authority on form state** (mobile-proxy model). The server is a relay.

```
Gemini → Backend → Flutter   (tool_request)
Flutter → Backend → Gemini   (tool_response)
```

**Rules:**
- Flutter must respond with `tool_response` within **5 seconds**. Timeout → `{ok: false, reason: "Validation timed out", code: "mobile_timeout"}` is returned to Gemini automatically.
- `request_id` in the response must match the `request_id` from the request.
- The `result` shape varies per tool — see §11.
- After `finalize_note` returns `{ok: true}`, the **backend closes the WebSocket automatically**. Flutter does not need to close it.

### Message shapes

**Server → Flutter (tool_request):**
```json
{
  "type": "tool_request",
  "request_id": "<uuid>",
  "tool": "<tool_name>",
  "args": { /* tool-specific */ }
}
```

**Flutter → Server (tool_response):**
```json
{
  "type": "tool_response",
  "request_id": "<same uuid>",
  "result": { /* tool-specific result */ }
}
```

---

## 11. All 4 Tools — Exact Shapes

### Tool 1: `update_field`

**When:** Gemini captured a field value the user dictated.

**Server sends:**
```json
{
  "type": "tool_request",
  "request_id": "abc123",
  "tool": "update_field",
  "args": {
    "section": "summary",
    "field": "summaryOfShift",
    "value": "Assisted James with morning routine and medication"
  }
}
```

> `value` is **always a string**, even for boolean fields. The backend coerces:
> - Boolean → `"true"` or `"false"` (string)
> - Number → `"309362545"` (string)
> - Date → `"YYYY-MM-DD"` (string)

Optional field in `args`:
- `repeatable_index` (int, 0-based) — only for repeatable sections (none in case note — all case note sections are non-repeatable)

**Flutter responds — success:**
```json
{
  "type": "tool_response",
  "request_id": "abc123",
  "result": {
    "ok": true,
    "state": { /* current FormState snapshot — see note below */ }
  }
}
```

**Flutter responds — validation failed:**
```json
{
  "type": "tool_response",
  "request_id": "abc123",
  "result": {
    "ok": false,
    "reason": "Handover note must be at least 5 characters"
  }
}
```

> The `state` key in `{ok:true}` responses is the **Option D state channel** — Gemini uses it as its source of truth for what's been filled. Include it. Shape: whatever your `_buildCurrentState()` produces (see §12 for field paths).

---

### Tool 2: `clear_field`

**When:** Gemini wants to blank out a field the user asked to remove.

**Server sends:**
```json
{
  "type": "tool_request",
  "request_id": "def456",
  "tool": "clear_field",
  "args": {
    "section": "wellbeingAndBehaviour",
    "field": "mood"
  }
}
```

Optional: `repeatable_index` (int)

**Flutter responds:**
```json
{
  "type": "tool_response",
  "request_id": "def456",
  "result": {
    "ok": true,
    "state": { /* current FormState snapshot */ }
  }
}
```

---

### Tool 3: `get_current_state`

**When:** Gemini wants to re-read the full form state (e.g. after 3+ turns without a state update, or if user said "I just typed it in").

**Server sends:**
```json
{
  "type": "tool_request",
  "request_id": "ghi789",
  "tool": "get_current_state",
  "args": {}
}
```

**Flutter responds:**
```json
{
  "type": "tool_response",
  "request_id": "ghi789",
  "result": {
    "ok": true,
    "state": {
      "visible_fields": [
        { "path": "summary.summaryOfShift", "value": "Assisted James...", "label": "Summary of Shift" },
        { "path": "activitiesAndSkill.assisted", "value": null, "label": "Assisted With" }
      ],
      "next_target": {
        "path": "activitiesAndSkill.assisted",
        "label": "Assisted With",
        "reason": "Required field not filled"
      }
    }
  }
}
```

---

### Tool 4: `finalize_note`

**When:** Gemini has confirmed with the staff member that all fields are done and they want to submit.

**Server sends:**
```json
{
  "type": "tool_request",
  "request_id": "jkl012",
  "tool": "finalize_note",
  "args": {
    "confirmation_transcript": "Yes I'm done, please submit"
  }
}
```

**Flutter responds — all fields valid, submit to app backend:**
```json
{
  "type": "tool_response",
  "request_id": "jkl012",
  "result": {
    "ok": true
  }
}
```

> ⚠️ **NDIS non-negotiable:** Only return `{ok:true}` after you have **successfully submitted the note to the app backend**. This `{ok:true}` is the human-in-the-loop confirmation gate. Never auto-return true without submitting.  
> After backend receives `{ok:true}`, it **closes the WebSocket automatically**. You do not need to close it.

**Flutter responds — missing required fields:**
```json
{
  "type": "tool_response",
  "request_id": "jkl012",
  "result": {
    "ok": false,
    "blockers": [
      {
        "path": "handover.handover",
        "label": "Handover Note",
        "reason": "This field is required"
      },
      {
        "path": "outcomesAndProgress.whatWentWell",
        "label": "What Went Well",
        "reason": "This field is required"
      }
    ]
  }
}
```

> Gemini will read the **first blocker's reason** aloud to the staff member and ask them to fill it.

---

## 12. Full Field Schema (from `casenote_schema.py`)

**Source of truth:** `services/case_review/voice/casenote_schema.py`

All fields are voice-eligible. All required unless marked optional.

| Section ID | Field ID | Type | Required | Label | Notes |
|------------|----------|------|----------|-------|-------|
| `summary` | `summaryOfShift` | textarea | ✓ | Summary of Shift | |
| `activitiesAndSkill` | `assisted` | textarea | ✓ | Assisted With | |
| `activitiesAndSkill` | `practisedSkill` | textarea | ✓ | Skill Practised | |
| `activitiesAndSkill` | `participantsLevelOfIndependence` | textarea | ✓ | Participant's Level of Independence | |
| `activitiesAndSkill` | `observation` | textarea | ✓ | Observation | |
| `wellbeingAndBehaviour` | `mood` | text | ✓ | Mood | |
| `wellbeingAndBehaviour` | `behaviouralEvents` | textarea | ✓ | Behavioural Events | |
| `wellbeingAndBehaviour` | `anyConcerns` | boolean | ✓ | Any Concerns? | Voice sends `"true"`/`"false"` string |
| `outcomesAndProgress` | `whatWentWell` | textarea | ✓ | What Went Well | |
| `outcomesAndProgress` | `furtherSupport` | textarea | ✓ | Further Support Needed | |
| `outcomesAndProgress` | `participantsComments` | textarea | ✓ | Participant's Comments | |
| `safetyAndHealth` | `medicationReminderGiven` | boolean | ✓ | Medication Reminder Given? | Voice sends `"true"`/`"false"` string |
| `safetyAndHealth` | `safetyHazardObserved` | boolean | ✓ | Safety Hazard Observed? | Voice sends `"true"`/`"false"` string |
| `safetyAndHealth` | `anyInjuries` | boolean | ✓ | Any Injuries? | Voice sends `"true"`/`"false"` string |
| `safetyAndHealth` | `injuryDetails` | textarea | **optional** | Injury Details | Only visible/collected when `anyInjuries = true` |
| `feedback` | `careFeedback` | textarea | ✓ | Care Feedback | |
| `feedback` | `anyIncident` | boolean | ✓ | Any Incident? | Voice sends `"true"`/`"false"` string |
| `handover` | `handover` | textarea | ✓ | Handover Note | Min 5 chars (Flutter validator `requiredWithMinMax(5,1000)`) |

**Total: 18 fields, 17 required, 1 optional (injuryDetails)**

### Boolean handling

Voice always sends booleans as strings. Flutter must handle both:
```dart
// value from tool_request args may be "true"/"false" OR true/false
bool parseBool(dynamic v) =>
    v is bool ? v : v.toString().toLowerCase() == 'true';
```

### `finalize_note` blockers path format

`path` in blockers = `"<section_id>.<field_id>"` e.g. `"handover.handover"`, `"safetyAndHealth.anyInjuries"`

---

## 13. Mic Muting — Echo Prevention (MANDATORY)

The server **never** gates audio on its side — it always forwards audio to Gemini unconditionally. Flutter **must** mute the mic during agent speech to prevent echo.

**Rules (from `rules/gemini.md`):**

```
on turn_start  → _agentSpeaking = true  → stop sending audio frames
                                         → send {"type":"audio_end"}  ← flushes Gemini VAD buffer
on turn_complete → _agentSpeaking = false → resume sending audio frames
on interrupted   → _agentSpeaking = false → clear audio queue + resume
```

Do NOT stop the microphone recorder itself — just gate the stream listener:
```dart
void _sendAudio(Uint8List chunk) {
  if (!_agentSpeaking) {
    _wsChannel.sink.add(chunk); // binary frame
  }
}
```

---

## 14. Full Session Lifecycle

```
Flutter                          Backend                         Gemini
  │                                 │                               │
  │── POST /session ───────────────>│                               │
  │<── {session_id, ws_url} ────────│                               │
  │                                 │                               │
  │── WS connect ──────────────────>│                               │
  │── {"type":"hello"} ────────────>│                               │
  │<── {"type":"ready", state, coverage} ──│                        │
  │                                 │── Gemini Live connect ───────>│
  │                                 │                               │
  │── [mic audio binary] ──────────>│── send_realtime_input(audio) >│
  │                                 │                               │── processes ──>
  │                                 │<── model_turn (audio chunks) ─│
  │<── {"type":"turn_start"} ───────│                               │
  │── {"type":"audio_end"} ────────>│── send_realtime_input(audio_stream_end) │
  │<── [agent audio binary] ────────│                               │
  │<── {"type":"turn_complete"} ────│                               │
  │── [mic audio binary] ──────────>│                               │
  │                                 │                               │
  │    [... conversation turns ...]                                 │
  │                                 │                               │
  │                                 │<── tool_call: update_field ───│
  │<── {"type":"tool_request","tool":"update_field","args":{...}} ──│
  │   [Flutter applies to FormState]│                               │
  │── {"type":"tool_response","result":{"ok":true,"state":{...}}} ->│
  │                                 │── send_tool_response ────────>│
  │                                 │                               │
  │    [... more turns ...]                                         │
  │                                 │                               │
  │                                 │<── tool_call: finalize_note ──│
  │<── {"type":"tool_request","tool":"finalize_note","args":{...}} ─│
  │   [Flutter validates all fields]│                               │
  │   [Flutter submits to app backend]                              │
  │── {"type":"tool_response","result":{"ok":true}} ───────────────>│
  │                                 │── send_tool_response ────────>│
  │                                 │   [step_completed = True]     │
  │                                 │   [WS session closes]         │
  │<── WS close (normal) ───────────│                               │
```

**Error path — missing fields:**
```
  │<── {"type":"tool_request","tool":"finalize_note",...} ──────────│
  │   [Flutter finds missing fields]│                               │
  │── {"type":"tool_response","result":{"ok":false,"blockers":[...]}} >│
  │                                 │── send_tool_response ────────>│
  │                                 │      [step_completed NOT set] │
  │<── {"type":"turn_start"} ───────│                               │
  │<── [Gemini reads first blocker aloud] ──────────────────────────│
  │<── {"type":"turn_complete"} ────│                               │
  │    [session continues...]       │                               │
```

---

## 15. Flutter Dart Skeleton

Minimal structure the frontend dev needs to implement. Adapt to your state management.

```dart
import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

class CaseNoteVoiceSession {
  WebSocketChannel? _ws;
  bool _agentSpeaking = false;
  final _pendingTools = <String, Completer<void>>{};

  Future<void> connect(String sessionId, String tenantId, String participantId) async {
    final uri = Uri.parse(
      'ws://3.111.109.14:8080/case-review/ws/case-review/voice/$sessionId'
    );
    _ws = WebSocketChannel.connect(uri, headers: {
      'X-Tenant-Id': tenantId,
      'X-Participant-Id': participantId,
      'X-User-Roles': 'worker',
    });

    // Step 1: send handshake
    _ws!.sink.add(json.encode({'type': 'hello'}));

    // Step 2: listen
    _ws!.stream.listen(_handleMessage, onError: _handleError, onDone: _handleDone);
  }

  void _handleMessage(dynamic message) {
    if (message is Uint8List) {
      // Agent audio — play if agent is speaking
      if (_agentSpeaking) _playAudio(message);
      return;
    }
    final data = json.decode(message as String) as Map<String, dynamic>;
    switch (data['type']) {
      case 'ready':
        _onReady(data);
      case 'turn_start':
        _agentSpeaking = true;
        _ws!.sink.add(json.encode({'type': 'audio_end'})); // flush VAD buffer
      case 'turn_complete':
        _agentSpeaking = false;
      case 'interrupted':
        _agentSpeaking = false;
        _clearAudioQueue();
      case 'user_said':
        _updateTranscript('user', data['text'] as String);
      case 'agent_said':
        _updateTranscript('agent', data['text'] as String);
      case 'go_away':
        _onGoAway(data['time_left_ms'] as int);
      case 'tool_request':
        _handleToolRequest(data);
      case 'error':
        _onError(data['code'] as String, data['message'] as String);
    }
  }

  Future<void> _handleToolRequest(Map<String, dynamic> req) async {
    final requestId = req['request_id'] as String;
    final tool = req['tool'] as String;
    final args = req['args'] as Map<String, dynamic>;

    Map<String, dynamic> result;
    switch (tool) {
      case 'update_field':
        result = await _applyUpdateField(
          section: args['section'] as String,
          field: args['field'] as String,
          value: args['value'],
          repeatableIndex: args['repeatable_index'] as int?,
        );
      case 'clear_field':
        result = _applyClearField(
          section: args['section'] as String,
          field: args['field'] as String,
        );
      case 'get_current_state':
        result = {'ok': true, 'state': _buildCurrentState()};
      case 'finalize_note':
        result = await _finalizeNote(
          confirmationTranscript: args['confirmation_transcript'] as String,
        );
      default:
        result = {'ok': false, 'reason': 'Unknown tool: $tool'};
    }

    _ws!.sink.add(json.encode({
      'type': 'tool_response',
      'request_id': requestId,
      'result': result,
    }));
  }

  Future<Map<String, dynamic>> _applyUpdateField({
    required String section,
    required String field,
    required dynamic value,
    int? repeatableIndex,
  }) async {
    // Apply to your FormState / controllers
    // value is always a string — parse boolean fields: value == 'true'
    // Return current state snapshot
    final ok = _applyToFormState(section, field, value);
    if (!ok) return {'ok': false, 'reason': 'Validation failed'};
    return {'ok': true, 'state': _buildCurrentState()};
  }

  Map<String, dynamic> _applyClearField({required String section, required String field}) {
    _clearFromFormState(section, field);
    return {'ok': true, 'state': _buildCurrentState()};
  }

  Future<Map<String, dynamic>> _finalizeNote({required String confirmationTranscript}) async {
    // 1. Validate ALL required fields
    final blockers = _validateAllFields();
    if (blockers.isNotEmpty) {
      return {'ok': false, 'blockers': blockers};
    }
    // 2. Submit to app backend — MUST succeed before returning ok:true
    final submitted = await _submitToAppBackend();
    if (!submitted) {
      return {'ok': false, 'reason': 'Failed to submit case note'};
    }
    // 3. Return ok:true — backend will close WS automatically
    return {'ok': true};
  }

  List<Map<String, dynamic>> _validateAllFields() {
    final blockers = <Map<String, dynamic>>[];
    // Check each required field — add to blockers if empty
    // Example:
    if (_formState.summary.summaryOfShift.isEmpty) {
      blockers.add({
        'path': 'summary.summaryOfShift',
        'label': 'Summary of Shift',
        'reason': 'This field is required',
      });
    }
    // ... check all 17 required fields
    return blockers;
  }

  Map<String, dynamic> _buildCurrentState() {
    // Return your current FormState as a map Gemini can read
    return {
      'visible_fields': _formState.toVisibleFieldsList(),
      'next_target': _formState.firstEmptyRequiredField(),
    };
  }

  void sendAudio(Uint8List pcm16khz) {
    if (!_agentSpeaking) {
      _ws?.sink.add(pcm16khz); // raw binary frame
    }
  }

  // Stubs — implement with your audio player and state management
  void _playAudio(Uint8List pcm24khz) { /* play 24kHz PCM */ }
  void _clearAudioQueue() { /* stop playback */ }
  void _onReady(Map<String, dynamic> data) { /* show UI, start mic */ }
  void _onGoAway(int timeLeftMs) { /* show warning */ }
  void _updateTranscript(String speaker, String text) { /* update UI */ }
  void _onError(String code, String message) { /* show error */ }
  void _handleError(Object error) { /* handle WS error */ }
  void _handleDone() { /* WS closed — note submitted or error */ }
  bool _applyToFormState(String section, String field, dynamic value) => true;
  void _clearFromFormState(String section, String field) {}
  Future<bool> _submitToAppBackend() async => true;
}
```
