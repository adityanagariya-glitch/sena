# Flutter Voice Integration — Case Note Voice Assistant

**Last updated: 2026-05-21**  
**Backend branch: `onboarding_casenote`**

This document is the complete contract between the Flutter app and the case-note voice assistant API. Give it to the mobile developer as the single source of truth.

---

## Overview

The voice assistant fills every case-note field in real time via a two-phase flow:

1. **Drafting phase** — worker records or types a shift summary. The server transcribes and extracts fields into a pre-filled draft. Handled by REST (no WebSocket).
2. **Assistant phase** — the pre-filled values seed the voice session. The assistant only asks about the fields that are still empty.

**The assistant never auto-submits.** When all fields are filled and the worker says "finish", the server emits `session_complete`. The worker reviews the form and presses the Submit button to call `POST /evaluate`.

---

## 1. Recommended Integration Flow

```
Worker records shift summary
        │
        ▼
POST /draft/audio  ── (audio blob, multipart)
   or POST /draft  ── (text transcript, JSON)
        │
        ▼
CaseDraftResponse  ──  map flat fields → initial_values sections
        │
        ▼
POST /voice/session  ──  {initial_values, readonly_paths}
        │
        ▼
WSS /voice/ws/{session_id}?token=…
        │
        ├─ stream PCM16 mic audio (binary frames)
        ├─ receive field_updated events → update form live
        ├─ receive agent audio (binary frames) → play back
        └─ receive session_complete → show Submit button
```

---

## 2. Phase 1 — Draft from Recording

### Option A — Audio file (recommended, higher quality)

Amazon Transcribe (en-AU) transcribes the audio, then Claude extracts the form fields.

```
POST /v1/restrictive-practices/draft/audio
Content-Type: multipart/form-data
Authorization: Basic <base64(user:pass)>   # only if SENA_AI_BASIC_AUTH_USER is set

audio:            <audio file>      # mp3, mp4/m4a, wav, flac, ogg, webm — required
worker_id:        w-123             # form field, required
client_id:        liam-001          # form field, required
case_note_id:     <uuid>            # form field, optional — auto-generated if blank
shift_date:       2026-05-21        # form field, optional
shift_time:       07:00-15:00       # form field, optional
worker_position:  Support Worker    # form field, optional
```

Returns: `CaseDraftResponse` (see §2.3).

Requires `SENA_AI_TRANSCRIPTION_BUCKET` to be set on the server. Returns `503` if not configured — handle gracefully by falling back to Option B.

Custom NDIS vocabulary is supported via `SENA_AI_TRANSCRIPTION_VOCAB_NAME`. Improves recognition of NDIS-specific terms.

### Option B — Text transcript

Worker types or dictates; app sends the raw text directly.

```
POST /v1/restrictive-practices/draft
Content-Type: application/json
Authorization: Basic <base64(user:pass)>   # only if SENA_AI_BASIC_AUTH_USER is set

{
  "transcript":      "Liam was in good spirits today. We worked on...",
  "worker_id":       "w-123",
  "client_id":       "liam-001",
  "case_note_id":    "<uuid>",       // optional — auto-generated if blank
  "shift_date":      "2026-05-21",   // optional
  "shift_time":      "07:00-15:00",  // optional
  "worker_position": "Support Worker" // optional
}
```

Returns: `CaseDraftResponse` (see §2.3).

### 2.3 `CaseDraftResponse` shape

```json
{
  "case_note_id":   "<uuid>",
  "client_id":      "liam-001",
  "worker_id":      "w-123",
  "shift_date":     "2026-05-21",
  "shift_time":     "07:00-15:00",
  "worker_position":"Support Worker",

  "describe":       "Morning shift at Liam's house...",

  "assisted":                          "personal care, breakfast",
  "practised_skill":                   "making toast independently",
  "participants_level_of_independence":"moderate prompting required",
  "observations":                      null,

  "mood":             "settled and happy",
  "behavioural_events": null,
  "any_concerns":     false,

  "what_went_well":             "Liam was cooperative and engaged.",
  "what_needs_further_support": null,
  "participant_comments":       null,

  "medication_reminders_given": true,
  "safety_hazards_observed":    false,
  "any_injuries":               false,
  "injury_description":         null,
  "uploaded_documents":         null,

  "carer_feedback":   null,
  "incident_occurred": false,

  "transcript": "<original transcript echoed back>",

  "draft_note":         "Observations and carer feedback are missing from the transcript.",
  "note_quality_score": 0.62,
  "note_quality_label": "Average",
  "quality_gaps":       ["Add observations from the shift", "Include carer feedback"]
}
```

`draft_note` — show this as a hint to the worker if non-null. It describes what the AI could not extract.  
`note_quality_label` — `"Premium"` / `"Average"` / `"Poor"`.  
`quality_gaps` — actionable suggestions to improve the note.

