# SENA Voice Onboarding — Flutter Wiring Handoff

> **Audience:** Flutter team integrating voice onboarding (Gemini Live) into the SENA mobile app.
> **Status:** Backend live on EC2 (`http://<EC2_HOST>:8083`). Local dev: `http://127.0.0.1:8089`.
> **Owner:** AI backend team.

This document is a **wiring checklist**. Read it top-to-bottom; every section is something the app must implement or configure. The canonical contract for FormState/events lives in `flutterhandoffdev.md` — this file is the practical "what wires to what".

---

## 0. Why the app currently shows `Voice unavailable: 404`

The app is hitting a path the backend doesn't expose. Three things to confirm before anything else:

1. **Base URL** — Flutter `AppStrings.aiBaseUrl` (or equivalent) must point to the onboarding service host, not the main SENA REST API.
2. **Path** — `POST /v1/onboarding/session` (no `/api/` prefix).
3. **Service running** — `curl http://<host>/health/live` must return `{"status":"ok"}`.

Once those three pass, the 404 stops and you proceed to WebSocket wiring below.

---

## 1. Environment configuration

Add an `aiBaseUrl` per env. **This is a different host from the main API** (different service, different port).

| Env | Main API | Onboarding (this service) |
|-----|----------|---------------------------|
| Local dev | `http://localhost:3000/api/mobile` | `http://10.0.2.2:8089` (Android emulator) or `http://127.0.0.1:8089` (iOS sim) |
| Staging | `https://staging-api.isena.org/api/mobile` | `https://staging-ai.isena.org` *(TBD — confirm with backend)* |
| Production | `https://api.isena.org/api/mobile` | `https://ai.isena.org` *(TBD — confirm with backend)* |

> **Android emulator note:** `127.0.0.1` inside the emulator is the emulator itself, not the host. Use `10.0.2.2`.

---

## 2. REST: create session

```
POST {aiBaseUrl}/v1/onboarding/session
Content-Type: application/json
```

**Request body** (typed model, NOT raw map):

```json
{
  "participant_id": "uuid-from-app",
  "tenant_id": "org-uuid",
  "step": "personal_information",
  "schema": { /* full StepSchema — see below */ },
  "bootstrap": {
    "mode": "page_handoff",
    "current_page_values": { "basics.full_name": "Jane", "basics.phone": "0412345678" },
    "readonly_paths": ["basics.email"],
    "prior_pages": { "step_0": { "basics.email": "jane@x.com" } },
    "participant_display_name": "Jane"
  }
}
```

**Response (201):**

```json
{
  "session_id": "uuid",
  "ws_url": "ws://<host>:<port>/ws/onboarding/<session_id>",
  "expires_at": "2026-05-18T12:00:00Z",
  "resumption_handle": null
}
```

**Wire `ws_url` exactly** — backend returns the correct host:port for the deployment. Don't reconstruct it on the client.

### `step` allowed values

| step_id | Voice-driven |
|---------|--------------|
| `personal_information` | ✓ |
| `participant_requirements` | ✓ |
| `ndis_plan_details` | ✓ |
| `documents` | ✗ (app handles uploads) |
| `medical_information` | ✓ |
| `consent` | ✗ (app-only) |

### `schema` payload

App must send the full `StepSchema` for the current step. Source these from the backend fixtures or hardcode in Flutter — they're stable per step. Shape:

```json
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
        {"id": "full_name", "type": "text", "label": "Full Name", "required": true},
        {"id": "email", "type": "email", "label": "Email", "required": true},
        {"id": "interpreter_required", "type": "boolean", "label": "Interpreter?", "required": true}
      ]
    },
    {
      "id": "emergency_contacts",
      "label": "Emergency Contacts",
      "item_fields": [
        {"id": "name", "type": "text", "label": "Name", "required": true},
        {"id": "phone", "type": "phone", "label": "Phone", "required": true}
      ],
      "repeatable": {"min": 1, "max": 5}
    }
  ]
}
```

Field types: `text | email | phone | date | enum | multi_enum | boolean | number | textarea`.

---

