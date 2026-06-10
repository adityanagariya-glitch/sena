# Flutter Handoff — Voice Case-Note Dictation (case_review)

**Backend:** `services/case_review` · ports 8084 · branch `ai-services`
**Engine:** shared `sena_common.voice` (Gemini Live) — the **same engine** as onboarding voice, reused. If you've wired the onboarding voice client, this is the same protocol with a different schema + endpoints.
**Frontend target:** `lib/features/case_notes/staff/` (the existing 7-section case-note form).

> **Read §6 (Mistakes we will NOT repeat) FIRST.** Three of those bugs cost us days during client/staff onboarding. They are 100% avoidable on the client side and the backend cannot fix them for you.

---

## 0. The mental model (READ THIS — it's different from a "transcribe" API)

This is **NOT** "record audio → server returns text". It is a **live, mobile-proxy voice agent**:

- The worker speaks; Gemini Live drives a conversation and **calls tools** (`update_field`, `finalize_note`, …).
- **Your Flutter app is the source of truth for the form.** When Gemini wants to set a field, the server sends you a `tool_request`; **you apply it to your own form state and send back a `tool_response` containing the FRESH full form state.** The server stores only ephemeral session scaffolding in Redis — your `CaseNoteFormController` remains authoritative.
- The agent **never auto-submits.** It calls `finalize_note` only after the worker confirms; you still run your normal `submit()` (including the ≥1-document gate).

This "the client applies the change and echoes state back" design is called the **Option-D state channel**. It is the single most important thing to get right (see §6.1).

---

## 1. Integration flow

```
Worker taps "Dictate" on the case-note form
        │
        ▼
POST /v1/case-review/voice/session   (headers: X-Tenant-Id, X-User-Id, X-User-Roles; body: {client_id, shift_id})
        │  → { session_id, ws_url }
        ▼
WSS  /ws/case-review/voice/{session_id}   (headers: X-Tenant-Id, X-User-Id, X-User-Roles, X-Participant-Id=client_id)
        │
        ├─ send {"type":"hello"}                        → recv {"type":"ready", state, coverage}
        ├─ stream PCM16 16 kHz mic audio (binary)        → recv PCM16 24 kHz agent audio (binary) → play
        ├─ recv {"type":"turn_start"}  → MUTE MIC + start playback
        ├─ recv {"type":"turn_complete"/"interrupted"} → UNMUTE MIC + (clear queue on interrupted)
        ├─ recv {"type":"tool_request", request_id, tool, args}
        │         → apply to CaseNoteFormController → send {"type":"tool_response", request_id, result:{ok, state}}
        ├─ recv {"type":"user_said"/"agent_said", text} → show live transcript (optional)
        └─ on worker "done": agent calls finalize_note → you validate → return {ok} or {ok:false, blockers}
                              → on ok, run your normal submit() (incl. document gate)
```

---

## 2. Session create (REST)

```
POST {AppStrings.apiBaseUrl}/v1/case-review/voice/session
Headers (dev_header auth — same as your other case_review calls):
  X-Tenant-Id:   <org/tenant uuid>
  X-User-Id:     <support worker uuid>
  X-User-Roles:  worker          # MUST contain a staff role (worker/staff/support_worker/admin) or you get 403
Content-Type: application/json

Body:
{ "client_id": "<participant/client id>", "shift_id": "<shift id>" }

201 →
{ "session_id": "ab12…", "ws_url": "/ws/case-review/voice/ab12…" }
```

- **Staff-only.** A non-staff role → `403 {"detail":{"code":"not_staff"}}`.
- `client_id` becomes the session's `participant_id` — you must send it back as `X-Participant-Id` on the WS (below).
- The session holds ephemeral Redis state, TTL `SENA_AI_VOICE_SESSION_MAX_SEC` (default 3600 s).

---

## 3. WebSocket connect

Open `wss://<host>{ws_url}` and send these **headers on the upgrade** (the WS authenticates from headers, not a query token):

| Header | Value | Required |
|--------|-------|----------|
| `X-Tenant-Id` | same tenant as session create | **YES** — missing → close `4401` |
| `X-User-Roles` | must include a staff role | **YES** — non-staff → close `4403` |
| `X-Participant-Id` | the `client_id` used at session create | strongly recommended — used for the ownership check |
| `X-User-Id` | worker uuid | optional |

> Flutter `web_socket_channel` / `IOWebSocketChannel.connect(url, headers: {...})` supports custom headers on mobile. If your WS lib can't set headers on web, tell us — we'll add a query-param fallback. **Tenant isolation depends on `X-Tenant-Id` matching the session's tenant** — a wrong/absent tenant means the session is simply not found (`4004`).