### 2.4 Mapping `CaseDraftResponse` → `initial_values`

The draft response is flat. The voice session expects values nested by section. Use this mapping:

| `CaseDraftResponse` field | `initial_values` section | `initial_values` field |
|--------------------------|--------------------------|------------------------|
| `shift_date` | `shift` | `shift_date` |
| `shift_time` | `shift` | `shift_time` |
| `worker_position` | `shift` | `worker_position` |
| `describe` | `summary` | `describe` |
| `assisted` | `activities` | `assisted` |
| `practised_skill` | `activities` | `practised_skill` |
| `participants_level_of_independence` | `activities` | `participants_level_of_independence` |
| `observations` | `activities` | `observations` |
| `mood` | `wellbeing` | `mood` |
| `behavioural_events` | `wellbeing` | `behavioural_events` |
| `any_concerns` | `wellbeing` | `any_concerns` |
| `what_went_well` | `outcomes` | `what_went_well` |
| `what_needs_further_support` | `outcomes` | `what_needs_further_support` |
| `participant_comments` | `outcomes` | `participant_comments` |
| `medication_reminders_given` | `safety` | `medication_reminders_given` |
| `safety_hazards_observed` | `safety` | `safety_hazards_observed` |
| `any_injuries` | `safety` | `any_injuries` |
| `injury_description` | `safety` | `injury_description` |
| `carer_feedback` | `incidents` | `carer_feedback` |
| `incident_occurred` | `incidents` | `incident_occurred` |

Include only non-null fields in `initial_values`. Null fields stay absent so the assistant knows to ask about them.

---

## 3. Phase 2 — Voice Assistant Session

### 3.1 Create Session

```
POST /v1/restrictive-practices/voice/session
Content-Type: application/json
Authorization: Basic <base64(user:pass)>   # only if SENA_AI_BASIC_AUTH_USER is set

{
  "case_note_id":       "<uuid>",
  "worker_id":          "w-123",
  "client_id":          "liam-001",
  "tenant_id":          "t-1",              // optional
  "worker_display_name":"Sarah",            // optional — used in the assistant greeting
  "initial_values": {                       // pre-filled fields from /draft response
    "shift": {
      "shift_date":      "2026-05-21",
      "shift_time":      "07:00-15:00",
      "worker_position": "Support Worker"
    },
    "summary": {
      "describe": "Morning shift at Liam's house..."
    },
    "activities": {
      "assisted": "personal care, breakfast"
    }
    // ... any other non-null fields from CaseDraftResponse
  },
  "readonly_paths": [                       // agent may READ but never overwrite these
    "shift.case_note_id",
    "shift.worker_id",
    "shift.client_id"
  ]
}
```

Response:

```json
{
  "session_id": "<uuid>",
  "ws_url":     "wss://host/v1/restrictive-practices/voice/ws/<uuid>?token=<opaque>",
  "expires_at": "2026-05-21T18:00:00Z"
}
```

### 3.2 Connect WebSocket

Open `ws_url` verbatim — the session token is already embedded in the query param. Accept both binary and text frames.

### 3.3 Stream Audio

Send raw PCM16 as **binary frames**:

| Property | Value |
|----------|-------|
| Sample rate | **16 kHz** |
| Channels | 1 (mono) |
| Bit depth | 16-bit, little-endian, signed |
| Recommended chunk | 100 ms = 1600 samples = 3200 bytes |

Receive agent audio back as **binary frames**:

| Property | Value |
|----------|-------|
| Sample rate | **24 kHz** |
| Channels | 1 (mono) |

**DO NOT gate the mic on agent speech.** Send audio unconditionally while the mic is open. The server uses `START_OF_ACTIVITY_INTERRUPTS` — gating breaks multi-turn VAD. See §6.

### 3.4 Session End

Receive `session_complete` → apply `payload` to the form → show the Submit button. The WS closes after a short delay. Do NOT auto-call `/evaluate`.

---

## 4. WebSocket Events

### 4.1 Server → Client (text frames, JSON)

| Event type | When | Key payload fields |
|-----------|------|--------------------|
| `turn_start` | Agent starts speaking | — |
| `turn_complete` | Agent finishes speaking | — |
| `interrupted` | Worker spoke over agent | — |
| `user_said` | Worker speech transcribed | `text` |
| `agent_said` | Agent speech transcribed | `text` |
| `field_updated` | Field value captured | see §4.3 |
| `state` | Completion stats refreshed | `completion` |
| `validation_rejection` | Server rejected a field value | `section_id`, `field_id`, `code`, `reason_human` |
| `session_complete` | All fields filled + worker confirmed | see §4.4 |
| `escalated` | Safety incident escalation logged | `reason`, `transcript_excerpt`, `session_id` |
| `go_away` | Gemini 15-min limit approaching | `time_left_ms` |
| `error` | Server-side error | `code`, `message` |
| `screen_state_ack` | Debug echo (only when `SENA_AI_DEBUG=true`) | `accepted`, `version` |

