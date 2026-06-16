# SENA AI — Full API Endpoint Reference

## Base URLs

### Local Development

| Service | Port | URL |
|---------|------|-----|
| Voice | 8082 | `http://localhost:8082` |
| Onboarding | 8083 | `http://localhost:8083` |
| Case Review + Restrictive Practices | 8084 | `http://localhost:8084` |

### Localtunnel (Flutter integration)

| Service | URL |
|---------|-----|
| Voice | `https://bosc-sena-voice.loca.lt` |
| Onboarding | `https://bosc-sena-onboarding.loca.lt` |
| Case Review + Restrictive Practices | `https://bosc-sena-case-review.loca.lt` |

---

## Auth Headers (all services)

```
X-Tenant-Id:  <uuid>
X-User-Id:    <uuid>
X-User-Roles: worker,staff      # or: manager, admin, support_worker
```

Basic auth (RP evaluate only): `Authorization: Basic <base64(user:pass)>`

---

## Case Review Service — port 8084

### Health

| Method | Path | Auth | Response |
|--------|------|------|----------|
| GET | `/health/live` | None | `{"status": "ok", "version": "..."}` |
| GET | `/health/ready` | None | `{"status": "ok", "version": "..."}` |

---

### Case Review AI

| Method | Path | Auth | Body | Description |
|--------|------|------|------|-------------|
| POST | `/v1/case-review/context` | SENA headers | `{"case_note_id": "", "client_id": "", "tenant_id": ""}` | Fetch last N case notes + rolling summary |
| POST | `/v1/case-review/classify` | SENA headers | `{"text": "", "session_id": ""}` | Paragraph → structured fields + re-ask prompts |
| POST | `/v1/case-review/review` | SENA headers | `{"session_id": ""}` | Risk / anomaly flags *(Phase D — returns 501)* |
| POST | `/v1/case-review/incident/detect` | SENA headers | `{"session_id": ""}` | Is this a reportable incident? *(Phase E — returns 501)* |
| POST | `/v1/case-review/incident/draft` | SENA headers | `{"session_id": ""}` | Autofill incident form from case note *(Phase E — returns 501)* |
| PATCH | `/v1/case-review/incident/{incident_id}/confirm` | SENA headers | `{"confirmed_fields": {}}` | Staff confirms AI-autofilled draft *(Phase E — returns 501)* |
| POST | `/v1/case-review/submit` | SENA headers | `{"session_id": ""}` | Final submit gate *(Phase F — returns 501)* |

---

### Case Review Voice (Gemini Live)

| Method | Path | Auth | Body | Description |
|--------|------|------|------|-------------|
| POST | `/v1/case-review/voice/session` | SENA headers (staff only) | `{"client_id": "", "worker_id": "", "case_note_id": "", "initial_values": {}, "readonly_paths": []}` | Create voice session → returns `session_id` + `ws_url`. Status 201. |
| POST | `/v1/case-review/voice/draft` | SENA headers (staff only) | `{"transcript": "", "worker_id": "", "client_id": "", "case_note_id": ""}` | Transcript → pre-filled case note fields via Bedrock Claude |
| WS | `/ws/case-review/voice/{session_id}` | SENA headers | — | Gemini Live WebSocket bridge for voice case note dictation |

**WebSocket protocol:**
1. Client sends first frame: `{"type": "hello"}`
2. Server responds: `{"type": "ready", "state": {...}, "prompt_version": "v2", "coverage": {...}}`
3. Stream audio in both directions
4. Server emits events: `turn_start`, `turn_complete`, `interrupted`, `user_said`, `agent_said`, `field_updated`, `state`, `step_completed`, `error`

---

### Restrictive Practices

| Method | Path | Auth | Body | Description |
|--------|------|------|------|-------------|
| POST | `/v1/restrictive-practices/evaluate` | Basic auth | `{"case_note_id": "", "client_id": "", "worker_id": "", "note_text": ""}` | Full RP detection pipeline — triage → evaluator → cross-check → verdict |
| POST | `/v1/restrictive-practices/bsp` | SENA headers | `{"client_id": "", "practice_type": "", "status": "Active", "approved_dosage": "", "approved_conditions": "", "authorised_by": "", "valid_from": "", "valid_until": ""}` | Register a new Behaviour Support Plan. Status 201. |
| GET | `/v1/restrictive-practices/bsp/{client_id}` | SENA headers | — | List all BSPs for a client, newest first |
| PATCH | `/v1/restrictive-practices/bsp/{bsp_id}/status` | SENA headers | `{"status": "Active"}` | Update BSP status. Values: `Active`, `Expired`, `Revoked` |
| POST | `/v1/restrictive-practices/draft` | None | `{"transcript": "", "worker_id": "", "client_id": "", "case_note_id": "", "shift_date": "", "shift_time": "", "worker_position": ""}` | Transcript (text) → structured case note draft. JSON body. |
| POST | `/v1/restrictive-practices/draft/audio` | None | `multipart/form-data` (see below) | Audio file → Amazon Transcribe → structured case note draft |
| POST | `/v1/restrictive-practices/voice/session` | SENA headers (staff only) | `{"client_id": "", "worker_id": "", "case_note_id": "", "initial_values": {}, "readonly_paths": [], "worker_display_name": ""}` | Create RP voice session → returns `session_id` + `ws_url`. Status 201. |
| WS | `/v1/restrictive-practices/voice/ws/{session_id}` | SENA headers | — | Gemini Live WebSocket bridge for RP voice case note |
| GET | `/v1/restrictive-practices/health` | None | — | `{"status": "ok", "service": "restrictive-practice-detection"}` |

#### POST `/v1/restrictive-practices/draft/audio` — multipart fields