## 3. WebSocket: connect

```dart
final socket = WebSocket.connect(response.wsUrl);
```

**Subprotocols:** none.
**Binary type:** raw bytes (`Uint8List`) — NOT base64.
**Compression:** none. Disable if your client enables it by default.

After connect, **send a single JSON text frame** to open the Gemini session:

```json
{"type": "start"}
```

Backend responds with a `ready` event when Gemini is connected. **Don't send audio before `ready`.**

---

## 4. Audio formats — strict

| Direction | Format | Sample rate | Channels | Encoding |
|-----------|--------|-------------|----------|----------|
| Client → server (mic) | PCM16 LE raw | **16 kHz** | mono | binary WS frame |
| Server → client (playback) | PCM16 LE raw | **24 kHz** | mono | binary WS frame |

**Chunk size:** ~20–40ms (640–1280 bytes at 16 kHz). Avoid huge chunks (>4 KB) — VAD jitters.

**Resampling:** if recorder gives 48 kHz (most Android devices), downsample to 16 kHz before send. Don't ask Gemini to do it.

### Packages tested in similar Flutter VoIP flows

- `flutter_sound` — gives raw PCM via stream; needs manual resample.
- `record` + `audio_streamer` — streamable raw PCM.
- Native channel — most reliable on Android with old SDKs.

---

## 5. THE echo gate (most critical rule)

**Without this the agent will interrupt itself and the session will die after 2–4 turns.**

```dart
class VoiceController {
  bool _agentSpeaking = false;

  void _onWsEvent(Map<String, dynamic> ev) {
    switch (ev['type']) {
      case 'turn_start':    _agentSpeaking = true;  break;  // mute mic
      case 'turn_complete': _agentSpeaking = false; break;  // unmute mic
      case 'interrupted':   _agentSpeaking = false; break;  // user barged in
    }
  }

  void _onMicChunk(Uint8List pcm16) {
    if (_agentSpeaking) return;                              // GATE
    if (_socket.readyState != WebSocket.open) return;
    _socket.add(pcm16);                                       // binary send
  }
}
```

**Why client-side, not server-side:** the server tried gating; it caused silent VAD lockup after a few turns (model audio for turn N+1 arrives before `turn_complete` of turn N fires, gate stays closed). Backend now forwards mic audio unconditionally and relies on Flutter to mute.

---

## 6. Server → client event protocol

All non-audio frames are JSON text. Switch on `ev.type`:

| Event | Payload | Flutter action |
|-------|---------|----------------|
| `ready` | `{state, prompt_version, coverage}` | Session live. Enable mic stream. |
| `turn_start` | — | `_agentSpeaking = true`. Start playback queue. |
| `turn_complete` | — | `_agentSpeaking = false`. Drain playback queue. |
| `interrupted` | — | `_agentSpeaking = false`. **Clear playback buffer.** |
| `user_said` | `{text}` | Append to transcript. |
| `agent_said` | `{text}` | Append to transcript. |
| `field_updated` | `{section, field, value, repeatable_index?, confidence, source?, auto_copied_from?}` | Patch local FormState. Highlight the field. |
| `state` | full FormState snapshot | Reconcile. |
| `row_added` | `{section_id, new_index}` | Render an empty card at `new_index`. |
| `repeatable_section_entered` | `{section_id, intent, row_index}` | Highlight focused row. |
| `repeatable_section_exited` | `{section_id}` | Release focus. |
| `validation_rejection` | `{section_id, field_id?, code, reason_human, repeatable_index?}` | Inline error display on the field. |
| `field_skipped_warning` | `{section_id, field_id, reason}` | Banner + highlight. |
| `step_completed` | `{webhook_delivered}` | Show success, close session, route to next step. |
| `escalated` | `{reason, transcript_excerpt}` | Calm acknowledgement screen. |
| `schema_drift_detected` | `{...}` | Inline notice, refresh schema from backend. |
| `go_away` | `{time_left_ms}` | Backend is closing in N ms — call resume endpoint. |
| `resumable` | `{handle, ttl_sec}` | Store handle for resume. |
| `error` | `{code, message}` | Show error toast, handle close. |

