# SENA Onboarding Service — Flutter Integration Guide
## Voice Onboarding via Gemini Live (Phases A – F)

**Service:** Onboarding (port 8083)  
**Implemented & tested:** Phase A (REST), Phase B (WebSocket + Gemini Live), Phase C (Tool events), Phase D (Screen state injection), Phase E (Session resumption + grounding), Phase F (OpenAPI docs + WS protocol doc + Postman collection)  
**Date:** 2026-04-28

---

## What's Built

```
Flutter App                     Onboarding Service (8083)          Gemini Live
    │                                     │                              │
    │── POST /v1/onboarding/session ────► │                              │
    │◄── { session_id, ws_url } ──────── │                              │
    │                                     │                              │
    │── WSS /ws/onboarding/{id} ────────► │── connect ──────────────────►│
    │── {"type":"start"} ───────────────► │                              │
    │◄── {"type":"ready", state:{...}} ── │                              │
    │                                     │                              │
    │── [binary: PCM16 16kHz audio] ────► │── send audio ───────────────►│
    │◄── [binary: PCM16 24kHz audio] ──── │◄── AI speaks ────────────── │
    │◄── {"type":"user_said",...} ─────── │                              │
    │◄── {"type":"agent_said",...} ─────── │                              │
    │── {"type":"screen_state",...} ─────► │── inject text ──────────────►│  ← Phase D
    │◄── {"type":"field_updated",...} ──── │◄── tool: update_field ───── │
    │◄── {"type":"state",...} ──────────── │                              │
    │◄── {"type":"step_completed",...} ─── │◄── tool: advance_step ───── │
    │   [WS closes]                        │── webhook fired ────────────►│app backend
    │◄── {"type":"resumable","handle":"…"} │                              │  ← Phase E
    │   [WS closes on non-terminal exit]   │                              │
    │                                     │                              │
    │  (reconnect with handle)             │                              │
    │── WSS /ws/onboarding/{id}?resume=… ►│                              │  ← Phase E
```

---

## Step 1 — Create a Session (REST)

```
POST http://<host>:8083/v1/onboarding/session
Content-Type: application/json
```

The app sends the form **schema inline** — the service has no pre-stored schemas.

**Request body:**
```json
{
  "participant_id": "any-string-or-uuid",
  "step":           "personal_information",
  "schema":         { ...StepSchema object... },
  "initial_state":  null,
  "locale":         "en-AU",
  "tenant_id":      "your-tenant-id"
}
```

> **Note:** Auth is not enforced in the current MVP. No auth headers required.

**`schema` structure** — the app passes this from its own fixtures. Example minimal schema:
```json
{
  "step_id": "personal_information",
  "title": "Personal Information",
  "sections": [
    {
      "section_id": "basics",
      "title": "Basic Details",
      "fields": [
        { "field_id": "full_name",     "label": "Full Name",     "type": "text",  "required": true },
        { "field_id": "date_of_birth", "label": "Date of Birth", "type": "date",  "required": true },
        { "field_id": "phone",         "label": "Phone",         "type": "phone", "required": true }
      ]
    }
  ]
}
```

**Response `201`:**
```json
{
  "session_id":        "550e8400-e29b-41d4-a716-446655440000",
  "ws_url":            "ws://localhost:8083/ws/onboarding/550e8400-...",
  "expires_at":        "2026-04-28T11:30:00.000Z",
  "resumption_handle": null
}
```

Save `session_id` and `ws_url`.

**Error `404`** — session not found (stale `session_id`):
```json
{ "detail": "Session not found or expired" }
```

---

## Step 2 — Read or Pre-fill State (REST, optional)

### Read current form state

```
GET http://<host>:8083/v1/onboarding/session/{session_id}/state
```

Returns the full `FormState` JSON. Useful to display progress after the voice session ends.

### Write state from app (only when WebSocket is NOT active)

```
PUT http://<host>:8083/v1/onboarding/session/{session_id}/state
Content-Type: application/json
```

```json
{
  "values": {
    "basics": {
      "full_name": "John Smith",
      "phone": "+61 412 345 678"
    }
  }
}
```

> **Important:** This call returns `409 Conflict` if a WebSocket is currently open for this session. The voice connection holds a write lock.

---

## Step 3 — Open the WebSocket

### Fresh connection

Connect to the `ws_url` from Step 1.

```dart
import 'dart:io';

final ws = await WebSocket.connect(
  'ws://<host>:8083/ws/onboarding/$sessionId',
  // No auth headers needed in current MVP
);
```

### Reconnect with a resumption handle (Phase E)

If the previous connection closed mid-session and you received a `resumable` envelope (see Step 7), reconnect using the handle as a query parameter:

```dart
final ws = await WebSocket.connect(
  'ws://<host>:8083/ws/onboarding/$sessionId?resume=$resumptionHandle',
);
```

