# SENA AI — Frontend Integration URLs

## Auth headers (all requests)

```
X-Tenant-Id: <tenant_id>
X-Participant-Id: <user_id>
X-User-Roles: worker
```

---

## Local dev (direct service ports)

| Service | Base URL | Health check |
|---------|----------|--------------|
| Case Review (voice, RP) | `http://localhost:8084` | `/v1/restrictive-practices/health` |
| Voice (case note dictation) | `http://localhost:8082` | `/health/live` |
| Onboarding | `http://localhost:8083` | `/health/live` |
| Casenote Monthly | `http://localhost:8602` | `/psr-report/health` |
| Policy & Procedures | `http://localhost:8000` | `/health` |
| Staff / Client Q&A | `http://localhost:8601` | `/health` |
| AI Chatbot gateway | `http://localhost:8003` | `/ai-chatbot/healthz` |
| AI Communication Log | `http://localhost:8005` | `/health` |
| Shift Summary | `http://localhost:8006` | `/health` |
| AI Text Extraction | `http://localhost:8007` | `/health` |

---

## Production (EC2 — all through nginx gateway)

**Base:** `http://3.111.109.14:8080`

| Service | Path prefix | Example |
|---------|-------------|---------|
| Case Review | `/case-review/` | `http://3.111.109.14:8080/case-review/v1/case-review/voice/session` |
| Voice | `/voice/` | `http://3.111.109.14:8080/voice/v1/voice/session` |
| Onboarding | `/onboarding/` | `http://3.111.109.14:8080/onboarding/v1/onboarding/session` |
| Casenote Monthly | `/casenote/` | `http://3.111.109.14:8080/casenote/...` |
| Policy | `/policy/` | `http://3.111.109.14:8080/policy/...` |
| Staff | `/staff/` | `http://3.111.109.14:8080/staff/...` |
| AI Chatbot | `/ai-chatbot/` | `http://3.111.109.14:8080/ai-chatbot/...` |
| AI Comm Log | `/ai-comm-log/` | `http://3.111.109.14:8080/ai-comm-log/...` |
| Shift Summary | `/shift-summary/` | `http://3.111.109.14:8080/shift-summary/...` |
| Text Extraction | `/text-extraction/` | `http://3.111.109.14:8080/text-extraction/...` |

---

## Case Review voice endpoints (key flow)

### 1. Create voice session
```
POST /v1/case-review/voice/session
Body: { "client_id": "...", "shift_id": "...", "initial_values": {} }
Returns: { "session_id": "...", "ws_url": "/ws/case-review/voice/<id>" }
```

### 2. Connect WebSocket
```
Local:  ws://localhost:8084/ws/case-review/voice/<session_id>
Prod:   ws://3.111.109.14:8080/case-review/ws/case-review/voice/<session_id>

Query params (no header support on WS):
  ?tenant_id=<id>&participant_id=<id>&roles=worker
```

### 3. Draft from transcript (optional pre-fill)
```
POST /v1/case-review/voice/draft
Body: { "transcript": "..." }
Returns: { "initial_values": {...}, "gaps_note": "...", "filled_count": 3 }
```

---

## Swagger docs (local only)

| Service | URL |
|---------|-----|
| Case Review | http://localhost:8084/docs |
| Voice | http://localhost:8082/docs |
| Onboarding | http://localhost:8083/docs |
| All others | `http://localhost:<port>/docs` |
