# AI Communication Log Classifier

> Stateless FastAPI microservice that classifies support-worker ↔ client conversations as **emergency**, **inappropriate**, or **normal** using AWS Bedrock (Claude Sonnet 4.5). Built for real-time NDIS compliance monitoring on the Sena platform.

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

This service sits inline with the Sena messaging layer. Each time a support worker or client sends a message, the **backend** calls this service with the message and recent conversation history. The service classifies it and returns multi-label results with confidence scores, sentiment, risk level, and a recommended action. The backend then decides what to do — alert, log, escalate, or pass through.

**This service does not store any data.** It is fully stateless. One request in, one classification response out.

---

## How It Works

```
Backend receives new message
        │
        ▼
POST /api/v1/classify
  ├─ Validate request (Pydantic)
  ├─ Trim history to last N messages (CONVERSATION_HISTORY_LIMIT)
  ├─ Build system prompt + user prompt
  ├─ Call AWS Bedrock (Claude Sonnet 4.5, ap-southeast-2)
  ├─ Parse JSON response from model
  └─ Return: classifications + sentiment + risk + breakdown + outcome
        │
        ▼
Backend decides: log / alert / escalate / pass
```

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| API Framework | FastAPI + Uvicorn |
| AI Model | AWS Bedrock — Claude Sonnet 4.5 (`au.anthropic.claude-sonnet-4-5-20250929-v1:0`) |
| AWS Region | `ap-southeast-2` (Sydney — AUS data residency) |
| Validation | Pydantic v2 |
| Auth | API Key (`X-API-Key` header) |
| Database | None (stateless) |
| Containerization | Not yet (Dockerfile TODO) |

---

## API Reference

### `POST /api/v1/classify`

**Headers**
```
Content-Type: application/json
X-API-Key: <your-api-key>
```

**Request Body**
```json
{
  "conversation_id": "conv_20250601_001",
  "provider_id": "org_abc_123",
  "current_message": {
    "role": "support_worker",
    "text": "I don't want to deal with you anymore.",
    "timestamp": "2025-06-01T10:05:00Z"
  },
  "history": [
    {
      "role": "client",
      "text": "I need help getting to the bathroom.",
      "timestamp": "2025-06-01T10:03:00Z"
    }
  ],
  "metadata": {
    "shift_id": "shift_789",
    "client_id": "client_456",
    "worker_id": "worker_321"
  }
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `conversation_id` | string | Yes | Unique ID for this conversation thread |
| `provider_id` | string | Yes | Org ID for data isolation |
| `current_message` | object | Yes | The message being classified |
| `current_message.role` | string | Yes | `support_worker` or `client` |
| `current_message.timestamp` | string | Yes | ISO 8601 UTC format |
| `history` | array | No | Past messages; server trims to `CONVERSATION_HISTORY_LIMIT` |
| `metadata` | object | No | Shift, client, worker IDs for audit trail |

**Response `200 OK`**
```json
{
  "conversation_id": "conv_20250601_001",
  "provider_id": "org_abc_123",
  "is_uncertain": false,
  "classifications": [
    {
      "label": "inappropriate",
      "confidence": 0.91,
      "reason": "Support worker expressed dismissiveness, violating NDIS Code of Conduct."
    }
  ],
  "sentiment": {
    "label": "frustrated_dissatisfied",
    "confidence": 0.85,
    "reason": "Tone suggests frustration and refusal."
  },
  "risk": {
    "level": "high",
    "indicators": ["refusal_to_assist", "dismissive_language"],
    "reason": "Worker is refusing basic care obligation."
  },
  "breakdown": {
    "detected": true,
    "reasons": ["Code of Conduct violation — Section 4.2"]
  },
  "outcome": "unresolved",
  "recommended_action": "Flag for supervisor review and incident reporting.",
  "messages_analysed": 2,
  "analysed_at": "2025-06-01T10:05:01Z"
}
```

| Field | Description |
|-------|-------------|
| `is_uncertain` | `true` if all confidence scores are below `CONFIDENCE_THRESHOLD` |
| `classifications` | Multi-label — can include `emergency`, `inappropriate`, and/or `normal` simultaneously |
| `sentiment.label` | One of: `positive_satisfied`, `neutral`, `frustrated_dissatisfied`, `distressed_upset`, `confused_uncertain`, `engaged`, `disengaged` |
| `risk.level` | One of: `low`, `medium`, `high`, `critical` |
| `outcome` | One of: `resolved`, `unresolved`, `pending` |
| `recommended_action` | Free-text suggestion; `null` if normal |

**Classification Labels**

| Label | When Used |
|-------|-----------|
| `emergency` | Immediate risk — self-harm, medical emergency, abuse, violence |
| `inappropriate` | NDIS Code of Conduct violation — verbal abuse, coercion, restrictive practice |
| `normal` | Professional conversation, no concerns |

`normal` is never combined with other labels. `emergency` and `inappropriate` can appear together.

**Error Responses**

| Code | Reason |
|------|--------|
| `401` | Missing or invalid `X-API-Key` |
| `422` | Validation error — missing required fields or wrong format |
| `500` | Bedrock invocation failure or response parsing error |

---

### `GET /health`

No auth required.

```json
{
  "status": "ok",
  "version": "1.0.0",
  "model": "au.anthropic.claude-sonnet-4-5-20250929-v1:0"
}
```

---

## Environment Variables

Copy `.env.example` to `.env` and fill in values.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `API_KEY` | Yes | — | Secret for `X-API-Key` header |
| `AWS_ACCESS_KEY_ID` | Yes* | — | AWS credentials (*or use IAM role) |
| `AWS_SECRET_ACCESS_KEY` | Yes* | — | AWS credentials (*or use IAM role) |
| `AWS_REGION` | No | `ap-southeast-2` | Bedrock region (do not change — AUS data residency) |
| `BEDROCK_MODEL_ID` | No | `au.anthropic.claude-sonnet-4-5-20250929-v1:0` | Claude model ID |
| `BEDROCK_MAX_TOKENS` | No | `1024` | Max tokens in model response |
| `BEDROCK_TEMPERATURE` | No | `0.1` | Low = consistent classification |
| `CONFIDENCE_THRESHOLD` | No | `0.5` | Below this → `is_uncertain: true` |
| `CONVERSATION_HISTORY_LIMIT` | No | `5` | Max past messages sent to model |
| `DEBUG` | No | `false` | Enables verbose logging |

**IAM permission required for the AWS role/user:**
```json
{
  "Effect": "Allow",
  "Action": ["bedrock:InvokeModel"],
  "Resource": "arn:aws:bedrock:ap-southeast-2::foundation-model/anthropic.claude-3-5-sonnet*"
}
```

---

## Running the Service

**Install dependencies**
```bash
pip install -r ai-classifier/requirements.txt
```

**Development**
```bash
cd ai-classifier
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Production**
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**Interactive CLI tester** (manual testing only)
```bash
python ai-classifier/chat.py
```