### 4.2 Client → Server (text frames, JSON)

| Message type | When to send | Required fields |
|-------------|-------------|-----------------|
| `screen_state_v2` | On screen mount, focus change, `any_injuries` toggle | see §5 |
| `user_text` | Text-input fallback | `text` |
| `audio_end` | Worker lifts finger from mic button (optional) | — |
| `validation_failed` | App-side validator rejects a field | `section_id`, `field_id`, `reason_human`, `code` |
| `validation_cleared` | App-side validation error is resolved | `section_id`, `field_id` |
| `stop` | Worker taps End Session | — |

### 4.3 `field_updated` payload

```json
{
  "type":               "field_updated",
  "section_id":         "wellbeing",
  "field_id":           "mood",
  "value":              "settled",
  "confidence":         0.95,
  "pending_confirmation": false
}
```

`value` is `null` when a field is cleared.  
Boolean fields arrive as `true` / `false`.  
When `pending_confirmation: true`, the agent is reading the value back for confirmation. Render the field as "pending" (e.g. amber highlight) until confirmation arrives.

### 4.4 `session_complete` payload

```json
{
  "type":         "session_complete",
  "session_id":   "<uuid>",
  "case_note_id": "<uuid>",
  "payload": {
    "case_note_id":   "<uuid>",
    "client_id":      "liam-001",
    "worker_id":      "w-123",
    "shift_date":     "2026-05-21",
    "shift_time":     "07:00-15:00",
    "worker_position":"Support Worker",
    "describe":       "Morning shift at Liam's house...",
    "assisted":       "personal care, breakfast",
    "practised_skill":"making toast independently",
    "participants_level_of_independence": "moderate prompting",
    "observations":   "Liam was focused and calm throughout.",
    "mood":           "settled",
    "behavioural_events": "No incidents.",
    "any_concerns":   false,
    "what_went_well": "Liam engaged well.",
    "what_needs_further_support": "Continue breakfast routine practice.",
    "participant_comments": "He said he was happy.",
    "medication_reminders_given": true,
    "safety_hazards_observed":    false,
    "any_injuries":               false,
    "injury_description":         null,
    "uploaded_documents":         null,
    "carer_feedback":   "Handover was smooth.",
    "incident_occurred": false
  },
  "completion": {
    "required_total":  19,
    "required_filled": 19,
    "optional_total":  1,
    "optional_filled": 0
  }
}
```

Apply all non-null values in `payload` to your local form state before showing the Submit button. The payload is flat — field IDs match `CaseDraftResponse` 1:1 so you can reuse the same form model.

**Merge rule**: if the worker typed a value manually into a form field while the assistant was running, your local value wins over the voice payload.

---

## 5. `screen_state_v2` Contract

Send this event:
- When the voice WS opens (immediately on `ws.onopen`)
- Whenever the visible set of fields changes — particularly when `any_injuries` toggles (shows/hides `injury_description`)
- Whenever the worker manually types into a field (so the assistant knows it is already filled)

```json
{
  "type": "screen_state_v2",
  "data": {
    "step_id": "case_note",
    "fields": [
      {"section_id": "shift",    "field_id": "shift_date",          "status": "filled"},
      {"section_id": "shift",    "field_id": "shift_time",          "status": "empty"},
      {"section_id": "safety",   "field_id": "any_injuries",        "status": "filled"},
      {"section_id": "safety",   "field_id": "injury_description",  "status": "empty"}
    ],
    "field_errors": {}
  }
}
```

`status` values:
- `"filled"` — field has a value; the assistant will not re-ask it
- `"empty"` — field is visible and empty; the assistant may ask

Fields **absent** from the list are treated as not visible — the assistant ignores them entirely. Always send all currently rendered fields.

---

## 6. Audio Rules (Critical)

1. **Never gate mic on agent speech.** Do NOT stop sending audio while the agent is speaking. Multi-turn VAD breaks silently after turn 2–4 if you do. Let the server's `START_OF_ACTIVITY_INTERRUPTS` handle barge-in.
2. **Stream continuously.** Send audio frames from the moment the WS opens until the user taps End Session.
3. **Use headphones (UX note to worker).** Without headphones, the agent's output is picked up by the mic and confuses VAD. Add a pre-session hint in the app UI.
4. **Binary and text frames interleave freely.** Send `screen_state_v2` while audio is streaming — no special ordering needed.
5. **`interrupted` event** — when received, immediately clear any queued agent audio in your playback buffer and stop playback. The agent has been interrupted and will start listening again.

---

## 7. WebSocket Close Codes