**Default arm rule:** `default` of the switch MUST log `WARN` with the unknown type. Silent `null` return = bug.

---

## 7. Client → server messages

Text frames (JSON):

| Type | Payload | Use |
|------|---------|-----|
| `start` | — | Open Gemini session (send once on WS open). |
| `user_text` | `{text}` | Typed user input (no voice). |
| `audio_end` | — | Flush VAD buffer (send right after `turn_start` echo gate fires). |
| `screen_state_v2` | `{data: {step_id, focused_section, focused_field, field_status, field_errors, repeatable_rows, ui_flags}}` | Tell the agent what the user is looking at. **Send on every UI focus change.** |

Binary frames: raw PCM16 16 kHz audio (see §4).

---

## 8. `screen_state_v2` — what to populate

The agent uses this to re-ask the right field, give validation hints, and avoid asking about already-filled fields.

```json
{
  "type": "screen_state_v2",
  "data": {
    "step_id": "personal_information",
    "focused_section": "basics",
    "focused_field": "phone",
    "field_status": {
      "basics.full_name": "filled",
      "basics.phone": "invalid",
      "basics.email": "empty"
    },
    "field_errors": {
      "basics.phone": "Must be 10 digits with no spaces"
    },
    "repeatable_rows": {"emergency_contacts": 1},
    "ui_flags": {}
  }
}
```

**Send triggers:**

- On screen mount → initial snapshot
- On focus change → updated `focused_field`
- On client-side validation result → updated `field_status` + `field_errors`
- On adding a repeatable row → updated `repeatable_rows`

**Don't send on every keystroke.** Debounce to focus/blur boundaries.

---

## 9. Multi-page handoff (`bootstrap`)

When the user finishes step N and starts step N+1, pass the values they already entered so the agent doesn't re-ask. This is the `bootstrap` envelope from §2.

```dart
final bootstrap = {
  'mode': 'page_handoff',
  'current_page_values': currentPageFormValues,            // what's pre-filled on THIS page
  'readonly_paths': ['basics.email'],                       // fields the user can't edit here
  'prior_pages': {
    'step_0_invitation': {'basics.email': user.email},
    'step_1_personal':   {'basics.full_name': prev.fullName},
  },
  'participant_display_name': user.firstName,
};
```

`mode` values:
- `new_user` — fresh session, nothing pre-filled
- `returning_same_page` — user came back to the same step (resume)
- `page_handoff` — coming from a previous step

The agent's first utterance acknowledges the participant by name (no re-asking) and verifies any pre-filled values.

---

## 10. Resume protocol (long sessions)

Gemini Live sessions have a hard ~15 min cap. Backend warns the client with `go_away` ~10s before close, then issues a `resumable` event on close.

```dart
String? _resumeHandle;
int? _resumeTtl;

void _onWsEvent(Map<String, dynamic> ev) {
  if (ev['type'] == 'resumable') {
    _resumeHandle = ev['handle'];
    _resumeTtl = ev['ttl_sec'];
  }
}

// To resume:
final wsUrl = '${response.wsUrl}?resume=$_resumeHandle';
final socket = await WebSocket.connect(wsUrl);
```

**Handle is single-use** — once redeemed, it's gone. Store last few transcript turns client-side so the user sees continuity even before the agent re-speaks.

---

## 11. WebSocket close codes

| Code | Meaning | Flutter response |
|------|---------|------------------|
| 1000 | Normal close | Session done, go to success screen |
| 1001 | Going away (server restart) | Reconnect with resume handle |
| 1008 | Policy violation (Gemini key/quota) | **Hard error** — show "voice temporarily unavailable", fall back to typed input |
| 1011 | Internal server error | Retry once, then fall back |
| 4001 | Session not found / expired | Restart from session create |
| 4003 | Tenant mismatch | Hard error — log out and back in |
| 4008 | Schema drift | Re-fetch schema from backend, create new session |
| 4429 | Too many sessions | Show "another device is in your account" |

Always read `event.reason` for human-readable detail.

---

## 12. Permissions