**Swagger UI** — http://localhost:8000/docs (available in all modes)

---

## Integration Guide

### For Backend Teams

This service is called by the **Sena backend** each time a conversation message is sent. The backend owns the decision logic (what to do with the classification); this service only classifies.

**Integration Pattern:**
```
User sends message → Sena backend saves message → backend calls POST /api/v1/classify
→ backend reads response → backend acts (log, alert, flag, pass)
```

**Call this endpoint when:**
- A new message is received in a shift conversation
- You want to re-classify a previous message (e.g., after appeal)

**Do not call this endpoint for:**
- Internal system messages or automated notifications
- Messages sent outside of active shift sessions

**Example call (Python/httpx):**
```python
import httpx

response = httpx.post(
    "http://ai-communication-log:8000/api/v1/classify",
    headers={"X-API-Key": API_KEY},
    json={
        "conversation_id": str(conversation.id),
        "provider_id": str(org.id),
        "current_message": {
            "role": message.sender_role,
            "text": message.text,
            "timestamp": message.created_at.isoformat()
        },
        "history": [
            {"role": m.role, "text": m.text, "timestamp": m.created_at.isoformat()}
            for m in last_5_messages
        ],
        "metadata": {
            "shift_id": str(shift.id),
            "client_id": str(client.id),
            "worker_id": str(worker.id)
        }
    }
)
result = response.json()
```

**Handling the response:**
- Check `result["classifications"]` for labels — trigger alerts on `emergency` or `inappropriate`
- Check `result["risk"]["level"]` — escalate on `high` or `critical`
- Store `result["analysed_at"]` and `result["recommended_action"]` in your audit log
- If `result["is_uncertain"] == true` — queue for human review rather than auto-flagging

### For Frontend Teams

Frontend does **not** call this service directly. The backend handles classification and pushes results to the frontend via its own notification/alert system. There is no WebSocket or SSE — this is a request/response API.

If your frontend needs to display a classification badge or alert, consume it from the backend's notification feed, not from this service.

---

### Pre-Integration Checklist

Before wiring this service into the platform:

- [ ] `API_KEY` is set and stored securely in the backend (not in frontend code)
- [ ] AWS credentials or IAM role attached with `bedrock:InvokeModel` permission in `ap-southeast-2`
- [ ] Backend is prepared to handle `500` responses gracefully (Bedrock can throttle)
- [ ] Backend has a retry strategy for transient failures (1–2 retries with backoff)
- [ ] Backend stores `conversation_id`, `provider_id`, and classification result in audit log
- [ ] CORS is locked to backend IP in production (currently `*` — see Known Issues)
- [ ] `CONVERSATION_HISTORY_LIMIT` is tuned to match your message volume (default: 5)
- [ ] Alert/escalation workflow is defined for `emergency` and `high-risk` classifications

### What to Confirm Before Integration

1. **Who triggers the call?** The backend — not the frontend. Confirm the backend message-receive handler is the integration point.
2. **What happens on `emergency`?** Confirm the escalation path (supervisor alert, incident log, etc.) before going live.
3. **What happens when the service is down?** Define a fallback — do messages still go through? Are they queued?
4. **Is rate limiting in place on the backend side?** This service has no rate limiter; the backend should throttle calls if needed.

---

## QA & Testing

### Running Tests

**Unit tests (no AWS calls, fast):**
```bash
cd ai-classifier
pytest tests/test_unit.py -v
```

**Integration tests (real Bedrock, requires AWS credentials):**
```bash
pytest tests/test_classify.py -v
```

**Postman collection:** `tests/sena_classifier.postman_collection.json` — import into Postman for manual API testing.

### Manual Test Scenarios

| Scenario | Expected Label | Expected Risk |
|----------|---------------|---------------|
| Worker says "I'll hurt you if you don't cooperate" | `emergency` + `inappropriate` | `critical` |
| Worker says "I hate this job" (to themselves, not client) | `normal` or `inappropriate` (low confidence) | `low` |
| Client says "I feel like hurting myself" | `emergency` | `critical` |
| Worker says "Let's get you ready for your appointment" | `normal` | `low` |
| Empty or very short message (< 5 words) | Low confidence → `is_uncertain: true` | — |
| Message with special characters or emoji only | `is_uncertain: true` | — |

### Known Edge Cases

- **Very short messages** (single words, greetings) often return `is_uncertain: true` — expected behaviour.
- **Context-dependent messages** — classification accuracy improves significantly when `history` is provided. Always include history.
- **Non-English messages** — model attempts classification but accuracy is lower. Flag these for human review.
- **Bedrock throttling** — during peak load, Bedrock may return `ThrottlingException`. The service returns `500`; backend should retry after 2–5 seconds.

---

## Implementation Status

### Done
- POST /api/v1/classify — fully functional
- GET /health
- Multi-label classification (emergency / inappropriate / normal)
- Sentiment analysis
- Risk level scoring
- Breakdown detection
- Outcome and recommended action
- Conversation history trimming
- API key authentication (simple equality check)
- Structured logging
- Unit tests + integration tests
- Postman collection

### Missing / Not Yet Implemented

| Item | Impact | Notes |
|------|--------|-------|
| Docker / Dockerfile | Medium | Docs show a sample Dockerfile but it is not added to the repo |
| CORS lock-down | High | Currently `allow_origins=["*"]` — must be restricted to backend IP before production |
| Rate limiting | Medium | No per-IP or per-org rate limiting; backend must throttle |
| Webhooks / async alerts | Low | Service is request/response only — caller handles alerting |
| Streamlit dev UI | Low | File `steam;it_app.py` has a filename typo (semicolon) — broken, not integrated |
| Trend analysis | Out of scope | Per-message classification only; no conversation-level trends |
| Secure API key comparison | Low | Uses simple string equality; `hmac.compare_digest` recommended |

---

## Integration Requirements

**Mandatory before production integration:**

1. **API_KEY** — must be generated, stored in backend secrets manager, and set in `.env`
2. **AWS credentials / IAM role** — `bedrock:InvokeModel` in `ap-southeast-2`
3. **CORS restriction** — change `allow_origins=["*"]` to the backend's IP/domain in `app/main.py:34`
4. **Backend error handling** — handle `500` with retry; handle `401` by refreshing API key
5. **Audit log schema** — backend must have a table to store classification results with `conversation_id`, `shift_id`, `client_id`, `worker_id`, labels, confidence, risk level, timestamp
6. **Escalation workflow** — defined alert path for `emergency` and `critical` risk before go-live
7. **Dockerfile** — must be created for containerized deployment

**Nice to have:**
- Rate limiting middleware (e.g., slowapi)
- Centralized logging (e.g., CloudWatch) instead of stdout only
- Webhook support for async push-based alerting
