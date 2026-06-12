# Case Review Service

> FastAPI service that automates NDIS restrictive practice detection via a 7-stage LangGraph pipeline. Combines Amazon Transcribe (audio), AWS Bedrock Claude (triage + evaluation), pgvector RAG (policy retrieval), and Google Gemini Live (real-time voice dictation) into a single compliance review workflow.

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

After a shift, a support worker may have recorded audio notes or completed a case note form. This service provides two paths:

1. **Pipeline path** — Submit a completed (or draft) case note through the 7-stage evaluation pipeline that determines whether restrictive practices were used, cross-checks against the client's Behaviour Support Plan (BSP), and auto-generates an incident report draft if needed.
2. **Voice path** — Open a Gemini Live WebSocket session to dictate case notes in real time via voice. The AI assistant guides the worker through the form fields conversationally.

> **CRITICAL: This service currently cannot start.** `config.py` and `main.py` are missing from the repository. These must be created before the service is deployable. See [Implementation Status](#implementation-status).

---

## How It Works

### Pipeline (REST)

```
POST /v1/restrictive-practices/evaluate
  ├─ Stage 1: Validate case note inputs
  ├─ Stage 2 (Triage): Claude Haiku — cheap YES/NO: "Any restrictive practice signal?"
  │     └─ NO → short-circuit, return "no_concern"
  ├─ Stage 3 (RAG): pgvector cosine search — retrieve relevant NDIS policy chunks
  ├─ Stage 4 (Evaluator): Claude Sonnet — detailed compliance analysis with policy context
  ├─ Stage 5 (Cross-Check): BSP database lookup — is this practice authorised?
  ├─ Stage 6 (Summary): AI quality score + progress summary
  └─ Stage 7 (Incident Draft): If confirmed → auto-generate incident report sections (parallel)
        │
        ▼
Return: verdict + incident draft + compliance details + quality score
        │
        ▼
Webhook fires to external system (async, background)
```

### Voice Dictation (WebSocket)

```
POST /v1/restrictive-practices/voice/session  →  session_id + ws_url
        │
        ▼
WSS /v1/restrictive-practices/voice/ws/{session_id}?token=<token>
  ├─ Client streams PCM16 audio (16 kHz)
  ├─ Gemini Live generates spoken responses (24 kHz)
  ├─ Agent uses tool calls to update case note form fields
  ├─ Session state persisted in Redis
  └─ Worker finalises note when all fields are complete
```

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| API Framework | FastAPI + Uvicorn |
| Pipeline Orchestration | LangGraph |
| Triage Model | AWS Bedrock — Claude Haiku |
| Evaluation Model | AWS Bedrock — Claude Sonnet 3.5 |
| Voice Agent | Google Gemini Live API |
| Speech-to-Text | Amazon Transcribe (en-AU + custom vocabulary) |
| Document Storage | Amazon S3 (temp audio) |
| Vector Store | pgvector on PostgreSQL (HNSW index, cosine similarity) |
| Relational DB | PostgreSQL (BSP, CaseNoteRun, NDISPolicyChunk) |
| Session Cache | Redis (voice session state, TTL-based) |
| Auth | HTTP Basic (REST, optional) + Token query param (voice WS) |
| Port | 8084 |

---

## API Reference

### REST Endpoints

#### `POST /v1/restrictive-practices/evaluate`
Run a completed case note through the full detection pipeline.

**Request Body**
```json
{
  "worker_id": "worker_321",
  "client_id": "client_456",
  "shift_id": "shift_789",
  "shift_date": "2026-06-01",
  "form_fields": {
    "participant_state": "Client was agitated during morning routine.",
    "support_actions": "Staff held client's arm to prevent them from leaving the room.",
    "incidents_risks": "Physical restraint used for approximately 2 minutes.",
    "medications_health": "No medication changes.",
    "outcomes_followup": "Client calmed after 10 minutes. BSP reviewed.",
    "handover_notes": "Incident documented. Coordinator notified."
  }
}
```

**Response `200 OK`**
```json
{
  "verdict": "restrictive_practice_confirmed",
  "practice_type": "physical_restraint",
  "authorised": false,
  "bsp_status": "no_bsp_found",
  "confidence": 0.94,
  "policy_references": ["NDIS Code of Conduct 4.2", "Restrictive Practices Guidelines §3.1"],
  "incident_draft": {
    "incident_type": "Unauthorised Restrictive Practice",
    "description": "...",
    "immediate_actions": "...",
    "notification_required": true
  },
  "quality_score": "good",
  "summary": "Case note documents a physical restraint incident..."
}
```

---

#### `POST /v1/restrictive-practices/draft`
Extract a voice transcript into pre-filled case note form fields (stateless).

**Request Body**
```json
{
  "transcript": "I helped Sarah with her morning routine. She became upset and I held her arm briefly to stop her from running into traffic.",
  "worker_id": "worker_321",
  "client_id": "client_456"
}
```

**Response:** Structured form fields extracted from the transcript.

---

#### `POST /v1/restrictive-practices/draft/audio`
Upload an audio file for transcription + form field extraction (multipart).

**Request:** `multipart/form-data`
- `audio` — audio file
- `worker_id`, `client_id`, `shift_date` — form fields

**Response:** Same as `/draft`.

---

#### `POST /v1/restrictive-practices/bsp`
Register a Behaviour Support Plan for a client.

```json
{
  "client_id": "client_456",
  "practice_type": "physical_restraint",
  "status": "Active",
  "conditions": "Only when client is at immediate risk of self-harm",
  "auth_by": "Dr Jane Smith (Behaviour Support Practitioner)",
  "valid_from": "2026-01-01",
  "valid_to": "2026-12-31"
}
```

#### `GET /v1/restrictive-practices/bsp/{client_id}`
List all BSPs for a client.

#### `PATCH /v1/restrictive-practices/bsp/{bsp_id}/status`
Update BSP status: `Active` | `Expired` | `Revoked`.

#### `GET /v1/restrictive-practices/health`
```json
{ "status": "ok", "service": "case-review" }
```

---

### Voice Session Endpoints

#### `POST /v1/restrictive-practices/voice/session`
Create a voice dictation session.

**Headers:** `X-Tenant-Id`, `X-User-Id`, `X-User-Roles`, `X-Participant-Id`

**Request Body**
```json
{
  "case_note_id": "cn_001",
  "worker_id": "worker_321",
  "client_id": "client_456",
  "initial_values": {},
  "readonly_paths": []
}
```

**Response**
```json
{
  "session_id": "sess_abc123",
  "ws_url": "wss://host/v1/restrictive-practices/voice/ws/sess_abc123?token=<token>",
  "expires_at": "2026-06-01T11:00:00Z"
}
```

---

#### `WSS /v1/restrictive-practices/voice/ws/{session_id}?token=<token>`
Real-time bidirectional voice session.

**Client → Server frames:**
| Frame | Type | Description |
|-------|------|-------------|
| Binary | PCM16 16kHz mono | Continuous audio from user's microphone |
| JSON | `{"type":"hello"}` | Must be first text frame |
| JSON | `{"type":"tool_response","id":"...","result":{...}}` | App confirms field update |
| JSON | `{"type":"screen_state_v2","data":{...}}` | Visible form state update |
| JSON | `{"type":"stop"}` | Graceful close |

**Server → Client frames:**
| Frame | Type | Description |
|-------|------|-------------|
| Binary | PCM16 24kHz mono | Agent voice output — play immediately |
| JSON | `{"type":"ready","state":{...}}` | Session accepted, initial form state |
| JSON | `{"type":"tool_request","tool":"update_field","args":{...}}` | Agent wants to update a field |
| JSON | `{"type":"turn_complete"}` | Agent finished speaking this turn |
| JSON | `{"type":"user_said","text":"..."}` | Transcription of what user said |
| JSON | `{"type":"go_away","time_left_ms":30000}` | Session about to expire |
| JSON | `{"type":"error","code":"...","message":"..."}` | Error |

---

## Environment Variables

> **These env vars are expected by the code but `config.py` is missing from the repo. You must create `config.py` before the service will start.**

| Variable | Required | Description |
|----------|----------|-------------|
| `SENA_AI_RP_DATABASE_URL` | Yes | PostgreSQL async URL (e.g. `postgresql+asyncpg://user:pass@host:5432/sena_case_review`) |
| `SENA_AI_BASIC_AUTH_USER` | No | HTTP Basic Auth username (if not set, auth is disabled) |
| `SENA_AI_BASIC_AUTH_PASSWORD` | No | HTTP Basic Auth password |
| `SENA_AI_TRANSCRIPTION_BUCKET` | Yes (audio) | S3 bucket for temporary audio file storage |
| `SENA_AI_GEMINI_API_KEY` | Yes (voice) | Google Generative AI API key |
| `SENA_AI_GEMINI_LIVE_MODEL_ID` | No | Gemini Live model (default: `gemini-3.1-flash-live-preview`) |
| `SENA_AI_CASE_REVIEW_REDIS_URL` | Yes (voice) | Redis URL for voice session state (e.g. `redis://localhost:6380/0`) |
| `SENA_AI_VOICE_SESSION_MAX_SEC` | No | Voice session TTL in seconds (default: 3600) |
| `SENA_AI_VOICE_SILENCE_TIMEOUT_SEC` | No | Silence before "are you still there?" (default: 8) |
| `AWS_REGION` | No | AWS region (default: `ap-southeast-2`) |

**AWS IAM permissions required:**
```json
{
  "Effect": "Allow",
  "Action": [
    "bedrock:InvokeModel",
    "bedrock:InvokeModelWithResponseStream",
    "transcribe:StartTranscriptionJob",
    "transcribe:GetTranscriptionJob",
    "s3:PutObject",
    "s3:GetObject"
  ],
  "Resource": "*"
}
```

---

## Running the Service

**Prerequisites:**
- PostgreSQL with `pgvector` extension enabled
- Redis instance running
- Policy documents ingested into pgvector (see below)

**NDIS policy ingestion (must run before first use):**
```bash
cd case_review
python scripts/ingest_ndis_policies.py
python scripts/ingest_style_standards.py
```

**Docker (recommended):**
```bash
docker-compose -f docker-compose_db.yml up -d   # starts PostgreSQL + Redis
docker-compose -f docker-compose.prod.yml up     # starts API service
```

**Manual (after creating config.py and main.py):**
```bash
uvicorn main:app --host 0.0.0.0 --port 8084
```

---

## Integration Guide

### For Backend Teams

The backend orchestrates two integration flows:

**Flow 1 — Evaluation (synchronous, 10–30s):**
```
Worker submits case note form
→ Backend calls POST /v1/restrictive-practices/evaluate
→ Backend receives verdict + incident draft
→ Backend stores result, triggers supervisor alert if confirmed
→ Webhook fires to external compliance system (async)
```

**Flow 2 — Voice Dictation:**
```
Worker opens voice dictation UI
→ Backend calls POST /v1/restrictive-practices/voice/session
→ Backend returns ws_url to frontend
→ Frontend opens WebSocket directly to this service
→ Agent collects form fields via voice
→ Backend receives tool_request frames and updates form state
→ On completion, backend saves the collected form data
```

**Example evaluation call (Python/httpx):**
```python
response = httpx.post(
    "http://case-review:8084/v1/restrictive-practices/evaluate",
    auth=(BASIC_AUTH_USER, BASIC_AUTH_PASSWORD),  # optional
    json={"worker_id": ..., "client_id": ..., "shift_id": ..., "form_fields": {...}},
    timeout=60.0  # pipeline can take up to 30s
)
```

### For Frontend Teams

Frontend interacts with this service **only** for the voice WebSocket. All REST calls go through the backend.

**Voice integration pattern:**
1. Backend calls POST /voice/session → receives `ws_url`
2. Backend passes `ws_url` to frontend
3. Frontend opens WebSocket to `ws_url`
4. Frontend streams PCM16 audio from microphone
5. Frontend plays back binary PCM16 audio received from server
6. Frontend handles `tool_request` frames — applies field updates to the form UI and sends `tool_response` to confirm
7. Frontend sends `screen_state_v2` updates when the user navigates between form sections

**Audio requirements:**
- Input: PCM16, 16 kHz, mono — no compression
- Output: PCM16, 24 kHz, mono — play via Web Audio API or similar

---

### Pre-Integration Checklist

- [ ] `config.py` created with all required settings (BLOCKER — service won't start without this)
- [ ] `main.py` created as FastAPI app factory (BLOCKER — Dockerfile references this file)
- [ ] PostgreSQL running with `pgvector` extension installed
- [ ] Redis running and accessible
- [ ] NDIS policy documents ingested into pgvector (`scripts/ingest_*.py` run)
- [ ] BSP records seeded for test clients (use `scripts/seed_demo.py`)
- [ ] AWS credentials with Transcribe + Bedrock + S3 permissions
- [ ] Google Gemini API key configured
- [ ] S3 bucket for temporary audio storage created
- [ ] Webhook target URL defined and accessible (for incident alerts)
- [ ] Gemini data residency pinned to `australia-southeast1` (pending — see Known Issues)

### What to Confirm Before Integration

1. **BSP data source** — BSPs must be registered via the `/bsp` endpoint before evaluation. Confirm who creates them and when.
2. **Webhook target** — The service fires async webhooks on confirmed incidents. Define the target URL and expected payload format.
3. **Audio format from frontend** — Confirm the frontend can produce PCM16 16kHz mono. Many browser audio APIs default to different formats.
4. **Voice session timeout** — 60 minutes default. Adjust if workers are unlikely to complete in time.
5. **Who handles incident draft?** — Confirm whether the backend auto-submits the incident draft or a coordinator reviews it first.

---

## QA & Testing

### Test Scripts
```bash
cd case_review/scripts
python test_pipeline.py      # pipeline evaluation
python test_triage.py        # triage gate only
python test_rag.py           # RAG retrieval
python test_evaluator.py     # evaluator only
python _debug_pipeline.py    # full debug run
```

### Manual Test Scenarios

| Scenario | Expected Result |
|----------|----------------|
| Case note with clear physical restraint | `verdict: restrictive_practice_confirmed`, incident draft generated |
| Routine shift note (no incident) | Triage gate returns NO — pipeline stops early, no incident draft |
| Case note with authorised BSP practice | `verdict: authorised_practice`, `authorised: true` |
| Audio upload with unclear speech | Transcription may have gaps — form fields partially filled |
| Voice session with silence > 8s | Server sends "are you still there?" prompt |
| Voice session with wrong audio format | Gemini Live returns error or produces garbled output |
| BSP not found for detected practice | `bsp_status: no_bsp_found` — flagged as unauthorised |

---

## Implementation Status

### Done
- All REST endpoints (evaluate, draft, draft/audio, bsp CRUD, health)
- 7-stage LangGraph pipeline (triage → RAG → evaluator → cross-check → summary → incident draft)
- pgvector HNSW indexing and cosine similarity search
- BSP database (ORM models, CRUD endpoints)
- Google Gemini Live voice WebSocket bridge
- Redis-backed voice session state
- Voice form tools (update_field, clear_field, finalize_note, get_current_state)
- Field validators (field-level, cross-field, sequencing)
- Amazon Transcribe integration (en-AU, custom vocabulary)
- Docker + docker-compose files
- Policy ingestion scripts

### Missing / Not Yet Implemented

| Item | Impact | Notes |
|------|--------|-------|
| `config.py` | **BLOCKER** | Missing — service cannot start without it |
| `main.py` | **BLOCKER** | Missing — Dockerfile tries to run `uvicorn main:app` |
| Webhook target definition | High | `pipeline/webhook.py` fires but target URL not defined |
| Gemini data residency pin | High | Not yet pinned to `australia-southeast1` — required before real participant audio |
| Voice session resumption (full) | Medium | `voice/resumption.py` skeleton exists but not fully wired |
| Bedrock model IDs in config | Low | Hardcoded in triage.py and evaluator.py — should reference settings |

---

## Integration Requirements

**Mandatory before any integration:**

1. **Create `config.py`** — Must define a `Settings` class with all env vars listed above (use Pydantic Settings)
2. **Create `main.py`** — Must create the FastAPI app, include routers from `api/routes.py` and `api/voice_routes.py`, and define lifespan hooks for DB init
3. **PostgreSQL + pgvector** — Database must be running with the `vector` extension enabled
4. **Run policy ingestion** — `scripts/ingest_ndis_policies.py` must be run before the RAG retrieval step works
5. **Redis** — Required for voice session state
6. **S3 bucket** — Required for audio upload via `/draft/audio`
7. **Google Gemini API key** — Required for voice sessions
8. **AWS permissions** — Bedrock (Haiku + Sonnet) + Transcribe + S3

**Required for voice integration specifically:**
- Frontend must produce PCM16 16kHz mono audio
- Frontend must implement `tool_response` message handling
- Frontend must handle binary PCM16 audio playback at 24kHz

**Nice to have:**
- Webhook target service to receive incident alerts
- Gemini data residency configuration (`australia-southeast1`)
- HTTP Basic Auth credentials for production REST endpoints