| Code | Meaning | Recommended action |
|------|---------|--------------------|
| `1000` | Normal close — session finished | Show "Session complete" state |
| `1006` | Abnormal close (network drop / server crash) | Retry connect with same `ws_url` if session has not expired |
| `4004` | Session not found (expired or invalid `session_id`) | Return to session creation; session cannot be recovered |
| `4009` | Another WebSocket is already open for this session | Wait and retry; or surface error to user |
| `4011` | Invalid or expired session token | Re-create the session (POST `/voice/session` again) |

---

## 8. Field Sections Reference

All fields are required by the assistant unless marked otherwise. The assistant accepts "N/A" or "none" as a valid answer for fields that do not apply to the shift — it will not push back.

| Section ID | Field ID | Type | Required | Notes |
|-----------|----------|------|----------|-------|
| `shift` | `shift_date` | date text | **Yes** | |
| `shift` | `shift_time` | text | **Yes** | e.g. "07:00–15:00" |
| `shift` | `worker_position` | text | **Yes** | e.g. "Support Worker" |
| `summary` | `describe` | textarea | **Yes** | Overall shift narrative |
| `activities` | `assisted` | textarea | **Yes** | What the worker helped with |
| `activities` | `practised_skill` | textarea | **Yes** | Skill-building activities; "N/A" accepted |
| `activities` | `participants_level_of_independence` | text | **Yes** | "N/A" accepted |
| `activities` | `observations` | textarea | **Yes** | Behavioural / engagement notes |
| `wellbeing` | `mood` | textarea | **Yes** | e.g. "settled and happy" |
| `wellbeing` | `behavioural_events` | textarea | **Yes** | "None" accepted if no events |
| `wellbeing` | `any_concerns` | boolean | **Yes** | `true` / `false` |
| `outcomes` | `what_went_well` | textarea | **Yes** | |
| `outcomes` | `what_needs_further_support` | textarea | **Yes** | "N/A" accepted |
| `outcomes` | `participant_comments` | textarea | **Yes** | Direct quotes or "None provided" |
| `safety` | `medication_reminders_given` | boolean | **Yes** | `true` / `false` |
| `safety` | `safety_hazards_observed` | boolean/text | **Yes** | `true` / `false` |
| `safety` | `any_injuries` | boolean | **Yes** | `true` / `false`; triggers `injury_description` |
| `safety` | `injury_description` | textarea | **Conditional** | Required only when `any_injuries = true`; hidden otherwise (`visible_if`) |
| `safety` | `uploaded_documents` | text | Optional | File references; voice cannot fill this |
| `incidents` | `carer_feedback` | textarea | **Yes** | Handover notes; "None" accepted |
| `incidents` | `incident_occurred` | boolean | **Yes** | `true` / `false` |

### `visible_if` rule for `injury_description`

The `injury_description` field is **only rendered** when `any_injuries = true`. When the worker answers `any_injuries = false`, hide the field. When it becomes visible, send `screen_state_v2` so the server re-evaluates completion.

---

## 9. Security

- The session token lives in the WS query param (`?token=…`). It is a single-use opaque UUID. Do not log or cache it.
- **Production upgrade**: switch the token to `Sec-WebSocket-Protocol` subprotocol header to prevent URL logging by reverse proxies.
- Sessions expire after `SENA_AI_VOICE_SESSION_MAX_SEC` seconds (default: 3600). After expiry the WS closes with code `4004`.
- Session state is scoped per `(session_id, worker_id)` — the server rejects cross-owner access at every operation.

---

## 10. Environment Variables (server-side reference)

| Variable | Default | Notes |
|----------|---------|-------|
| `SENA_AI_GEMINI_API_KEY` | `""` | **Required** for voice assistant |
| `SENA_AI_GEMINI_LIVE_MODEL_ID` | `gemini-3.1-flash-live-preview` | Do not change without testing |
| `SENA_AI_REDIS_URL` | `redis://localhost:6379/0` | Session state store |
| `SENA_AI_VOICE_SESSION_MAX_SEC` | `3600` | Session TTL (seconds) |
| `SENA_AI_VOICE_SILENCE_TIMEOUT_SEC` | `8` | Silence watchdog; `0` to disable |
| `SENA_AI_TRANSCRIPTION_BUCKET` | `""` | **Required** for `/draft/audio` (Amazon Transcribe). Returns 503 if blank. |
| `SENA_AI_TRANSCRIPTION_LANGUAGE` | `en-AU` | Amazon Transcribe language code |
| `SENA_AI_TRANSCRIPTION_VOCAB_NAME` | `""` | Custom Transcribe vocabulary for NDIS terms |
| `SENA_AI_BASIC_AUTH_USER` | `""` | HTTP Basic auth username for all endpoints |
| `SENA_AI_BASIC_AUTH_PASSWORD` | `""` | HTTP Basic auth password |