### Android (`android/app/src/main/AndroidManifest.xml`)

```xml
<uses-permission android:name="android.permission.RECORD_AUDIO" />
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.MODIFY_AUDIO_SETTINGS" />
<uses-permission android:name="android.permission.BLUETOOTH" />
<uses-permission android:name="android.permission.BLUETOOTH_CONNECT" />
```

### iOS (`ios/Runner/Info.plist`)

```xml
<key>NSMicrophoneUsageDescription</key>
<string>SENA uses your microphone for voice-based onboarding.</string>
```

### Runtime

Request mic before connecting the WebSocket. If denied, show the typed-input fallback (no voice).

---

## 13. Audio playback (server → client)

Server sends 24 kHz PCM16 chunks as binary frames. Playback must:

1. Queue chunks in arrival order
2. Schedule each buffer to play immediately after the previous one ends (no gaps)
3. On `interrupted` event: **flush the queue immediately** (user barged in; queued audio is now stale)
4. On `turn_complete`: let queue drain naturally

Recommended packages: `just_audio` (with raw PCM buffer source), `flutter_sound` playback mode.

**Don't play through the speaker if mic is hot** — use earpiece or force the user to wear headphones, otherwise echo cancellation will fight with the gate.

---

## 14. Testing checklist (before declaring done)

- [ ] Create session returns 201 with valid `ws_url`
- [ ] WS connect → `ready` event fires within 3s
- [ ] Mic permission prompt shows on first session
- [ ] Speaking "my name is Aditya" triggers `user_said` + `field_updated` for `basics.full_name`
- [ ] Agent's voice plays through speaker/earpiece (not Bluetooth fail)
- [ ] Mid-sentence interrupt: queue clears, agent stops mid-word
- [ ] All 17 server events have a handler (no `default` warnings in logs)
- [ ] Multi-page handoff: step 2 first utterance addresses user by name
- [ ] Close codes 1008/4001/4008 each show the correct user-visible state
- [ ] Background → foreground: session survives (or resumes via handle)
- [ ] Airplane mode mid-session: clean error, not crash

---

## 15. Common pitfalls (read these)

1. **Sending audio before `ready`** — server queues and drops. Always wait.
2. **Base64-encoding audio frames** — server expects raw bytes. Base64 = corrupted audio.
3. **Skipping the echo gate** — agent will VAD-interrupt itself, session dies in 2–4 turns.
4. **Not clearing the playback buffer on `interrupted`** — user hears old agent audio after they barge in.
5. **`Origin` header mismatch** — some packages add weird Origin headers. Backend ignores it but proxies may not.
6. **Hardcoded `ws://localhost:...`** — backend now returns `ws_url` with the actual host. Trust it.
7. **One WebSocket for multiple steps** — wrong. One WS = one step. Close + recreate on advance.
8. **Treating `field_updated` as the source of truth** — it's a delta. Reconcile against `state` events for full snapshot.
9. **Not handling `go_away`** — Gemini drops the session silently; resume handle is your only recovery.
10. **Sending `screen_state_v2` on every keystroke** — flood. Debounce to focus/blur.

---

## 16. Backend contact + escalation

- **Health check:** `GET {aiBaseUrl}/health/live` → must return `{"status":"ok"}`
- **Diag bucket:** `GET {aiBaseUrl}/v1/onboarding/_diag/bucket?tenant_id=X&participant_id=Y` (returns the cross-screen context bucket — useful for "the assistant forgot me" bugs)
- **Backend logs:** structlog JSON. Filter by `session_id` to trace a specific user.
- **Issues tracker:** Use the SENA_AI repo issue tracker; tag `flutter-integration`.

---

## 17. Open questions for backend team

- [ ] Confirm production `aiBaseUrl` (currently TBD)
- [ ] Auth header expected on session create? (currently dev_header mode — needs JWT for prod)
- [ ] Rate limit on session creation per participant?
- [ ] Schema fetch endpoint, or hardcoded in Flutter?

---

*Last updated: 2026-05-18 — when this file changes, re-sync with `flutterhandoffdev.md`.*
