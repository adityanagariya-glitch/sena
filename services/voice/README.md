# Voice Service

> FastAPI service for real-time voice-driven workflows on the Sena platform. Provides two voice modes: (1) **Case note dictation** — a support worker dictates their shift notes post-shift via REST + LiveKit audio, with Claude Sonnet drafting structured sections turn-by-turn; (2) **Personal details collection** — a Gemini Live WebSocket session collects participant onboarding data via natural voice conversation. Includes an approval queue and SNS event publishing.

---

## Table of Contents
- [Overview](#overview)
- [How It Works](#how-it-works)
- [Tech Stack](#tech-stack)
- [API Reference](#api-reference)
- [Environment Variables](#environment-variables)
- [Running the Service](#running-the-service)
- [Integration Guide](#integration-guide)
- [QA & Testing](#qa--testing)
- [Implementation Status](#implementation-status)
- [Integration Requirements](#integration-requirements)

---

## Overview

Two distinct voice workflows are supported:

**Case Note Dictation (REST + LiveKit):**
- Worker starts a voice session
- Worker speaks their shift notes via LiveKit
- Frontend transcribes audio and sends text turns to this service
- Service builds a structured case note draft section-by-section using Claude Sonnet
- Worker ends session; service generates a final case note draft
- Draft enters an approval queue — a coordinator approves or rejects
- On approval, SNS event fires to downstream systems

**Personal Details Collection (WebSocket + Gemini Live):**
- Participant opens a voice session
- Service connects to Gemini Live API via WebSocket
- Bidirectional audio streaming: participant speaks, Gemini responds
- Service extracts personal detail fields from conversation
- Returns structured field data on session end

---

## How It Works

### Case Note Dictation Flow

```
POST /v1/voice/session  { objective: "CASE_NOTE", ... }
  ├─ Validate auth (JWT or dev_header)
  ├─ Check Redis: no active session for this participant
  ├─ Create VoiceSession in AI DB
  ├─ Generate LiveKit access token
  └─ Return: session_id + LiveKit room credentials

[Frontend connects to LiveKit room, streams audio]
[Frontend transcribes audio locally or via LiveKit STT]

POST /v1/voice/session/turn  { session_id, transcript, confidence, sequence_number }
  ├─ Call Bedrock Claude Sonnet with transcript + draft context
  ├─ Update case note draft sections
  └─ Return: agent_reply + draft_preview + completeness_score + missing_topics

POST /v1/voice/session/end  { session_id, ended_at }
  ├─ Finalise draft
  ├─ Create ApprovalQueueItem in Shared DB
  └─ Return: draft_id + approval_item_id

POST /v1/voice/approval  { approval_item_id, decision: "APPROVED", reviewer_id }
  ├─ Update approval item
  ├─ On APPROVED: persist to shared case note table
  └─ Publish SNS event: case note delivered
```

### Personal Details (WebSocket) Flow

```
POST /v1/voice/personal-details/session  →  session_id + LiveKit token

WSS /ws/personal-details/{session_id}
  ├─ Client streams PCM16 audio (16 kHz)
  ├─ Service bridges to Gemini Live (bidirectional)
  ├─ Gemini asks questions, extracts field values
  ├─ Service streams PCM16 responses back (24 kHz)
  └─ Emits JSON events: fields_update, complete, error
```

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| API Framework | FastAPI + Uvicorn (port 8082) |
| Case Note AI | AWS Bedrock — Claude Sonnet (`anthropic.claude-3-5-sonnet-20240620-v1:0`) |
| Personal Details AI | Google Gemini 2.5 Flash Live (`gemini-2.5-flash-native-audio-latest`) |
| Real-time Audio | LiveKit (WebRTC infrastructure) |
| Primary DB | PostgreSQL async (AI DB — sessions, turns, drafts) |
| Shared DB | PostgreSQL async (Shared DB — approval queue, case notes) |
| Session Cache | Redis (rate limiting, participant locks, session state) |
| Events | AWS SNS (case note delivery notifications) |
| Auth | JWT (production) or dev_header (development) |
| Port | 8082 |

---

## API Reference

### Case Note Dictation

#### `POST /v1/voice/session`
Start a case note dictation session.

**Request Body**
```json
{
  "objective": "CASE_NOTE",
  "participant_id": "part_abc123",
  "staff_id": "staff_xyz",
  "shift_id": "shift_789",
  "language": "en-AU",
  "metadata": {}
}
```

**Response**
```json
{
  "session_id": "sess_001",
  "status": "ACTIVE",
  "objective": "CASE_NOTE",
  "lock_acquired": true,
  "livekit": {
    "room_name": "voice_sess_001",
    "token": "eyJhbGci...",
    "url": "wss://livekit.example.com"
  }
}
```

| Field | Notes |
|-------|-------|
| `lock_acquired` | `false` if another active session exists for this participant — do not proceed |
| `livekit.token` | Use this to connect to the LiveKit room for audio capture |

---

#### `POST /v1/voice/session/turn`
Submit one transcribed turn.

**Request Body**
```json
{
  "session_id": "sess_001",
  "transcript": "I helped the client with their morning routine. They were calm and cooperative.",
  "transcript_confidence": 0.94,
  "audio_duration_ms": 4200,
  "sequence_number": 1,
  "timestamp": "2026-06-01T08:05:00Z"
}
```

**Response**
```json
{
  "session_id": "sess_001",
  "sequence_number": 1,
  "agent_reply": "Great, I've noted the morning routine. Can you tell me about any incidents or risks during the shift?",
  "draft_preview": {
    "participant_state": "Calm and cooperative during morning routine.",
    "support_actions": "Assisted with morning routine."
  },
  "completeness_score": 0.28,
  "missing_topics": ["incidents_risks", "medications_health", "outcomes_followup", "handover_notes"],
  "model": "claude-3-5-sonnet",
  "latency_ms": 1840
}
```

**Case note sections tracked:**

| Section | Description |
|---------|-------------|
| `participant_state` | Client's mood, behaviour, presentation |
| `support_actions` | What the worker did |
| `incidents_risks` | Any incidents or risks observed |
| `medications_health` | Medication administration or health concerns |
| `outcomes_followup` | Outcomes achieved; follow-up needed |
| `handover_notes` | Information for the next shift worker |

---

#### `POST /v1/voice/session/end`
End the session and create the draft for approval.

**Request Body**
```json
{
  "session_id": "sess_001",
  "ended_at": "2026-06-01T08:20:00Z",
  "client_timezone": "Australia/Sydney"
}
```

**Response**
```json
{
  "session_id": "sess_001",
  "draft_id": "draft_abc",
  "approval_item_id": "appr_xyz",
  "event_id": "evt_001",
  "status": "PENDING_APPROVAL",
  "case_note": { ... }
}
```

---

#### `POST /v1/voice/approval`
Approve or reject a case note draft.

**Request Body**
```json
{
  "approval_item_id": "appr_xyz",
  "decision": "APPROVED",
  "reviewer_id": "coordinator_001",
  "review_notes": "Looks complete and accurate."
}
```

**Response**
```json
{
  "approval_item_id": "appr_xyz",
  "decision": "APPROVED",
  "status": "DELIVERED",
  "shared_case_note_id": "cn_shared_001",
  "delivered_at": "2026-06-01T08:25:00Z"
}
```

---

#### `GET /v1/voice/session/{session_id}`
Get current session status and draft completeness.

---

### Personal Details (WebSocket)

#### `POST /v1/voice/personal-details/session`
Start a personal details collection session.

Same request/response shape as case note session but `objective: "PERSONAL_DETAILS"`.

#### `POST /v1/voice/personal-details/turn`
Submit a transcribed turn (REST fallback for non-WebSocket clients).

#### `POST /v1/voice/personal-details/end`
End session and return collected fields.

---

#### `WSS /ws/personal-details/{session_id}`

**Auth:** JWT token via `Authorization` header or `?token=<jwt>` query param.

**Client → Server**

| Frame | Description |
|-------|-------------|
| Binary PCM16 16kHz mono | Continuous audio |
| JSON `{"type":"end_session"}` | Graceful close |

**Server → Client**

| Frame | Description |
|-------|-------------|
| Binary PCM16 24kHz mono | Gemini voice response |
| JSON `{"type":"fields_update","fields":{...}}` | Updated field values |
| JSON `{"type":"complete","fields":{...}}` | All fields collected |
| JSON `{"type":"error","message":"..."}` | Error |

---

### Health Checks

#### `GET /health/live`
```json
{ "status": "alive", "service": "sena-voice", "version": "0.1.0" }
```

#### `GET /health/ready`
Checks all components. Returns `200` if all healthy, `503` if any degraded.
```json
{
  "status": "healthy",
  "checks": {
    "ai_database": "ok",
    "shared_database": "ok",
    "redis": "ok",
    "bedrock": "ok",
    "sns": "ok"
  }
}
```

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SENA_AI_AI_DB_URL` | Yes | — | PostgreSQL async URL for AI DB (voice sessions, turns, drafts) |
| `SENA_AI_SHARED_DB_URL` | Yes | — | PostgreSQL async URL for Shared DB (approval queue) |
| `SENA_AI_REDIS_URL` | Yes | — | Redis URL |
| `SENA_AI_LIVEKIT_API_KEY` | Yes | — | LiveKit API key |
| `SENA_AI_LIVEKIT_API_SECRET` | Yes | — | LiveKit API secret |
| `SENA_AI_LIVEKIT_URL` | Yes | — | LiveKit server URL (e.g. `wss://livekit.yourdomain.com`) |
| `SENA_AI_SNS_CASE_NOTE_TOPIC_ARN` | Yes | — | AWS SNS topic ARN for case note delivery events |
| `SENA_AI_GEMINI_API_KEY` | Yes | — | Google Gemini API key |
| `SENA_AI_AUTH_MODE` | No | `dev_header` | `"jwt"` (production) or `"dev_header"` (development) |
| `SENA_AI_JWT_ISSUER` | If `auth_mode=jwt` | — | JWT issuer |
| `SENA_AI_JWT_AUDIENCE` | If `auth_mode=jwt` | — | JWT audience |
| `SENA_AI_JWT_PUBLIC_KEY_PEM` | If `auth_mode=jwt` | — | Public key for JWT signature verification |
| `SENA_AI_AWS_REGION` | No | `ap-southeast-2` | AWS region |
| `SENA_AI_BEDROCK_MODEL_ID` | No | `anthropic.claude-3-5-sonnet-20240620-v1:0` | Bedrock model (⚠ outdated — update before production) |
| `SENA_AI_GEMINI_LIVE_MODEL_ID` | No | `gemini-2.5-flash-native-audio-latest` | Gemini Live model |
| `SENA_AI_PORT` | No | `8082` | Service port |
| `SENA_AI_REDIS_LOCK_TTL_SECONDS` | No | `3600` | Participant lock TTL |
| `SENA_AI_RATE_LIMIT_START_PER_MINUTE` | No | `30` | Session start rate limit |
| `SENA_AI_RATE_LIMIT_TURN_PER_MINUTE` | No | `120` | Turn processing rate limit |

**AWS IAM permissions required:**
```json
{
  "Effect": "Allow",
  "Action": [
    "bedrock:InvokeModel",
    "bedrock:InvokeModelWithResponseStream",
    "sns:Publish"
  ],
  "Resource": "*"
}
```

---

## Running the Service

**Install dependencies**
```bash
cd voice
pip install -e .
```

**Start databases (local dev):**
```bash
docker run -p 5432:5432 -e POSTGRES_PASSWORD=dev ankane/pgvector
docker run -p 6379:6379 redis:7
```

**Run database migrations** (ensure ORM models are applied):
```bash
# No migration tool configured — tables are created on startup via SQLAlchemy create_all
```

**Run service:**
```bash
uvicorn voice.main:app --reload --host 0.0.0.0 --port 8082
```

**Auth mode (dev):**
Set `SENA_AI_AUTH_MODE=dev_header` and pass headers:
```
X-Tenant-ID: org_xyz
X-User-ID: user_001
X-User-Role: support_worker
X-Staff-ID: staff_xyz
```

**Health check:** http://localhost:8082/health/ready

---

## Integration Guide

### For Backend Teams

**Case note dictation flow:**
```
1. Worker starts shift on the app
2. At shift end, worker opens "Record Case Note" in the app
3. App calls POST /v1/voice/session → receives LiveKit credentials
4. App connects to LiveKit room, records audio
5. App transcribes audio (can use LiveKit STT or client-side)
6. For each transcribed segment, App calls POST /v1/voice/session/turn
7. App shows agent reply + draft preview to worker
8. When completeness_score ≈ 1.0 or worker signals done:
   App calls POST /v1/voice/session/end
9. Coordinator reviews draft via POST /v1/voice/approval
10. On APPROVED: SNS event fires, case note is delivered
```

**Participant lock:** Only one active session per `participant_id`. If `lock_acquired: false`, inform the worker another session is active (or wait for it to expire).

**Approval queue:** Backend can list pending approval items directly from its Shared DB (this service writes to it). Alternatively, build a polling endpoint or push-based notification.

### For Frontend Teams

**Case note dictation:**
- Use LiveKit SDK to connect to the returned room
- Stream audio to LiveKit; transcribe locally or via LiveKit's transcription service
- Send each transcribed segment to `/v1/voice/session/turn`
- Display `agent_reply` as the AI assistant's response
- Show a progress indicator using `completeness_score` (0.0 → 1.0)
- Show `missing_topics` as a checklist of remaining sections
- When all sections are complete or worker taps "Done", call `/v1/voice/session/end`

**Personal details (WebSocket):**
```javascript
const ws = new WebSocket(`wss://voice-service/ws/personal-details/${sessionId}`, [], {
  headers: { 'Authorization': `Bearer ${token}` }
});

ws.binaryType = 'arraybuffer';

// Send PCM16 16kHz audio
ws.send(audioChunk);  // ArrayBuffer of PCM16 16kHz mono

ws.onmessage = (event) => {
  if (event.data instanceof ArrayBuffer) {
    // PCM16 24kHz — play immediately
    playAudio(event.data);
  } else {
    const msg = JSON.parse(event.data);
    if (msg.type === 'fields_update') updateFormUI(msg.fields);
    if (msg.type === 'complete') finaliseForm(msg.fields);
  }
};
```

---

### Pre-Integration Checklist

- [ ] **Two PostgreSQL databases** created and accessible (AI DB + Shared DB)
- [ ] Redis running and accessible
- [ ] LiveKit server deployed and `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `LIVEKIT_URL` set
- [ ] AWS SNS topic created and `SNS_CASE_NOTE_TOPIC_ARN` set
- [ ] SNS topic has subscriber(s) for case note events
- [ ] `SENA_AI_GEMINI_API_KEY` set for personal details WebSocket sessions
- [ ] `SENA_AI_BEDROCK_MODEL_ID` updated to a current Claude Sonnet version (current default is outdated)
- [ ] `SENA_AI_AUTH_MODE` set to `jwt` in production (NOT `dev_header`)
- [ ] JWT public key set (`SENA_AI_JWT_PUBLIC_KEY_PEM`) for production auth
- [ ] Frontend audio pipeline produces PCM16 16kHz mono for WebSocket mode
- [ ] Frontend handles `completeness_score` and `missing_topics` to guide the worker

### What to Confirm Before Integration

1. **LiveKit deployment** — Confirm the LiveKit server URL and whether it's self-hosted or LiveKit Cloud. This service generates access tokens — both sides must use the same server URL.
2. **Who transcribes audio?** — This service does NOT transcribe case note audio. The frontend (via LiveKit STT or client-side) must send text turns to `/turn`. Confirm transcription ownership.
3. **SNS subscriber** — Confirm what subscribes to the SNS topic. Does the backend listen for the `case_note_delivered` event?
4. **Approval queue access** — Coordinator approval via `/v1/voice/approval`. Confirm whether coordinators use a dedicated approval screen or if the backend builds this from Shared DB queries.
5. **Two databases** — This service requires TWO separate PostgreSQL databases. Confirm both are provisioned before deployment.
6. **Bedrock model version** — The default model ID is outdated (`claude-3-5-sonnet-20240620-v1:0`). Update `SENA_AI_BEDROCK_MODEL_ID` to the current version.

---

## QA & Testing

### Running Tests

```bash
cd voice
pytest tests/ -v
```

Covers: session start, turn processing, session end, approval workflow, health checks.

### Manual Test Scenarios

| Scenario | Expected |
|----------|----------|
| Start session (CASE_NOTE) | Returns `lock_acquired: true` + LiveKit credentials |
| Start second session for same participant | Returns `lock_acquired: false` |
| Submit 6 turns covering all sections | `completeness_score` increases toward 1.0 after each turn |
| Submit turn with low confidence (< 0.5) | Service processes it but may flag low reliability |
| End session after partial completion | Draft created with partial sections; missing sections are empty |
| Approve a draft | `status: DELIVERED` + SNS event published |
| Reject a draft | `status: REJECTED`; no SNS event |
| WebSocket personal details | Fields update after each voice exchange |
| `/health/ready` with Redis down | Returns `503` with `redis: "error"` |
| `/health/ready` with SNS unreachable | Returns `503` with `sns: "error"` |

### Known Edge Cases

- **LiveKit audio not transcribed** — The service receives text; if the frontend's transcription is empty or low-quality, the draft will be incomplete. Test with realistic background noise.
- **Bedrock model version** — Default is an older version of Claude Sonnet. Update the env var to the latest version for best quality.
- **SNS delivery** — SNS publish is fire-and-forget. If the SNS topic or subscriber is misconfigured, the event is lost silently. Test the full SNS path before production.
- **Short session timeout** — `SENA_AI_PROVIDER_TIMEOUT_SECONDS` defaults to 1.2s, which is very tight for Bedrock. On high load, turns may timeout. Increase this if you see timeout errors.
- **Personal details WebSocket reconnection** — Session state is in Redis but reconnect flow does not have full integration test coverage. Test drop-and-reconnect scenarios.
- **PII in transcripts** — Raw participant speech is stored in the database without redaction. Consider PII filtering before storing.

---

## Implementation Status

### Done
- Case note dictation: session start, turn processing (with draft sections), session end
- Approval queue workflow (create, approve/reject)
- Personal details: REST turns + WebSocket Gemini Live bidirectional audio
- Redis participant locking (one session per participant)
- Rate limiting (session start + turn processing)
- Async PostgreSQL (AI DB + Shared DB)
- LiveKit access token generation
- SNS event publishing
- JWT auth (production) + dev_header mode (development)
- Idempotent request handling
- Health checks (liveness + readiness with component checks)
- Comprehensive test suite

### Missing / Not Yet Implemented

| Item | Impact | Notes |
|------|--------|-------|
| Bedrock model version outdated | High | Default `BEDROCK_MODEL_ID` is `claude-3-5-sonnet-20240620-v1:0` — update to current Sonnet |
| PII filtering on transcripts | High | Raw speech stored without redaction — compliance risk |
| SNS integration test | Medium | Event published but no integration test confirms delivery |
| Personal details WebSocket reconnection test | Medium | No integration test for connection drop + resume |
| Approval delivery logic | Medium | `approval_service.py` partially implemented for "deliver to shared database" step |
| Auth mode switch reminder | Medium | `dev_header` mode is the default — easy to forget to switch for production |

---

## Integration Requirements

**Mandatory before production integration:**

1. **Two PostgreSQL databases** — AI DB + Shared DB, both with async connection URLs
2. **Redis** — must be accessible for participant locking and rate limiting
3. **LiveKit** — server deployed; API key, secret, and URL configured
4. **AWS SNS topic** — created with subscriber(s) for case note delivery events
5. **`SENA_AI_AUTH_MODE=jwt`** — switch from `dev_header` to JWT mode with public key set
6. **Update `SENA_AI_BEDROCK_MODEL_ID`** — replace outdated default with current Claude Sonnet version
7. **Gemini API key** — required for personal details WebSocket sessions
8. **Frontend transcription pipeline** — frontend must transcribe LiveKit audio before calling `/turn`
9. **Frontend audio pipeline for WebSocket** — PCM16 16kHz mono in, PCM16 24kHz mono out

**Nice to have:**
- PII filtering on transcript storage
- Bedrock model version centralised as an env var (already configured, just needs correct value)
- Integration test for SNS delivery path
- Gemini data residency pinned to `australia-southeast1`