> ⚠️ This is `multipart/form-data` — NOT JSON. Use `MultipartRequest` in Flutter, not `http.post`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `audio` | File | Yes | Audio recording — mp3, mp4/m4a, wav, flac, ogg, webm |
| `worker_id` | String | Yes | Worker identifier |
| `client_id` | String | Yes | Client identifier |
| `case_note_id` | String | No | Auto-generated UUID if blank |
| `shift_date` | String | No | e.g. `2026-06-15` |
| `shift_time` | String | No | e.g. `14:30` |
| `worker_position` | String | No | e.g. `Support Worker` |

Requires `SENA_AI_TRANSCRIPTION_BUCKET` env var set — returns 503 if missing.

---

### Demo UIs (browser only)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/demo` | Voice dictation demo HTML |
| GET | `/draft-demo` | Draft extraction test UI |

---

## Voice Service — port 8082

### Health

| Method | Path | Auth | Response |
|--------|------|------|----------|
| GET | `/health/live` | None | `{"status": "ok", "service": "voice", "version": "..."}` |
| GET | `/health/ready` | None | `{"status": "ok", "checks": {...}}` — pings DB, Redis, Bedrock, SNS |

---

### Case Note Dictation — Flow B (Bedrock + LiveKit)

| Method | Path | Auth | Body | Description |
|--------|------|------|------|-------------|
| POST | `/v1/voice/session` | SENA headers (worker/manager/admin) | `{"participant_id": "", "shift_id": ""}` | Start dictation session. Returns LiveKit token. Status 201. |
| POST | `/v1/voice/session/turn` | SENA headers | `{"session_id": "", "transcript": ""}` | Process a voice turn — transcript → Bedrock → draft update |
| POST | `/v1/voice/session/end` | SENA headers | `{"session_id": ""}` | Compile case note, create approval item, publish SNS event |
| GET | `/v1/voice/session/{session_id}` | SENA headers | — | Session status, turn count, completeness score, missing topics |

---

### Personal Details Voice (Gemini Live)

| Method | Path | Auth | Body | Description |
|--------|------|------|------|-------------|
| POST | `/v1/voice/personal-details/session` | SENA headers | `{"participant_id": ""}` | Start personal-details voice session. Status 201. |
| POST | `/v1/voice/personal-details/session/turn` | SENA headers | `{"session_id": "", "transcript": ""}` | Process turn via Gemini |
| POST | `/v1/voice/personal-details/session/end` | SENA headers | `{"session_id": ""}` | End session — returns extracted fields + draft_id |

---

### Approval

| Method | Path | Auth | Body | Description |
|--------|------|------|------|-------------|
| POST | `/v1/approval/decision` | SENA headers (manager/admin only) | `{"session_id": "", "decision": "approve", "comment": ""}` | Approve or reject case note draft |

---

## Onboarding Service — port 8083

### Health

| Method | Path | Auth | Response |
|--------|------|------|----------|
| GET | `/health/live` | None | `{"status": "ok"}` |
| GET | `/health/ready` | None | `{"status": "ok"}` — pings Redis; 503 if unavailable |

---

### Session Lifecycle

| Method | Path | Auth | Body | Description |
|--------|------|------|------|-------------|
| POST | `/v1/onboarding/session` | SENA headers | `{"participant_id": "", "step": "", "schema": {...}}` | Create session with schema inline. Returns `session_id` + `ws_url` + `expires_at`. Status 201. |
| GET | `/v1/onboarding/session/{session_id}/state` | SENA headers | — | Read current FormState |
| PUT | `/v1/onboarding/session/{session_id}/state` | SENA headers | `{"values": {}}` | Write FormState — returns 409 if WebSocket is active |
| POST | `/v1/onboarding/session/{session_id}/complete` | SENA headers | — | Finalize session, write cross-screen bucket, fire outbound webhook |
| POST | `/v1/onboarding/session/{session_id}/errors` | SENA headers | `{"input_method": "voice", "ts": ""}` | Report client-side validation error (telemetry). Returns 204. |

---

### Voice

| Method | Path | Auth | Query | Description |
|--------|------|------|-------|-------------|
| WS | `/ws/onboarding/{session_id}` | SENA headers | `?resume=<handle>` (optional) | Gemini Live voice onboarding. Pass `resume` handle to resume a dropped session. |

**WebSocket protocol:**
1. Client sends first frame: `{"type": "hello"}` or `{"type": "start"}`
2. Server responds: `{"type": "ready", "state": {...}, "prompt_version": "...", "coverage": {...}}`
3. Stream audio in both directions
4. On session approaching timeout server sends: `{"type": "go_away", "time_left_ms": 30000}`
5. On close server sends: `{"type": "resumable", "handle": "...", "ttl_sec": 600}` — use handle in `?resume=` to reconnect

---

### Dev Only

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/v1/onboarding/_diag/bucket` | SENA headers | Inspect cross-screen context bucket for a (tenant_id, participant_id) pair. Returns 404 in production. |

---

## Common Error Responses

| Status | Meaning |
|--------|---------|
| 400 | Bad request — invalid header or unsupported audio format |
| 401 | Unauthorized — missing or wrong Basic auth credentials |
| 403 | Forbidden — role not permitted for this endpoint |
| 404 | Not found — session expired or does not exist |
| 405 | Method not allowed — wrong HTTP verb |
| 409 | Conflict — WebSocket lock active, PUT blocked |
| 422 | Validation error — missing required field or wrong type |
| 501 | Not implemented — endpoint stubbed, phase not yet shipped |
| 503 | Service unavailable — required env var not configured |
| 504 | Gateway timeout — transcription timed out, retry |