The server rehydrates the form state and replays the last few transcript turns into Gemini so the conversation continues naturally. The handle is **single-use** — consumed on redeem; a new one is issued if this connection also closes mid-session.

### Reconnect by session ID only (no handle)

If you have the `session_id` but no handle (handle expired, or `resumable` envelope was missed), connect without `?resume`. The server still injects transcript context so the agent continues rather than restarting cold.

```dart
final ws = await WebSocket.connect(
  'ws://<host>:8083/ws/onboarding/$sessionId',
);
```

**WS close codes the server sends before closing:**

| Code | `error.code` | Meaning |
|------|-------------|---------|
| `4004` | `session_not_found` | Session expired or not found |
| `4004` | `schema_not_found` | Schema missing — recreate the session |
| `4008` | `protocol_error` | First message was not `{"type":"start"}` |
| `4009` | `session_locked` | Another WebSocket is already active for this session |
| `4010` | `resume_invalid` | Handle missing, expired, or mapped to a different session_id |

---

## Step 4 — Send the Start Handshake

**The first message sent MUST be `{"type":"start"}`** — before any audio. The server blocks on this.

```dart
ws.add(jsonEncode({'type': 'start'}));
```

The server responds with `{"type":"ready"}` (see Step 5). Only start streaming audio after receiving `ready`.

---

## Step 5 — Receive Events

Listen on the WebSocket before sending audio. The server sends two frame types:

```dart
ws.listen((dynamic frame) {
  if (frame is List<int>) {
    // Binary: AI audio to play — PCM16 24kHz mono
    audioPlayer.queuePcm16(Uint8List.fromList(frame), sampleRate: 24000);
  } else if (frame is String) {
    final event = jsonDecode(frame) as Map<String, dynamic>;
    _handleEvent(event);
  }
});
```

### All server → client JSON events

| `type` | When | Key fields |
|--------|------|-----------|
| `ready` | After `start` handshake — session is live | `state` (full FormState), `prompt_version` |
| `turn_start` | Gemini began speaking | — |
| `turn_complete` | Gemini finished a turn of speech | — |
| `interrupted` | User spoke over the agent | — |
| `user_said` | Transcription of what user said | `text` |
| `agent_said` | Transcription of AI reply | `text` |
| `field_updated` | AI captured a field value | `section`, `field`, `value`, `confidence`, `turn_id`, `repeatable_index` |
| `state` | Full form state after any mutation | `state` (FormState object) |
| `step_completed` | All required fields filled, webhook fired, WS will close | `state`, `webhook_delivered` |
| `escalated` | Safety/abuse flag detected, session continues | `reason`, `transcript_excerpt` |
| `resumable` | WS closing mid-step — store handle for reconnect | `handle`, `ttl_sec` |
| `error` | Any error | `code`, `message` |

**`ready` example:**
```json
{
  "type": "ready",
  "state": {
    "session_id": "uuid",
    "step_id": "personal_information",
    "completed": false,
    "values": { "basics": { "full_name": {"value": null, "source": null} } },
    "completion": { "required_filled": 0, "required_total": 3, "complete": false }
  },
  "prompt_version": "v1"
}
```

**`field_updated` example:**
```json
{
  "type": "field_updated",
  "section": "basics",
  "field": "full_name",
  "value": "John Smith",
  "repeatable_index": null,
  "confidence": 0.95,
  "turn_id": 2
}
```

**`state` example** (always follows `field_updated`):
```json
{
  "type": "state",
  "state": {
    "session_id": "uuid",
    "step_id": "personal_information",
    "completed": false,
    "values": {
      "basics": {
        "full_name":     { "value": "John Smith", "source": "voice", "confidence": 0.95 },
        "date_of_birth": { "value": null,         "source": null },
        "phone":         { "value": null,         "source": null }
      }
    },
    "completion": { "required_filled": 1, "required_total": 3, "complete": false }
  }
}
```

**`step_completed` example** (WS closes after this — do NOT store any `resumable` handle):
```json
{
  "type": "step_completed",
  "state": { ...final FormState... },
  "webhook_delivered": true
}
```

**`escalated` example** (session continues — do NOT close on this):
```json
{
  "type": "escalated",
  "reason": "self_harm",
  "transcript_excerpt": "I don't want to be here anymore"
}
```

**`resumable` example** (store handle immediately — WS is about to close non-terminally):
```json
{
  "type": "resumable",
  "handle": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "ttl_sec": 600
}
```

**`error` codes you may receive mid-session:**

| `code` | Cause | WS stays open? | Action |
|--------|-------|---------------|--------|
| `screen_state_too_large` | `screen_state` payload exceeded 8 KB | Yes | Reduce payload; retry |
| `screen_state_invalid` | `screen_state` failed schema validation | Yes | Fix data shape; retry |
| `internal_error` | Unhandled server exception | No | Show error UI, reconnect |

