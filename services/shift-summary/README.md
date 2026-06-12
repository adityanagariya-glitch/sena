# Shift Summary Service

> Lightweight FastAPI microservice that consolidates 1–5 individual shift summaries into a single coherent narrative using AWS Bedrock (Claude Haiku). Designed for low-latency, high-availability shift handover automation on the Sena platform.

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

At the end of a shift or work period, the Sena backend may have multiple individual summaries (e.g., from different staff on the same shift, or from multiple shift periods). This service takes those 1–5 text summaries and returns a single consolidated narrative — suitable for use in handover reports, client progress notes, or coordinator briefings.

**This service is stateless.** No data is persisted. One request in, one consolidated summary out.

---

## How It Works

```
Backend collects N shift summaries from its database
        │
        ▼
POST /summarize  { "summaries": ["text1", "text2", ...] }
  ├─ Validate: 1–5 summaries, each 1–5000 chars
  ├─ Build consolidation prompt
  ├─ Call AWS Bedrock (Claude Haiku, ap-southeast-2)
  └─ Return: { "consolidated_summary": "...", "input_tokens": N, "output_tokens": N }
        │
        ▼
Backend stores / displays the consolidated summary
```

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| API Framework | FastAPI + Uvicorn |
| AI Model | AWS Bedrock — Claude Haiku (`au.anthropic.claude-haiku-4-5-20251001-v1:0`) |
| AWS Region | `ap-southeast-2` (Sydney — AUS data residency) |
| Auth | API Key (`X-API-Key` header, timing-attack safe) |
| Validation | Pydantic v2 |
| Database | None (stateless) |
| Containerization | Not yet (Dockerfile TODO) |

---

## API Reference

### `POST /summarize`

**Headers**
```
Content-Type: application/json
X-API-Key: <your-api-key>
```

**Request Body**
```json
{
  "summaries": [
    "Jane assisted client with morning routine including shower and breakfast. Client was in good spirits. No incidents.",
    "Afternoon support provided. Client attended physio appointment. Transport arranged. Mild fatigue noted post-appointment.",
    "Evening check-in completed. Medications administered as per plan. Client settled for the night."
  ]
}
```

| Field | Type | Required | Constraints |
|-------|------|----------|------------|
| `summaries` | array of strings | Yes | 1–5 items; each 1–5000 characters; no empty/whitespace-only strings |

**Response `200 OK`**
```json
{
  "consolidated_summary": "Jane supported the client throughout the day across morning, afternoon, and evening sessions. The morning routine was completed smoothly, with the client in positive spirits. The afternoon included a physiotherapy appointment with arranged transport, though mild fatigue was noted afterwards. Evening support included scheduled medication administration, and the client settled for the night without incident.",
  "input_tokens": 187,
  "output_tokens": 94
}
```

**Error Responses**

| Code | Reason |
|------|--------|
| `401` | Missing or invalid `X-API-Key` |
| `422` | Validation error — wrong number of summaries, empty string, exceeds length limit |
| `502` | Bedrock invocation failure or response parsing error |

---

### `GET /health`

No auth required.

```json
{
  "status": "ok",
  "version": "1.0.0"
}
```

---

## Environment Variables

Copy `.env.example` to `.env` and fill in values.

> **Note:** The config file currently hardcodes the path `/home/main/SENA/.env`. If deploying on a different machine or in a container, either update `config.py` or ensure the `.env` file is available at that path.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `API_KEY` | Yes | — | Secret for `X-API-Key` header |
| `AWS_ACCESS_KEY_ID` | Yes* | — | AWS credentials (*or use IAM role) |
| `AWS_SECRET_ACCESS_KEY` | Yes* | — | AWS credentials (*or use IAM role) |
| `AWS_REGION` | No | `ap-southeast-2` | Bedrock region |
| `BEDROCK_MODEL_ID` | No | `au.anthropic.claude-haiku-4-5-20251001-v1:0` | Claude model ID |
| `BEDROCK_MAX_TOKENS` | No | `1024` | Max tokens in model response |
| `BEDROCK_TEMPERATURE` | No | `0.3` | 0.0 = deterministic, 1.0 = creative |
| `MIN_SUMMARIES` | No | `1` | Minimum number of summaries allowed |
| `MAX_SUMMARIES` | No | `5` | Maximum number of summaries allowed |
| `MIN_SUMMARY_LENGTH` | No | `1` | Min characters per summary |
| `MAX_SUMMARY_LENGTH` | No | `5000` | Max characters per summary |
| `APP_ENV` | No | `development` | `development` / `production` / `test` |

**IAM permission required:**
```json
{
  "Effect": "Allow",
  "Action": ["bedrock:InvokeModel"],
  "Resource": "arn:aws:bedrock:ap-southeast-2::foundation-model/anthropic.claude-haiku*"
}
```

---

## Running the Service

**Install dependencies**
```bash
pip install -r requirements.txt
```

**Development**
```bash
cd shift-summary
uvicorn main:app --reload
```

**Production**
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

**Swagger UI** — http://localhost:8000/docs (disabled in production mode)

---

## Integration Guide

### For Backend Teams

The backend fetches individual shift summaries from its own database and calls this service to consolidate them.

**Integration Pattern:**
```
Coordinator or automated job triggers summary generation
→ Backend fetches relevant shift note records for the period
→ Backend extracts text summaries (1–5 items)
→ Backend calls POST /summarize
→ Backend stores consolidated_summary in handover / report record
```