### Handshake
Immediately after connect, send one text frame:
```json
{"type":"hello"}
```
Server replies:
```json
{"type":"ready","state":{…},"prompt_version":"v2","coverage":["summary.summaryOfShift", …]}
```
`coverage` = every voice-eligible `section.field` path. Start the mic only after `ready`.

---

## 4. Audio (binary frames)

| Direction | Format |
|-----------|--------|
| Mic → server | **PCM16, 16 kHz, mono, little-endian**. ~100 ms chunks (3200 bytes). Send as **binary** WS frames. |
| Server → speaker | **PCM16, 24 kHz, mono**. Binary frames — enqueue + play. |

Optional control frames (text):
- `{"type":"audio_end"}` — when the worker lifts a push-to-talk button (flushes Gemini's VAD buffer). Optional in always-on mic mode.
- `{"type":"user_text","text":"…"}` — typed-input fallback (no audio).
- `{"type":"stop"}` — worker ends the session (graceful close).

---

## 5. WebSocket events — full contract

### 5.1 Server → Client

| `type` | Payload | Flutter action |
|--------|---------|----------------|
| `ready` | `{state, coverage, prompt_version}` | session live — start mic |
| *(binary)* | PCM16 24 kHz | enqueue + play agent audio |
| `turn_start` | — | **set `_agentSpeaking=true` (MUTE MIC)**; start playback |
| `turn_complete` | — | **set `_agentSpeaking=false` (UNMUTE MIC)** |
| `interrupted` | — | **set `_agentSpeaking=false`**; **clear the audio playback queue** |
| `user_said` | `{text}` | append to live transcript (optional UI) |
| `agent_said` | `{text}` | append to live transcript (optional UI) |
| `tool_request` | `{request_id, tool, args}` | **apply to form + reply with `tool_response` (see §5.3)** — the core loop |
| `go_away` | `{time_left_ms}` | Gemini ~15-min limit approaching; warn the worker to wrap up |
| `error` | `{code, message}` | show/log; handle close codes (§7) |
| `screen_state_ack` | debug-only | ignore unless debugging |

### 5.2 Client → Server

| `type` | Payload | When |
|--------|---------|------|
| `hello` | — | once, right after connect |
| *(binary)* | PCM16 16 kHz | continuous while mic open |
| `tool_response` | `{request_id, result}` | **reply to every `tool_request`** (§5.3) |
| `user_text` | `{text}` | typed fallback |
| `audio_end` | — | push-to-talk release (optional) |
| `screen_state_v2` | `{data:{…}}` | optional — when visible fields change (e.g. `anyInjuries` toggles). Must be ≤ 8192 bytes. |
| `stop` | — | worker taps "End" |

> **Parse EVERY `type`.** Your `switch`/`default` arm must **log a warning**, never silently drop an unknown event. (Onboarding shipped a silent `null` default and we lost a day to "the agent isn't responding" — it was an unhandled event. See §6.3.)

### 5.3 The tool loop — `tool_request` → `tool_response` (THE CORE)

When Gemini decides to write a field, the server sends:
```json
{"type":"tool_request","request_id":"f3a1…","tool":"update_field",
 "args":{"section":"wellbeingAndBehaviour","field":"mood","value":"Settled and calm"}}
```
You **apply it to `CaseNoteFormController`** (set `moodCtl.text = "Settled and calm"`), then **reply with the FRESH full form state**:
```json
{"type":"tool_response","request_id":"f3a1…",
 "result":{"ok":true,"state":{ …see §5.4… }}}
```
On rejection (e.g. your own validator fails): `{"result":{"ok":false,"reason":"Mood must be at least 5 characters."}}` — the agent reads the reason aloud.

The four tools you will receive (`coverage`/decls):

| tool | args | what you do | result |
|------|------|-------------|--------|
| `update_field` | `{section, field, value}` | set the matching controller/Rx value (§8 map). Booleans arrive as the **string** `"true"`/`"false"`. | `{ok:true, state}` or `{ok:false, reason}` |
| `clear_field` | `{section, field}` | clear that field | `{ok:true, state}` |
| `get_current_state` | `{}` | no mutation | `{ok:true, state}` |
| `finalize_note` | `{confirmation_transcript}` | the worker confirmed they're done — run your `submit()` validation (all required + **≥1 document**) | `{ok:true}` on success, else `{ok:false, blockers:[{path,label,reason}]}` (see §6.4) |

### 5.4 The `state` object you echo back (Option-D — get this RIGHT)

Every `tool_response.result.state` (and the `get_current_state` reply) must be the **current full form state** in this shape:
```json
{
  "step": {"id":"staff_case_note","label":"Case Note","number":1},
  "bootstrap_mode": "new_user",
  "participant": {"first_name":"","display_name":""},
  "visible_fields": [
    {"path":"summary.summaryOfShift","label":"Summary of Shift","type":"textarea","required":true,"readonly":false,"value":"Morning shift…"},
    {"path":"wellbeingAndBehaviour.mood","label":"Mood","type":"text","required":true,"readonly":false,"value":null},
    {"path":"safetyAndHealth.anyInjuries","label":"Any Injuries?","type":"boolean","required":true,"readonly":false,"value":false}
    // …one entry per CURRENTLY VISIBLE field. value=null when empty.
  ],
  "next_target": {"path":"wellbeingAndBehaviour.mood","label":"Mood","reason":"next_required"},
  "prior_steps": {}
}
```
- `visible_fields[].value` is how the agent knows what's already filled — **it will re-ask or hallucinate if you don't keep this fresh.**
- `next_target` = the first empty required field (or `null` when everything required is filled). Drives what the agent asks next.
- Only include `injuryDetails` in `visible_fields` when `anyInjuries == true` (it's `visible_if`).

> If echoing the full `state` per turn is heavy, you can ship a minimal first cut returning `{ok:true}` with no `state` — the agent will still work but will rely on `get_current_state` round-trips and may re-ask. **Strongly recommend shipping the `state` channel from day one** — it's the difference between a smooth agent and a forgetful one (onboarding lesson §6.1).

---

## 6. 🔴 Mistakes we will NOT repeat (from client/staff onboarding)

### 6.1 Always echo fresh `state` in `tool_response` (the #1 onboarding bug)
Onboarding initially returned `{ok:true}` with no `state`. Result: the agent had no idea which fields were filled, re-asked answered questions, and "hallucinated" values. **Fix:** every `tool_response` carries the full current `state` (§5.4). Treat the agent as stateless between turns — your app is the memory.

### 6.2 MUTE the mic while the agent is speaking (echo / VAD death)
If the phone speaker audio is picked up by the mic, Gemini's voice-activity-detection hears itself, "interrupts," and **silently wedges after 2–4 turns** (issues-solved 0001). **Fix on the client:**
```dart
// _agentSpeaking flips on the WS events, NOT in the recorder.
ws turn_start    → _agentSpeaking = true;
ws turn_complete → _agentSpeaking = false;
ws interrupted   → _agentSpeaking = false; clearAudioQueue();
// gate in the mic stream listener:
micStream.listen((chunk) { if (!_agentSpeaking) ws.sendBinary(chunk); });
```
- Mute in the **stream listener**, not by stopping the recorder (stopping/restarting the recorder drops frames + adds latency).
- **Do NOT** ask the backend to gate audio — the server forwards mic audio unconditionally on purpose (server-side gating is what caused the original VAD death). The echo fix lives **only** on the client.
- UX: prompt the worker to use **headphones/earbuds**; without them, echo is much worse.

### 6.3 Handle EVERY event type; never silently drop
Onboarding's `VoiceEventModel.parse` had a `default → return null` that swallowed unknown events → "the agent froze" debugging rabbit holes. **Fix:** `default` arm logs a WARN with the raw type. If you see a warning for a `type` not in §5.1, tell us — it means the contract drifted.

### 6.4 Voice CANNOT satisfy the document-upload gate — surface it
The screen requires **≥1 attached document** (`uploadedDocuments.isEmpty` blocks submit). The voice agent cannot upload a file. The agent is prompted to remind the worker, but **your `finalize_note` handler must enforce it**: if no document is attached, return `{ok:false, blockers:[{"path":"safetyAndHealth.reportMedia","label":"Document","reason":"Attach at least one document before submitting."}]}` so the agent tells the worker to attach one on screen. Do not let voice "complete" a note that the form would reject.

### 6.5 Don't auto-submit; reuse your existing `submit()`
`finalize_note` is a *request to submit*, gated by the worker's spoken confirmation. On `ok:true` from your handler, run the **same `CaseNoteFormController.submit()`** you already have (which builds `CreateCaseNotePayload`, hits the document gate, and routes to the incident form if `anyIncident`). The voice flow must not bypass any existing validation or the incident-report redirect.

### 6.6 Wrong source-of-truth on manual edits
If the worker types into a field while the agent is running, **your typed value wins**. Because you own the state and echo it back (§5.4), this happens naturally — just make sure the `state` you send reflects the controller's *current* text, not a stale copy.

---

## 7. WebSocket close codes

| Code | Meaning | Action |
|------|---------|--------|
| `1000` | normal close (worker ended / session done) | show complete state |
| `1011` | server error | retry once; then surface error |
| `4401` | missing `X-Tenant-Id` | fix headers; re-create session |
| `4403` | not staff / not session owner | the worker's role/tenant doesn't match — do not retry blindly |
| `4004` | session not found/expired (or wrong tenant) | re-create the session |
| `4008` | bad handshake (first frame not `hello`/`start`) | send `{"type":"hello"}` first |
| `4009` | another WS already open for this session | close the other one; retry |

---

## 8. Field map — `tool_request` (section.field) → your `CaseNoteFormController`

Field ids are the **exact backend keys** = your Flutter controllers, so mapping is 1:1. All text fields **required, 5–1000 chars** (mood + injuryDetails **5–500**). Booleans arrive as the string `"true"`/`"false"`.

| section.field | Controller / Rx | Type |
|---------------|-----------------|------|
| `summary.summaryOfShift` | `summaryCtl` | text 5–1000 |
| `activitiesAndSkill.assisted` | `assistedCtl` | text 5–1000 |
| `activitiesAndSkill.practisedSkill` | `practisedSkillCtl` | text 5–1000 |
| `activitiesAndSkill.participantsLevelOfIndependence` | `independenceCtl` | text 5–1000 |
| `activitiesAndSkill.observation` | `observationCtl` | text 5–1000 |
| `wellbeingAndBehaviour.mood` | `moodCtl` | text **5–500** |
| `wellbeingAndBehaviour.behaviouralEvents` | `behaviouralEventsCtl` | text 5–1000 |
| `wellbeingAndBehaviour.anyConcerns` | `anyConcerns` (Rx bool) | boolean |
| `outcomesAndProgress.whatWentWell` | `whatWentWellCtl` | text 5–1000 |
| `outcomesAndProgress.furtherSupport` | `furtherSupportCtl` | text 5–1000 |
| `outcomesAndProgress.participantsComments` | `participantsCommentsCtl` | text 5–1000 |
| `safetyAndHealth.medicationReminderGiven` | `medicationReminderGiven` (Rx bool) | boolean |
| `safetyAndHealth.safetyHazardObserved` | `safetyHazardObserved` (Rx bool) | boolean |
| `safetyAndHealth.anyInjuries` | `anyInjuries` (Rx bool) | boolean |
| `safetyAndHealth.injuryDetails` | `injuryDetailsCtl` | text **5–500**, only when `anyInjuries=true` |
| `feedback.careFeedback` | `careFeedbackCtl` | text 5–1000 |
| `feedback.anyIncident` | `anyIncident` (Rx bool) | boolean |
| `handover.handover` | `handoverNoteCtl` | text 5–1000 |
| `safetyAndHealth.reportMedia` | `uploadedDocuments` | **NOT voice-fillable** — file upload only (§6.4) |

When `value` is `"true"`/`"false"` for a boolean field, set the matching `RxBool`. When the agent sets `anyInjuries=true`, your UI should reveal `injuryDetails` and you should start including it in `visible_fields`.

---

## 9. Recommended Flutter wiring (where this lives)

- New: `lib/features/case_notes/staff/presentation/voice/` — a `CaseNoteVoiceController` (WS + audio + the tool loop) that holds a reference to the existing `CaseNoteFormController` and mutates it on `tool_request`.
- Reuse the existing form's controllers/validators verbatim — the voice controller just drives them.
- Entry point: a "Dictate" button on `case_note_form_screen.dart`. The `case_notes_hub` can deep-link into the form with voice pre-armed if you want.
- On WS close / worker stop: leave the form populated; the worker reviews and presses the existing Submit.

---

## 10. Not done yet (backend residuals — won't block client wiring against a dev server)

1. **Gemini data residency** (`australia-southeast1`) is not yet pinned — fine for synthetic/test data; **must** land before real participant audio (NDIS APP 8/11).
2. **WS auth headers**: full tenant enforcement assumes you send `X-Tenant-Id`/`X-Participant-Id`. Confirm your WS lib can set upgrade headers on every platform you target; if web can't, we add a query-param fallback.
3. `finalize_note` → app-backend submission: currently your client assembles `CreateCaseNotePayload` and calls your existing create/update usecase (the backend voice flow writes nothing itself). No new submit endpoint — reuse what you have.

---

## 11. Quick reference — env (server, for your local dev server)

| Var | Default |
|-----|---------|
| `SENA_AI_GEMINI_API_KEY` | (required) |
| `SENA_AI_GEMINI_LIVE_MODEL_ID` | `gemini-3.1-flash-live-preview` |
| `SENA_AI_CASE_REVIEW_REDIS_URL` | `redis://localhost:6380/0` (dedicated case_review Redis) |
| `SENA_AI_VOICE_SESSION_MAX_SEC` | `3600` |
| `SENA_AI_VOICE_SILENCE_TIMEOUT_SEC` | `8` |
| `SENA_AI_SCREEN_STATE_MAX_BYTES` | `8192` |

Questions → ping the AI/ML backend team. The protocol is identical to onboarding voice; if you've integrated that, this is the same client with the §8 schema swapped in.