---

## Step 6 — Stream Audio

After receiving `{"type":"ready"}`, start sending mic audio as binary frames.

```
Format:   PCM16, 16-bit signed little-endian
Rate:     16 000 Hz
Channels: 1 (mono)
Chunk:    ~100ms → 3 200 bytes per frame
```

```dart
micCapture.onChunk = (Uint8List pcm16) {
  ws.add(pcm16);  // send as binary frame
};
micCapture.start(sampleRate: 16000, channels: 1, bitsPerSample: 16);
```

**Audio to play back:** binary frames from server are PCM16 at 24 000 Hz mono — play immediately.

---

## Step 6b — Screen State Injection (Phase D)

Whenever the app navigates to a new screen or a form field changes, send a `screen_state` message over the **same** WebSocket. The agent uses this to skip questions for pre-filled fields and acknowledge what the user can see.

### Message format (client → server)

```dart
ws.add(jsonEncode({
  'type': 'screen_state',
  'data': {
    'current_screen': 'personal_information',                   // optional, ≤64 chars
    'visible_fields': ['full_name', 'date_of_birth', 'phone'], // optional, ≤32 entries
    'prefilled':      {'full_name': 'John Smith'},              // optional — already-filled fields
    'app_context':    'user is on step 1 of 5',                // optional, ≤256 chars
  },
}));
```

**Rules:**
- Send on every screen transition and whenever pre-filled values change.
- Sending the **same payload twice is a no-op** — server deduplicates by content hash. Fire-and-forget; no client-side rate limiting needed.
- Unknown keys in `data` are silently ignored — forward-compatible as the schema evolves.
- Total `data` must be under **8 KB**. Exceeding returns `{"type":"error","code":"screen_state_too_large"}`; message is dropped, WS stays open.

### Pydantic schema (for reference)

| Field | Type | Constraints |
|-------|------|------------|
| `current_screen` | `string \| null` | ≤64 chars |
| `visible_fields` | `list[str] \| null` | ≤32 entries, each ≤64 chars |
| `prefilled` | `dict \| null` | values coerced to string |
| `app_context` | `string \| null` | ≤256 chars |

### What the agent does with it

The backend renders this into a Gemini text turn, e.g.:
```
[SCREEN] section=personal_information; visible=full_name,date_of_birth,phone; prefilled={full_name=John Smith}; note="user is on step 1 of 5".
```
The system prompt instructs the agent: when a `[SCREEN]` line arrives, acknowledge pre-filled fields once and skip asking for them.

---

## Step 7 — End the Session

### Normal end — AI advances step automatically

When all required fields are filled, the AI calls `advance_step` internally. Flutter receives:
```json
{ "type": "step_completed", "state": {...}, "webhook_delivered": true }
```
After the AI finishes its farewell speech, the server closes the WebSocket. **This is a normal close — not an error. No `resumable` handle is issued after `step_completed`.**

### User taps "Stop" — graceful close

```dart
ws.add(jsonEncode({'type': 'stop'}));
// Then close after a brief delay
await ws.close();
```

### Unexpected disconnect / mid-session close (Phase E)

If the WS closes before `step_completed`, the server sends `resumable` immediately before closing:

```json
{ "type": "resumable", "handle": "<uuid>", "ttl_sec": 600 }
```

**Persist this handle in app state.** It expires in `ttl_sec` seconds (default 10 min) and is **single-use**. Use it to reconnect with context (see Step 3). If the user returns after the TTL, reconnect by session ID only — partial transcript context is still injected.

```dart
void _handleEvent(Map<String, dynamic> event) {
  switch (event['type']) {
    case 'resumable':
      // Persist — WS is about to close, step not done
      _resumptionHandle = event['handle'] as String;
      _resumptionHandleExpiry = DateTime.now().add(
        Duration(seconds: event['ttl_sec'] as int),
      );
    case 'step_completed':
      // Terminal — discard any stored handle
      _resumptionHandle = null;
      _resumptionHandleExpiry = null;
      _markStepDone(event);
    // ... other cases
  }
}
```

### App-initiated complete (REST fallback)

If the WS disconnects and you cannot resume, force-complete via REST:

```
POST http://<host>:8083/v1/onboarding/session/{session_id}/complete
```

No body required. Response:
```json
{
  "session_id": "uuid",
  "completed": true,
  "webhook_delivered": true
}
```

---

## Session Resumption — Full Lifecycle (Phase E)

```
1. WS drops / user backgrounds app
2. Server sends {"type":"resumable","handle":"<uuid>","ttl_sec":600} before closing
3. App stores handle + expiry
4. User returns → check: handle present AND not expired?
   YES → connect with ?resume=<handle>
   NO  → connect without ?resume (still gets transcript context)
5. Send {"type":"start"} as normal
6. Receive {"type":"ready"} with current FormState — conversation resumes
7. Server issues NEW resumable handle if this connection also closes mid-step
8. On step_completed → discard stored handle permanently
```

