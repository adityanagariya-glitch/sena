# SENA Onboarding Service — Flutter Integration Guide
## Voice Onboarding via Gemini Live (Phases A + B + C)

**Service:** Onboarding (port 8083)  
**Implemented & tested:** Phase A–F + v2 alignment (2026-04-29)  
**v2 key changes:** `screen_state_v2`, `field_apply` envelope, `add_repeatable_row` tool, `voice_coverage` enforcement, `about_me` field (was `bio`), `prompt_version:"v2"`, `coverage` array in ready message.

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
    │◄── {"type":"field_updated",...} ──── │◄── tool: update_field ───── │
    │◄── {"type":"state",...} ──────────── │                              │
    │◄── {"type":"step_completed",...} ─── │◄── tool: advance_step ───── │
    │   [WS closes]                        │── webhook fired ────────────►│app backend
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
  "session_id":       "550e8400-e29b-41d4-a716-446655440000",
  "ws_url":           "ws://localhost:8083/ws/onboarding/550e8400-...",
  "expires_at":       "2026-04-27T11:30:00.000Z",
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

Connect to the `ws_url` from Step 1.

```dart
import 'dart:io';

final ws = await WebSocket.connect(
  'ws://<host>:8083/ws/onboarding/$sessionId',
  // No auth headers needed in current MVP
);
```

**WS close codes the server sends before closing:**

| Code | `error.code` | Meaning |
|------|-------------|---------|
| `4004` | `session_not_found` | Session expired or not found |
| `4004` | `schema_not_found` | Schema missing — recreate the session |
| `4008` | `protocol_error` | First message was not `{"type":"start"}` |
| `4009` | `session_locked` | Another WebSocket is already active for this session |

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

**`step_completed` example** (WS closes after this):
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

## Step 7 — End the Session

### Normal end — AI advances step automatically

When all required fields are filled, the AI calls `advance_step` internally. Flutter receives:
```json
{ "type": "step_completed", "state": {...}, "webhook_delivered": true }
```
After the AI finishes its farewell speech, the server closes the WebSocket. **This is a normal close — not an error.**

### User taps "Stop" — graceful close

```dart
ws.add(jsonEncode({'type': 'stop'}));
// Then close after a brief delay
await ws.close();
```

### App-initiated complete (REST fallback)

If the WS disconnects unexpectedly, force-complete via REST:

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

## FormState Structure

The `state` object returned in `ready`, `state`, and `step_completed` events:

```json
{
  "session_id":   "uuid",
  "step_id":      "personal_information",
  "participant_id": "string",
  "tenant_id":    "string",
  "locale":       "en-AU",
  "completed":    false,
  "completed_at": null,
  "started_at":   "2026-04-27T09:00:00Z",
  "updated_at":   "2026-04-27T09:05:00Z",
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
1. POST /v1/onboarding/session        → get session_id + ws_url
2. WebSocket.connect(ws_url)          → connection open
3. send {"type":"start"}              → mandatory handshake
4. receive {"type":"ready","state":{}} → session live
5. stream binary PCM16 16kHz audio    → AI responds with audio + events
6. receive field_updated + state      → update form UI in real time
7. receive step_completed             → webhook fired, WS will close
8. WS closes (normal)
9. GET /session/{id}/state (optional) → read final state
```

---

## Flutter Implementation Checklist

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
