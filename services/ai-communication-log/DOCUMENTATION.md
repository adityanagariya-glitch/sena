# Sena AI Communication Classifier — Integration Documentation

**Version:** 1.2.0  
**Last updated:** 2026-06-15  
**Audience:** Backend integration team, frontend integration team, QA  
**Model:** AWS Bedrock — Claude Sonnet 4.5 (Sydney region, `ap-southeast-2`)

---

## Table of Contents

1. [What This Service Is](#1-what-this-service-is)
2. [What It Does and Does NOT Do](#2-what-it-does-and-does-not-do)
3. [How It Works — Flow Overview](#3-how-it-works--flow-overview)
4. [Project Structure](#4-project-structure)
5. [Internal Data Flow — Request to Response](#5-internal-data-flow--request-to-response)
6. [Local Setup and Running](#6-local-setup-and-running)
7. [API Reference](#7-api-reference)
   - [POST /api/v1/sentiment-batch](#post-apiv1sentiment-batch)
   - [GET /health](#get-health)
8. [Full Request and Response Examples](#8-full-request-and-response-examples)
9. [Field Reference](#9-field-reference)
10. [Integration Guide — Backend Team](#10-integration-guide--backend-team)
11. [Integration Guide — Frontend Team](#11-integration-guide--frontend-team)
12. [Authentication and Security](#12-authentication-and-security)
13. [Configuration Reference](#13-configuration-reference)
14. [Error Handling](#14-error-handling)
15. [Running Tests](#15-running-tests)
16. [Interactive Conversation Tester](#16-interactive-conversation-tester)
17. [Placeholders and Future Work](#17-placeholders-and-future-work)

---

## 1. What This Service Is

This is a **single-purpose AI batch analysis microservice** for the Sena platform.

It receives a window of up to N messages from a support worker ↔ client conversation and returns a full analysis — sentiment, risk, breakdown, outcome, and recommended action — for **every individual message** in that batch.

It does not store data. It does not trigger alerts. It does not take actions. It does not know about your database, your users, or your notification system. It returns a JSON object and stops.

**Your team decides what to do with that data.**

---

## 2. What It Does and Does NOT Do

### It DOES:

| Capability | Details |
|---|---|
| Per-message sentiment analysis | 7 wellbeing-focused categories with confidence and reason — returned for every message in the batch |
| Risk level assessment | 4-tier NDIS risk assessment: `low`, `medium`, `high`, `critical` with specific indicators |
| Communication breakdown detection | Detects when communication has broken down and returns why |
| Outcome classification | `resolved`, `unresolved`, or `pending` |
| Recommended action | Plain-English instruction for coordinators when risk is high/critical or breakdown is detected |
| Conversation context | Every message is analysed in the context of the full batch window |
| Batch analysis | Accepts up to `BATCH_MAX_MESSAGES` messages in one call (default 50, configurable) — one Bedrock call for the entire batch |

### It DOES NOT:

| Not in scope |
|---|
| **Store conversation data** | Your backend / your database |
| **Trigger alerts or notifications** | Your backend — you decide when to alert based on what we return |
| **Decide when to call this API** | Your backend — you call us when your debounce timer or message count fires |
| **Implement debounce or message-count logic** | Your backend — the 2-minute / N-message batching trigger is your responsibility |
| **Track conversation history itself** | You send us the messages each time; we do not persist anything |
| **Know your users** (client IDs, worker IDs, names) | We receive opaque IDs only |
| **Send webhooks or push events** | We only respond to HTTP requests; we never initiate contact |
| **Rate limiting per user or org** | Not implemented — add at your API gateway if needed |

---

## 3. How It Works — Flow Overview

The service exposes one analysis endpoint. Every request must be self-contained — the service is fully stateless.

```
Your Backend — accumulates messages in a local buffer
    │
    │  2-minute idle timer expires
    │  OR buffer reaches BATCH_MAX_MESSAGES messages
    │  (whichever comes first — YOUR backend triggers this)
    │
    │  POST /api/v1/sentiment-batch
    │  {messages: [up to BATCH_MAX_MESSAGES messages], conversation_id, provider_id}
    │
    ▼
Sena Classifier Service
    │
    ├─ Validates request (Pydantic — min 1 message, max BATCH_MAX_MESSAGES)
    ├─ Builds full conversation window prompt with index numbers
    │
    ▼
AWS Bedrock — ONE call for the entire batch (Claude Sonnet 4.5, Sydney ap-southeast-2)
    │
    ├─ Returns JSON with per-message analysis for all messages
    │
    ▼
Parse & validate response
    │
    ├─ Sort by index (model may return out of order)
    ├─ Fallback on count mismatch — every input message always gets a result
    │
    ▼
HTTP 200 — SentimentBatchResponse JSON
    │
    ├─ messages[] — one entry per input message, same order
    │     each entry: role, text, timestamp, sentiment, risk, breakdown,
    │                 outcome, recommended_action
    │
    ▼
Your Backend receives the result
    │
    └─ Your decision: store per-message analysis, surface trends, alert on findings.
```

**Key principle:** The classifier is stateless. The debounce timer and message counter live entirely in your backend. This service just receives what you send and returns analysis.

---

## 4. Project Structure

```
ai-classifier/
│
├── app/                              # Application package
│   │
│   ├── main.py                       # FastAPI app entry point
│   │                                 # Registers routes, CORS, API key middleware
│   │
│   ├── api/
│   │   └── sentiment_batch.py        # HTTP layer — defines POST /api/v1/sentiment-batch
│   │                                 # Validates request, enforces BATCH_MAX_MESSAGES cap,
│   │                                 # calls SentimentBatchService, handles HTTP errors
│   │
│   ├── models/
│   │   └── schemas.py                # All Pydantic models (request + response shapes)
│   │                                 # SentimentBatchRequest, SentimentBatchResponse,
│   │                                 # MessageAnalysis, SentimentResult, RiskAssessment,
│   │                                 # BreakdownAssessment, Message, HealthResponse
│   │
│   ├── services/
│   │   ├── sentiment_batch_service.py# Orchestration for /sentiment-batch
│   │   │                             # Calls BedrockService.analyse_batch(),
│   │   │                             # zips messages with analyses,
│   │   │                             # fills fallback on count mismatch,
│   │   │                             # derives period_start/end
│   │   │
│   │   └── bedrock_service.py        # AWS Bedrock layer
│   │                                 # analyse_batch() — one Bedrock call for all messages
│   │                                 # Parses AI response into BatchOutput dataclass
│   │                                 # Safe fallback on every field — one bad value never
│   │                                 # breaks the whole response
│   │
│   ├── prompts/
│   │   └── sentiment_batch_prompt.py # Prompt for /sentiment-batch
│   │                                 # BATCH_SYSTEM_PROMPT: instructs Claude to return
│   │                                 # full analysis for every message individually
│   │                                 # build_batch_user_prompt(): formats all messages
│   │                                 # with index numbers for ordering
│   │
│   └── core/
│       └── config.py                 # All configuration via pydantic-settings
│                                     # Reads from .env or environment variables
│
├── tests/
│   ├── test_batch_unit.py            # Unit tests — boto3 fully mocked, no AWS needed
│   │                                 # Tests batch parsing, all fallbacks, service
│   │                                 # orchestration, schema validation (1–N message limit)
│   │
│   └── test_batch.py                 # Integration tests — hits real API + Bedrock
│                                     # Requires running server + AWS credentials
│
├── chat.py                           # Interactive CLI tester
│                                     # Simulates the Sena backend debounce logic:
│                                     # accumulates messages, fires /sentiment-batch
│                                     # after --debounce seconds idle or --batch-limit msgs
│
├── pytest.ini                        # Test configuration
│                                     # testpaths = tests, pythonpath = .
│
└── .env                              # Local secrets (not committed to git)
                                      # API_KEY, AWS credentials if not using AWS CLI
```

---

## 5. Internal Data Flow — Request to Response

```
HTTP POST /api/v1/sentiment-batch
{
  "conversation_id": "conv_001",
  "provider_id": "org_abc",
  "messages": [ ...up to BATCH_MAX_MESSAGES Message objects... ]
}
```

---

#### Step 1 — API Key Middleware (`app/main.py`)

Before the request touches any handler, the middleware checks the `X-API-Key` header.

- If `API_KEY` is empty in config → middleware is skipped, request passes through.
- If `API_KEY` is set and the header does not match → `401 Unauthorized` returned immediately.
- If header matches → request continues.

---

#### Step 2 — Route Handler (`app/api/sentiment_batch.py`)

FastAPI routes to `analyse_sentiment_batch()` and validates the body against `SentimentBatchRequest`. Pydantic enforces `len(messages) >= 1`. The handler then checks `len(messages) <= settings.BATCH_MAX_MESSAGES` — exceeding this returns `422` with a message showing the current configured cap.

---

#### Step 3 — Batch Service (`app/services/sentiment_batch_service.py`)

Logs the request, calls `BedrockService.analyse_batch(messages)`, then zips the returned analyses with the original messages to build the final response. Derives `period_start` and `period_end` from message timestamps.

If the model returns fewer analyses than messages, missing entries are filled with a neutral fallback and a warning is logged — the response always contains exactly as many entries as the input.

---

#### Step 4 — Prompt Builder (`app/prompts/sentiment_batch_prompt.py`)

`build_batch_user_prompt()` formats all messages with index numbers:

```
=== CONVERSATION WINDOW (oldest → newest) ===
[0] [2025-06-01 10:00:00 UTC] CLIENT: I need help getting to the bathroom.
[1] [2025-06-01 10:01:00 UTC] SUPPORT WORKER: Wait, I'm busy.
[2] [2025-06-01 10:02:00 UTC] CLIENT: Please, it hurts.

Total messages: 3
Return exactly 3 objects in the 'messages' array (index 0 to 2). Return ONLY the JSON object.
```

The `BATCH_SYSTEM_PROMPT` instructs Claude to return sentiment, risk, breakdown, outcome, and recommended_action for **each individual message** in context of the full window.

---

#### Step 5 — AWS Bedrock Call (`app/services/bedrock_service.py`)

`BedrockService.analyse_batch()` makes **one single Bedrock call** regardless of how many messages are in the batch:

```python
response = self.client.converse(
    modelId="au.anthropic.claude-sonnet-4-5-20250929-v1:0",
    system=[{"text": BATCH_SYSTEM_PROMPT}],
    messages=[{"role": "user", "content": [{"text": user_prompt}]}],
    inferenceConfig={"maxTokens": settings.BEDROCK_MAX_TOKENS, "temperature": settings.BEDROCK_TEMPERATURE},
)
```

---

#### Step 6 — Response Parsing (`app/services/bedrock_service.py`)

`_parse_batch_response()` strips markdown fences, parses JSON, sorts entries by `index` to match input order, then calls per-field parsers with safe fallbacks:

```
Claude raw text
  └─► _parse_batch_response()
        └─► _parse_message_analyses()
              for each message entry (sorted by index):
                ├─► _parse_sentiment_from_key()  — label ∈ 7 values; unknown → "neutral"
                ├─► _parse_risk()                — level fallback to "low"
                ├─► _parse_breakdown()           — clears reasons if detected=false
                ├─► _parse_outcome()             — fallback to "pending"
                └─► _parse_recommended_action()  — null/"null"/"" → None
```

Returns a `BatchOutput` dataclass:

```python
@dataclass
class MessageAnalysisItem:
    sentiment:          SentimentResult
    risk:               RiskAssessment
    breakdown:          BreakdownAssessment
    outcome:            str
    recommended_action: Optional[str]

@dataclass
class BatchOutput:
    message_analyses: list[MessageAnalysisItem]  # ordered 0..N-1
```

---

#### Step 7 — Build Final Response

`SentimentBatchService` zips input messages with `MessageAnalysisItem` entries to produce a `SentimentBatchResponse`. FastAPI serializes it → `HTTP 200`.

---

## 6. Local Setup and Running

### Prerequisites

- Python 3.11+
- AWS credentials configured (see below)
- Access to AWS Bedrock in `ap-southeast-2` (Sydney) with `claude-sonnet-4-5-20250929-v1:0` enabled

### Step 1 — Install dependencies

```bash
cd ai-classifier
pip install -r requirements.txt
```

> If `requirements.txt` is missing, install manually:
> ```bash
> pip install fastapi uvicorn boto3 pydantic pydantic-settings requests pytest
> ```

### Step 2 — Configure AWS credentials

**Option A — Environment variables (recommended for local dev):**
```powershell
# Windows PowerShell
$env:AWS_ACCESS_KEY_ID     = "your-access-key"
$env:AWS_SECRET_ACCESS_KEY = "your-secret-key"
$env:AWS_DEFAULT_REGION    = "ap-southeast-2"
```

```bash
# Linux / macOS
export AWS_ACCESS_KEY_ID=your-access-key
export AWS_SECRET_ACCESS_KEY=your-secret-key
export AWS_DEFAULT_REGION=ap-southeast-2
```

**Option B — AWS credentials file:**
```
~/.aws/credentials
[default]
aws_access_key_id = your-access-key
aws_secret_access_key = your-secret-key
```

**Option C — IAM role (for deployed environments, e.g. ECS, EC2):**  
No credentials needed. Attach an IAM role with `bedrock:InvokeModel` permission.

### Step 3 — Create a `.env` file (optional)

```env
# ai-classifier/.env
DEBUG=false
API_KEY=your-secret-key-here   # leave empty to disable auth during local dev
AWS_REGION=ap-southeast-2
BEDROCK_MODEL_ID=au.anthropic.claude-sonnet-4-5-20250929-v1:0
BEDROCK_MAX_TOKENS=1024
BATCH_MAX_MESSAGES=50
```

### Step 4 — Start the server

```bash
cd ai-classifier
uvicorn app.main:app --reload --port 8000
```

### Step 5 — Verify it is up

```bash
curl http://localhost:8000/health
```

Expected response:
```json
{
  "status": "ok",
  "version": "1.0.0",
  "model": "au.anthropic.claude-sonnet-4-5-20250929-v1:0"
}
```

### Interactive API docs

- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc

---

## 7. API Reference

### POST /api/v1/sentiment-batch

Accepts a batch of messages from a conversation window and returns a full analysis for every individual message. Called by the Sena backend on a 2-minute idle debounce or `BATCH_MAX_MESSAGES` accumulation — whichever fires first.

**The debounce and message-count logic is the Sena backend's responsibility. This endpoint just receives the batch and returns results.**

| Property | Value |
|---|---|
| Method | `POST` |
| Path | `/api/v1/sentiment-batch` |
| Content-Type | `application/json` |
| Auth | `X-API-Key` header (only required if `API_KEY` is configured) |
| Response | `200 OK` — `SentimentBatchResponse` JSON |

#### Request body

```json
{
  "conversation_id": "string",
  "provider_id": "string",
  "messages": [
    {
      "role": "support_worker | client",
      "text": "string",
      "timestamp": "ISO 8601 UTC datetime"
    }
  ],
  "metadata": { "any_key": "any_value" }
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `conversation_id` | string | Yes | Your ID for the conversation thread. Echoed back. |
| `provider_id` | string | Yes | Your organisation/provider ID. Echoed back. |
| `messages` | array | Yes | Ordered oldest → newest. **Minimum 1, maximum `BATCH_MAX_MESSAGES`** (default 50). Outside this range returns `422`. |
| `messages[].role` | string | Yes | `"support_worker"` or `"client"` only. Any other value → `422`. |
| `messages[].text` | string | Yes | Minimum 1 character. |
| `messages[].timestamp` | datetime | Yes | ISO 8601. Example: `"2025-06-01T10:00:00Z"` |
| `metadata` | object | No | Optional extra context. Ignored by the classifier. |

---

### GET /health

Health check. Does not require authentication.

```json
{
  "status": "ok",
  "version": "1.0.0",
  "model": "au.anthropic.claude-sonnet-4-5-20250929-v1:0"
}
```

---

## 8. Full Request and Response Examples

### Example 1 — Normal conversation

**Scenario:** Support worker responds promptly to a client's missed service.

**Request:**
```json
{
  "conversation_id": "conv_20250601_001",
  "provider_id": "org_abc_123",
  "messages": [
    { "role": "client",         "text": "I haven't received my transport support this week.", "timestamp": "2025-06-01T10:03:00Z" },
    { "role": "support_worker", "text": "Sorry about that. I'll check and get back to you today.", "timestamp": "2025-06-01T10:05:00Z" }
  ]
}
```

**Response:**
```json
{
  "conversation_id": "conv_20250601_001",
  "provider_id": "org_abc_123",
  "messages": [
    {
      "role": "client",
      "text": "I haven't received my transport support this week.",
      "timestamp": "2025-06-01T10:03:00Z",
      "sentiment":          { "label": "frustrated_dissatisfied", "confidence": 0.82, "reason": "Client reports a missed support without hostility but expresses unmet expectation." },
      "risk":               { "level": "medium", "indicators": ["support not received"], "reason": "A missed transport support is a service gap that requires follow-up." },
      "breakdown":          { "detected": false, "reasons": [] },
      "outcome":            "unresolved",
      "recommended_action": null
    },
    {
      "role": "support_worker",
      "text": "Sorry about that. I'll check and get back to you today.",
      "timestamp": "2025-06-01T10:05:00Z",
      "sentiment":          { "label": "positive_satisfied", "confidence": 0.88, "reason": "Worker acknowledges the issue and commits to a clear action." },
      "risk":               { "level": "low", "indicators": [], "reason": "Worker is actively addressing the support gap." },
      "breakdown":          { "detected": false, "reasons": [] },
      "outcome":            "pending",
      "recommended_action": null
    }
  ],
  "messages_analysed": 2,
  "period_start": "2025-06-01T10:03:00Z",
  "period_end":   "2025-06-01T10:05:00Z",
  "analysed_at":  "2025-06-01T10:05:12Z"
}
```

---

### Example 2 — Communication breakdown

**Scenario:** Client cannot get a clear answer about plan changes.

**Request:**
```json
{
  "conversation_id": "conv_20250601_002",
  "provider_id": "org_abc_123",
  "messages": [
    { "role": "client",         "text": "Can you explain why my support hours changed?", "timestamp": "2025-06-01T10:07:00Z" },
    { "role": "support_worker", "text": "Please check your plan.",                        "timestamp": "2025-06-01T10:08:00Z" },
    { "role": "client",         "text": "I already did, but I don't understand.",         "timestamp": "2025-06-01T10:09:00Z" },
    { "role": "support_worker", "text": "It's in the documents.",                         "timestamp": "2025-06-01T10:10:00Z" }
  ]
}
```

**Response:**
```json
{
  "conversation_id": "conv_20250601_002",
  "provider_id": "org_abc_123",
  "messages": [
    {
      "role": "client",
      "text": "Can you explain why my support hours changed?",
      "timestamp": "2025-06-01T10:07:00Z",
      "sentiment":          { "label": "confused_uncertain", "confidence": 0.87, "reason": "Client is seeking clarification on a plan change they do not understand." },
      "risk":               { "level": "low", "indicators": [], "reason": "Legitimate question, no immediate concern." },
      "breakdown":          { "detected": false, "reasons": [] },
      "outcome":            "unresolved",
      "recommended_action": null
    },
    {
      "role": "support_worker",
      "text": "Please check your plan.",
      "timestamp": "2025-06-01T10:08:00Z",
      "sentiment":          { "label": "disengaged", "confidence": 0.84, "reason": "Worker deflects without explaining." },
      "risk":               { "level": "medium", "indicators": ["client question not addressed"], "reason": "Worker redirects without answering." },
      "breakdown":          { "detected": true, "reasons": ["Client question unanswered — deflection instead of explanation"] },
      "outcome":            "unresolved",
      "recommended_action": null
    },
    {
      "role": "client",
      "text": "I already did, but I don't understand.",
      "timestamp": "2025-06-01T10:09:00Z",
      "sentiment":          { "label": "frustrated_dissatisfied", "confidence": 0.91, "reason": "Client explicitly states the deflection did not help." },
      "risk":               { "level": "medium", "indicators": ["repeated unanswered request"], "reason": "Client follow-up shows the initial response failed." },
      "breakdown":          { "detected": true, "reasons": ["Repeated clarification needed — worker deflection ineffective"] },
      "outcome":            "unresolved",
      "recommended_action": null
    },
    {
      "role": "support_worker",
      "text": "It's in the documents.",
      "timestamp": "2025-06-01T10:10:00Z",
      "sentiment":          { "label": "disengaged", "confidence": 0.92, "reason": "Second deflection — worker continues to avoid explaining." },
      "risk":               { "level": "medium", "indicators": ["persistent deflection", "unresolved participant question"], "reason": "Failure to explain plan changes is a service quality concern." },
      "breakdown":          { "detected": true, "reasons": ["Participant's question not answered across multiple turns", "Worker deflecting without explanation"] },
      "outcome":            "unresolved",
      "recommended_action": "Review the support hours change with the participant directly and provide a clear explanation."
    }
  ],
  "messages_analysed": 4,
  "period_start": "2025-06-01T10:07:00Z",
  "period_end":   "2025-06-01T10:10:00Z",
  "analysed_at":  "2025-06-01T10:10:08Z"
}
```

---

### Example 3 — High risk / critical conduct

**Scenario:** Client in distress, worker responds abusively.

**Request:**
```json
{
  "conversation_id": "conv_20250601_003",
  "provider_id": "org_abc_123",
  "messages": [
    { "role": "client",         "text": "I need help getting to the bathroom.",                "timestamp": "2025-06-01T10:00:00Z" },
    { "role": "support_worker", "text": "Wait, I'm busy.",                                     "timestamp": "2025-06-01T10:01:00Z" },
    { "role": "client",         "text": "Please, it hurts.",                                   "timestamp": "2025-06-01T10:02:00Z" },
    { "role": "support_worker", "text": "I don't want to deal with you. Just do what I say.", "timestamp": "2025-06-01T10:03:00Z" }
  ]
}
```

**Response:**
```json
{
  "conversation_id": "conv_20250601_003",
  "provider_id": "org_abc_123",
  "messages": [
    {
      "role": "client",
      "text": "I need help getting to the bathroom.",
      "timestamp": "2025-06-01T10:00:00Z",
      "sentiment":          { "label": "engaged",          "confidence": 0.85, "reason": "Client clearly states their need." },
      "risk":               { "level": "low",              "indicators": [], "reason": "Straightforward support request." },
      "breakdown":          { "detected": false, "reasons": [] },
      "outcome":            "pending",
      "recommended_action": null
    },
    {
      "role": "support_worker",
      "text": "Wait, I'm busy.",
      "timestamp": "2025-06-01T10:01:00Z",
      "sentiment":          { "label": "disengaged",       "confidence": 0.90, "reason": "Worker dismisses the client with a single deflective response." },
      "risk":               { "level": "medium",           "indicators": ["client request dismissed"], "reason": "Worker not attending to an expressed need." },
      "breakdown":          { "detected": true, "reasons": ["Client request ignored"] },
      "outcome":            "unresolved",
      "recommended_action": "Follow up to ensure client's immediate need was addressed."
    },
    {
      "role": "client",
      "text": "Please, it hurts.",
      "timestamp": "2025-06-01T10:02:00Z",
      "sentiment":          { "label": "distressed_upset", "confidence": 0.95, "reason": "Client reports pain and expresses urgency." },
      "risk":               { "level": "high",             "indicators": ["client in pain", "worker unresponsive"], "reason": "Client is in physical distress with no support response." },
      "breakdown":          { "detected": true, "reasons": ["Client's urgent need not addressed"] },
      "outcome":            "unresolved",
      "recommended_action": "Escalate to coordinator immediately — client reporting pain with no worker response."
    },
    {
      "role": "support_worker",
      "text": "I don't want to deal with you. Just do what I say.",
      "timestamp": "2025-06-01T10:03:00Z",
      "sentiment":          { "label": "frustrated_dissatisfied", "confidence": 0.93, "reason": "Worker uses dismissive, coercive language toward the client." },
      "risk":               { "level": "critical",         "indicators": ["verbal abuse", "coercive language", "client in pain ignored"], "reason": "Worker's conduct constitutes an NDIS Code of Conduct violation while client is in distress." },
      "breakdown":          { "detected": true, "reasons": ["Worker refuses to address client's needs", "Coercive response to distressed client"] },
      "outcome":            "unresolved",
      "recommended_action": "File incident report with NDIS Commission. Escalate to coordinator for immediate review."
    }
  ],
  "messages_analysed": 4,
  "period_start": "2025-06-01T10:00:00Z",
  "period_end":   "2025-06-01T10:03:00Z",
  "analysed_at":  "2025-06-01T10:05:12Z"
}
```

---

## 9. Field Reference

### Response — top level

| Field | Type | Always present | Description |
|---|---|---|---|
| `conversation_id` | string | Yes | Echoed from request |
| `provider_id` | string | Yes | Echoed from request |
| `messages` | array | Yes | One entry per input message, in the same order |
| `messages_analysed` | integer | Yes | Count of messages in the batch |
| `period_start` | ISO datetime | Yes | Timestamp of the earliest message in the batch |
| `period_end` | ISO datetime | Yes | Timestamp of the latest message in the batch |
| `analysed_at` | ISO datetime | Yes | UTC timestamp of when the batch analysis ran |

### `messages[]` — per-message analysis

| Field | Type | Description |
|---|---|---|
| `role` | string | `"support_worker"` or `"client"` — preserved from input |
| `text` | string | Message content — preserved from input |
| `timestamp` | ISO datetime | Preserved from input |
| `sentiment` | object | Sentiment for this individual message |
| `risk` | object | Risk assessment for this message in context |
| `breakdown` | object | Whether this message contributes to a breakdown |
| `outcome` | string | Outcome state as of this message |
| `recommended_action` | string or null | Action required, or null |

### `sentiment`

| Field | Type | Values |
|---|---|---|
| `label` | string | `positive_satisfied` / `neutral` / `frustrated_dissatisfied` / `distressed_upset` / `confused_uncertain` / `engaged` / `disengaged` |
| `confidence` | float | 0.0 – 1.0 |
| `reason` | string | Specific language cited from the message |

### `risk`

| Field | Type | Values |
|---|---|---|
| `level` | string | `low` / `medium` / `high` / `critical` |
| `indicators` | string[] | Specific NDIS risk indicators detected. Empty for `low` with no concerns. |
| `reason` | string | Risk assessment summary |

**Risk level definitions:**

| Level | Meaning |
|---|---|
| `low` | No safeguarding concern. Normal service delivery. |
| `medium` | Service quality concern, mild frustration, or unresolved issue. Worth monitoring. |
| `high` | Participant distress, wellbeing at risk, supports not being provided. Requires coordinator attention. |
| `critical` | Immediate safety concern — self-harm, abuse, emergency medical, or similar. Requires urgent response. |

### `breakdown`

| Field | Type | Description |
|---|---|---|
| `detected` | boolean | `true` if communication breakdown was detected |
| `reasons` | string[] | Which breakdown criteria were matched. Empty when `detected=false`. |

### `outcome`

| Value | Meaning |
|---|---|
| `resolved` | The concern or question was addressed at this point |
| `unresolved` | The issue remains open or was not addressed |
| `pending` | Awaiting action (worker committed to follow-up) |

---

## 10. Integration Guide — Backend Team

### When to call

Your backend must implement the batching trigger. Accumulate messages in a local buffer per conversation, then flush to `/sentiment-batch` when either condition fires:

```python
# Pseudocode — the debounce/limit logic lives entirely in YOUR backend

class ConversationBatchBuffer:
    DEBOUNCE_SECONDS = 120         # 2 minutes
    MESSAGE_LIMIT    = 50          # match your BATCH_MAX_MESSAGES config

    def __init__(self, conversation_id, provider_id):
        self.conversation_id = conversation_id
        self.provider_id     = provider_id
        self.messages        = []
        self.last_message_at = None

    def add(self, role, text, timestamp):
        self.messages.append({"role": role, "text": text, "timestamp": timestamp})
        self.last_message_at = now()

        # Trigger 1: message limit reached
        if len(self.messages) >= self.MESSAGE_LIMIT:
            self.flush(trigger="message limit")

    def on_timer_tick(self):
        # Trigger 2: idle for 2 minutes
        if self.messages and (now() - self.last_message_at) >= self.DEBOUNCE_SECONDS:
            self.flush(trigger="idle debounce")

    def flush(self, trigger):
        if not self.messages:
            return
        msgs_to_send  = list(self.messages)
        self.messages = []

        payload = {
            "conversation_id": self.conversation_id,
            "provider_id":     self.provider_id,
            "messages":        msgs_to_send,
        }
        response = requests.post(
            url="http://your-classifier-url/api/v1/sentiment-batch",
            json=payload,
            headers={"X-API-Key": CLASSIFIER_API_KEY},
            timeout=60,
        )
        response.raise_for_status()
        self.store_batch_result(response.json())
```

**Key rules:**
- One buffer per active conversation
- Both triggers must be checked: idle time AND message count
- Flush and reset the buffer when either fires
- `MESSAGE_LIMIT` here must match `BATCH_MAX_MESSAGES` in the classifier's `.env`

---

### What to do with the response

```python
batch_result = flush_batch(buffer)

for msg_analysis in batch_result["messages"]:
    stored_message = find_message_by_timestamp(msg_analysis["timestamp"])
    stored_message.sentiment = msg_analysis["sentiment"]["label"]
    stored_message.risk      = msg_analysis["risk"]["level"]
    stored_message.outcome   = msg_analysis["outcome"]
    stored_message.save()

    if msg_analysis["recommended_action"]:
        flag_for_coordinator_review(stored_message, msg_analysis["recommended_action"])

    if msg_analysis["risk"]["level"] in ("high", "critical"):
        alert_coordinator(stored_message)
```

---

### Timeout and retry

| Endpoint | Recommended timeout |
|---|---|
| `/sentiment-batch` | 60 seconds |

Retry **once** with exponential backoff on `500` errors. Do not retry `422` errors — those indicate a malformed request or exceeded cap.

### Production deployment checklist

1. **CORS origins** — change `allow_origins=["*"]` in `app/main.py` to your backend's origin(s).
2. **`API_KEY`** — set a strong secret in `.env` or environment variables.
3. **AWS credentials** — use an IAM role with `bedrock:InvokeModel` in Sydney. Do not use long-lived keys.
4. **AWS region** — keep as `ap-southeast-2` for Australian data residency (NDIS requirement).
5. **`BATCH_MAX_MESSAGES`** — set to match your backend's buffer limit. Also increase `BEDROCK_MAX_TOKENS` if raising above 50.

---

## 11. Integration Guide — Frontend Team

The frontend does not call this API directly. The backend analyses conversation windows and stores results, then exposes them through your own API.

### Suggested data to surface in the UI

#### Risk badge on a conversation

| `risk.level` | Suggested UI |
|---|---|
| `low` | No badge or subtle green indicator |
| `medium` | Yellow/amber badge — "Attention" |
| `high` | Orange badge — "Review Required" |
| `critical` | Red badge with alert — "Urgent" |

#### Per-message sentiment indicator

| Label | Suggested icon / colour |
|---|---|
| `positive_satisfied` | Green, check mark |
| `neutral` | Grey |
| `frustrated_dissatisfied` | Amber, caution icon |
| `distressed_upset` | Red, warning icon |
| `confused_uncertain` | Blue, question mark |
| `engaged` | Green, active indicator |
| `disengaged` | Grey, low-activity indicator |

#### Coordinator alert panel

When `recommended_action` is non-null on any message:
```
⚠ Action Required
Escalate to coordinator for immediate review of support provision.
```

#### Breakdown flag

When `breakdown.detected = true` on any message:
```
⚠ Communication Breakdown Detected
• Participant's question not answered across multiple turns
• Worker deflecting without explanation
```

#### Outcome chip per message

- `resolved` — Green chip
- `pending` — Yellow chip
- `unresolved` — Red chip

#### Hover tooltip using `reason` fields

Each `sentiment.reason`, `risk.reason`, and `breakdown.reasons` contains plain-English explanation. Surface these in tooltips for coordinators.

---

## 12. Authentication and Security

### API key

- **Key:** `API_KEY` in `.env`
- **Header:** `X-API-Key: your-key-here`
- **No key configured:** Auth is disabled — all requests are accepted. Safe for local dev, not for production.

```bash
curl -X POST http://localhost:8000/api/v1/sentiment-batch \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-secret-key" \
  -d '{...}'
```

If the key is wrong or missing when auth is enabled:
```json
{ "detail": "Invalid or missing API key" }
```
HTTP status: `401 Unauthorized`

### What data leaves the service

Every API call sends conversation text to **AWS Bedrock (Sydney region)**:

```
Your message text → Sena Classifier (your infra) → AWS Bedrock ap-southeast-2 (Sydney)
```

AWS Bedrock does not train on your data by default. Confirm your Bedrock data privacy settings and NDIS data handling obligations with your compliance team.

---

## 13. Configuration Reference

All configuration is in `app/core/config.py` and can be overridden via `.env` or environment variables.

| Variable | Default | Description |
|---|---|---|
| `APP_NAME` | `"Sena Communication Log Classifier"` | Service name shown in health check and docs |
| `APP_VERSION` | `"1.0.0"` | Version string |
| `DEBUG` | `false` | Enables debug-level logging |
| `API_KEY` | `""` (empty = auth disabled) | Secret key for `X-API-Key` header |
| `AWS_REGION` | `ap-southeast-2` | AWS Bedrock region — Sydney for NDIS data residency |
| `BEDROCK_MODEL_ID` | `au.anthropic.claude-sonnet-4-5-20250929-v1:0` | Claude model used |
| `BEDROCK_MAX_TOKENS` | `1024` | Max tokens in model response — increase if raising `BATCH_MAX_MESSAGES` above 50 |
| `BEDROCK_TEMPERATURE` | `0.1` | Low temperature for consistent, deterministic output |
| `BATCH_MAX_MESSAGES` | `50` | Maximum messages per `/sentiment-batch` call. Set in `.env` to change without code edits. |

---

## 14. Error Handling

| HTTP Status | Meaning | What to do |
|---|---|---|
| `200 OK` | Success | Use the response body |
| `401 Unauthorized` | Missing or wrong API key | Check `X-API-Key` header |
| `422 Unprocessable Entity` | Request body validation failed | Check the `detail` field — lists which fields failed and why |
| `500 Internal Server Error` | Bedrock API error or model parsing failure | Log the `detail` field. Retry once. If persistent, check AWS Bedrock status. |

### 422 example — empty messages list

```json
{
  "detail": [
    {
      "type": "too_short",
      "loc": ["body", "messages"],
      "msg": "List should have at least 1 item after validation, not 0"
    }
  ]
}
```

### 422 example — exceeds BATCH_MAX_MESSAGES

```json
{
  "detail": "Too many messages: received 51, maximum allowed is 50 (BATCH_MAX_MESSAGES)."
}
```

### 500 example — Bedrock error

```json
{
  "detail": "Bedrock API error: ThrottlingException"
}
```

---

## 15. Running Tests

### Unit tests (no AWS, no network)

```bash
cd ai-classifier
pytest tests/test_batch_unit.py -v
```

Covers batch response parsing, index ordering, all 7 sentiment labels, all fallbacks (unknown labels, malformed JSON, count mismatch), service orchestration (period_start/end, role/text preservation), and schema validation (1–N message limit).

### Integration tests (requires live server + AWS)

```bash
# Terminal 1 — start server
cd ai-classifier
uvicorn app.main:app --reload --port 8000

# Terminal 2
cd ai-classifier
pytest tests/test_batch.py -v
```

Covers structural assertions, scenario tests (normal conversation, inappropriate behaviour, distressed client, breakdown, resolved outcome), and all 422 validation error cases.

### Run all tests

```bash
cd ai-classifier
pytest -v
```

### Run a specific group

```bash
pytest tests/test_batch_unit.py -v -k "parsing"
pytest tests/test_batch.py -v -k "validation"
pytest tests/test_batch.py -v -k "scenarios"
```

### Against a deployed URL

```bash
$env:BASE_URL = "https://your-deployed-url.com"
$env:API_KEY  = "your-key"
pytest tests/test_batch.py -v
```

---

## 16. Interactive Conversation Tester

`chat.py` is a local CLI tool that simulates the full Sena backend integration — the debounce buffer and batch trigger — so you can test the endpoint without writing scripts.

```bash
cd ai-classifier

# Quick testing — 20-second idle timer, batch after 5 messages:
python chat.py --debounce 20 --batch-limit 5

# Production-accurate — 2-minute timer, 50-message limit:
python chat.py --debounce 120 --batch-limit 50

# Against a deployed URL:
python chat.py --url https://your-deployed-classifier.com --key your-api-key
```

### How it works

When you type a message it is added to the local buffer — no result is shown immediately. The batch result appears only when a trigger fires:

```
Role [sw/c]: c
Message (Client): I need help getting to the bathroom.
  [batch buffer: 1/5 msgs]

Role [sw/c]: sw
Message (Support Worker): Wait, I'm busy.
  [batch buffer: 2/5 msgs]

  ► 5-message limit reached — sending batch...

════════════════════════════════════════════════════════════════
  BATCH ANALYSIS  —  trigger: 5-message limit
  5 messages  |  10:00:00 → 10:04:00
════════════════════════════════════════════════════════════════

  [0] CLIENT         "I need help getting to the bathroom."
      Sentiment : 👍 engaged              (85%)
      Risk      : LOW
      Breakdown : No
      Outcome   : pending

  [1] SUPPORT WORKER "Wait, I'm busy."
      Sentiment : 😶 disengaged           (90%)
      Risk      : MEDIUM  client request dismissed
      Breakdown : YES  Client request ignored
      Outcome   : unresolved
      ⚠ Action  : Follow up to ensure client's need was addressed
════════════════════════════════════════════════════════════════
```

If no new messages arrive for `--debounce` seconds, the timer fires automatically.

### Commands

| Command | What it does |
|---|---|
| `sw` | Next message is from the support worker |
| `c` | Next message is from the client |
| `batch` or `b` | Manually force-flush the buffer immediately |
| `history` | Show all messages typed so far |
| `reset` | Flushes the buffer, then starts a fresh conversation |
| `quit` | Flushes the buffer before exiting |

---

## 17. Placeholders and Future Work

The following capabilities are identified in the project scope but **not yet implemented**.

---

### PLACEHOLDER — Exception-Based Alert Triggers

Instead of returning data on every call (current behaviour), the service would additionally fire webhook callbacks or events only when predefined thresholds are crossed — for example risk reaching `critical`, or `breakdown.detected` becoming `true` across consecutive messages.

**Current state:** Not implemented. Your backend can implement this alerting logic by inspecting the fields returned in the batch response.

**When available:** `[ TO BE DETERMINED ]`

---

### PLACEHOLDER — Rate Limiting

Per-provider or per-API-key rate limiting is not implemented. Add at your API gateway (e.g. AWS API Gateway, nginx, Cloudflare) if needed before production deployment.

---

### PLACEHOLDER — Audit Logging

The service logs events to standard output via Python `logging`. There is no built-in audit trail or log persistence. Wire your deployment to a log aggregator (CloudWatch, Datadog, ELK) to retain analysis history for audit purposes.

---

*End of documentation.*