**Example call (Python/httpx):**
```python
import httpx

summaries = [note.summary_text for note in shift_notes[:5]]  # max 5

response = httpx.post(
    "http://shift-summary:8000/summarize",
    headers={"X-API-Key": API_KEY, "Content-Type": "application/json"},
    json={"summaries": summaries},
    timeout=30.0  # Bedrock can take 5–15s
)

if response.status_code == 200:
    data = response.json()
    save_consolidated_summary(data["consolidated_summary"])
    log_token_usage(data["input_tokens"], data["output_tokens"])
elif response.status_code == 502:
    # Bedrock failure — retry once, then fall back to manual
    pass
```

**Timeout:** Set at least 30 seconds — Bedrock responses typically take 3–12 seconds.

**Token tracking:** The response includes `input_tokens` and `output_tokens`. Log these if you need cost tracking.

### For Frontend Teams

Frontend does **not** call this service directly. The backend handles consolidation and returns the result through its own API.

**Typical UX:** A "Generate Handover Summary" button triggers the backend, which calls this service and stores the result. The frontend then fetches and displays the stored summary.

**No streaming** — the response is buffered. Show a loading indicator until the response arrives (typically 5–15 seconds for 3–5 summaries).

---

### Pre-Integration Checklist

- [ ] `API_KEY` generated and stored securely in backend secrets manager
- [ ] AWS credentials or IAM role with `bedrock:InvokeModel` in `ap-southeast-2`
- [ ] Backend enforces max 5 summaries before calling this service (client-side or DB-side limit)
- [ ] Backend strips empty/whitespace summaries before passing to this service
- [ ] Backend has timeout set (30+ seconds) on the HTTP client
- [ ] Backend has a fallback for `502` errors (retry once, then manual entry option)
- [ ] CORS restricted to backend IP in production (currently `allow_origins=["*"]`)
- [ ] `.env` path updated if not deploying on `/home/main/SENA/` (see Known Issues)

### What to Confirm Before Integration

1. **Where do shift summaries come from?** Backend must decide which records to pass — all notes from a shift, or a curated selection.
2. **When is consolidation triggered?** Auto (on shift end), manual (coordinator clicks "generate"), or scheduled batch?
3. **Is the consolidated summary editable?** Define whether the result goes directly to output or through an edit step.
4. **What happens on Bedrock failure?** Does the shift handover proceed without a summary, or is it blocked?

---

## QA & Testing

### Running Tests

```bash
cd shift-summary
pytest tests.py -v
```

All tests mock AWS Bedrock — no AWS credentials needed.

### Manual Test Scenarios

| Scenario | Input | Expected |
|----------|-------|----------|
| Single summary | 1 item | Summary returned as-is (lightly reformatted) |
| Three varied summaries | 3 items | Coherent merged narrative, no repetition |
| Five summaries | 5 items | Still within token limits; consolidated cleanly |
| Six summaries | 6 items | `422` validation error |
| Empty string in array | `["valid text", ""]` | `422` validation error |
| Summary over 5000 chars | 1 item > 5000 chars | `422` validation error |
| Missing `X-API-Key` | — | `401 Unauthorized` |
| Wrong `X-API-Key` | — | `401 Unauthorized` |

### Known Edge Cases

- **Very similar summaries** (e.g., two workers both noting the same incident) — Model handles deduplication well but may occasionally repeat. Review output.
- **Contradictory summaries** — If two summaries contradict each other, the model picks the most neutral interpretation. Human review recommended for clinical notes.
- **Long summaries (near 5000 chars each)** — With 5 × 5000 = 25,000 input chars, response time may reach 20–25 seconds. Adjust frontend loading states accordingly.

---

## Implementation Status

### Done
- POST /summarize — fully functional
- GET /health
- Input validation (count, length, empty string checks)
- API key authentication (timing-attack safe with `hmac.compare_digest`)
- AWS Bedrock Claude Haiku integration
- Token usage returned in response
- CORS middleware
- Full test suite (all Bedrock calls mocked)

### Missing / Not Yet Implemented

| Item | Impact | Notes |
|------|--------|-------|
| Docker / Dockerfile | Medium | No container support |
| CORS restriction | High | Currently `allow_origins=["*"]` — must restrict before production |
| `.env` path hardcoded | Medium | `config.py` hardcodes `/home/main/SENA/.env` — must update for other environments |
| Streaming response | Low | Response is buffered; no SSE/streaming support |
| Bedrock retry logic | Medium | No automatic retry on throttle — caller must retry |
| Boto3 call timeout | Medium | No explicit timeout configured on the Bedrock call |

---

## Integration Requirements

**Mandatory before production integration:**

1. **`API_KEY`** — generate a strong secret and store in backend secrets manager
2. **AWS credentials / IAM role** — `bedrock:InvokeModel` in `ap-southeast-2`
3. **Update `.env` path** — change the hardcoded `/home/main/SENA/.env` path in `config.py` to match your deployment environment
4. **Restrict CORS** — change `allow_origins=["*"]` in `main.py` to the backend domain/IP
5. **Backend retry logic** — add one retry on `502` with a 3-second delay
6. **Dockerfile** — required for containerized deployment
7. **Frontend timeout** — set at least 30 seconds on loading state

**Nice to have:**
- Streaming response for real-time output display
- Boto3 timeout configuration (currently can hang indefinitely)
- Centralised logging / CloudWatch integration