**Handle rules for Flutter:**
- Store as `String?` — null when no active mid-session handle
- Check expiry before using: `DateTime.now().isBefore(expiry)`
- After successful reconnect: clear old handle (server consumed it); await new `resumable` if WS closes again
- Handle close code `4010`: discard stored handle, reconnect without `?resume`
- Never log or display the full handle UUID — treat as an opaque secret

---

## FormState Structure

The `state` object returned in `ready`, `state`, and `step_completed` events:

```json
{
  "session_id":     "uuid",
  "step_id":        "personal_information",
  "participant_id": "string",
  "tenant_id":      "string",
  "locale":         "en-AU",
  "completed":      false,
  "completed_at":   null,
  "started_at":     "2026-04-28T09:00:00Z",
  "updated_at":     "2026-04-28T09:05:00Z",
  "values": {
    "<section_id>": {
      "<field_id>": {
        "value":      "captured value or null",
        "source":     "voice | app | null",
        "confidence": 0.95,
        "turn_id":    2
      }
    }
  },
  "completion": {
    "required_filled": 2,
    "required_total":  3,
    "complete":        false,
    "optional_filled": 0,
    "optional_total":  2
  },
  "escalations": []
}
```

Use `completion.required_filled / completion.required_total` to drive a progress bar.

---

## Quick Reference — Complete Flow

```
1. POST /v1/onboarding/session             → get session_id + ws_url
2. WebSocket.connect(ws_url[?resume=…])    → connection open
3. send {"type":"start"}                   → mandatory handshake
4. receive {"type":"ready","state":{}}     → session live
5. stream binary PCM16 16kHz audio         → AI responds with audio + events
6. send {"type":"screen_state","data":{}}  → on each screen/field change (Phase D)
7. receive field_updated + state           → update form UI in real time
8. receive step_completed                  → webhook fired, WS will close
   OR: WS drops → receive resumable → store handle → reconnect (Phase E)
9. WS closes (normal)
10. GET /session/{id}/state (optional)     → read final state
```

---

## API Docs & References (Phase F)

All documentation endpoints are unconditionally exposed:

| URL | Contents |
|-----|----------|
| `http://<host>:8083/docs` | Swagger UI — browse + test all REST endpoints |
| `http://<host>:8083/redoc` | ReDoc — clean REST reference |
| `http://<host>:8083/openapi.json` | Machine-readable OpenAPI 3.1 schema |

Full WebSocket protocol (every message type, every close code, sequence diagrams):
→ `sena-ai/services/onboarding/docs/WS_PROTOCOL.md`

Postman collection (import and run against localhost):
→ `sena-ai/services/onboarding/docs/postman_collection.json`  
Variables: `{{base_url}}` = `http://localhost:8083`, `{{tenant_id}}`, `{{participant_id}}`

---

## Flutter Implementation Checklist

### Core voice session (Phases A–C)
- [ ] `permission_handler` — request mic before calling `POST /session`
- [ ] `record` or `flutter_sound` — capture PCM16 16kHz mono
- [ ] `dart:io WebSocket` — connect, no auth headers needed
- [ ] Send `{"type":"start"}` as first message
- [ ] Wait for `{"type":"ready"}` before streaming audio
- [ ] Send binary PCM16 chunks (~3200 bytes / 100ms)
- [ ] Play binary responses at 24kHz via speaker
- [ ] Show `user_said` / `agent_said` as transcript bubbles
- [ ] Update form fields on every `field_updated` event
- [ ] Drive progress bar from `state.completion`
- [ ] On `step_completed`: mark step done, don't treat WS close as error
- [ ] On `escalated`: surface alert UI, keep session open
- [ ] Handle close codes 4004 / 4008 / 4009 with user-visible errors

### Screen state injection (Phase D)
- [ ] Send `{"type":"screen_state","data":{...}}` on every screen transition
- [ ] Send updated `screen_state` whenever pre-filled values change
- [ ] Include `prefilled` map for any fields the app already has values for
- [ ] Handle `screen_state_too_large` and `screen_state_invalid` errors (log + continue; WS stays open)

### Session resumption (Phase E)
- [ ] On `resumable`: persist `handle` + compute expiry from `ttl_sec`
- [ ] On `step_completed`: clear stored handle (terminal — no resume needed)
- [ ] On reconnect: check handle present + not expired → connect with `?resume=<handle>`
- [ ] If handle expired or absent: connect without `?resume` (partial context still injected)
- [ ] Handle close code `4010`: discard stale handle, reconnect without it
- [ ] Never log or display the full handle value
