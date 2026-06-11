# Sena AI Communication Classifier — Integration Documentation

**Version:** 1.0.0  
**Last updated:** 2026-06-10  
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
   - [POST /api/v1/classify](#post-apiv1classify)
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
8. [Integration Guide — Backend Team](#8-integration-guide--backend-team)
9. [Integration Guide — Frontend Team](#9-integration-guide--frontend-team)
10. [Authentication and Security](#10-authentication-and-security)
11. [Configuration Reference](#11-configuration-reference)
12. [Error Handling](#12-error-handling)
13. [Running Tests](#13-running-tests)
14. [Interactive Conversation Tester](#14-interactive-conversation-tester)
15. [Placeholders and Future Work](#15-placeholders-and-future-work)

---

## 1. What This Service Is

This is a **single-purpose AI classification microservice** for the Sena platform.

Its only job is: **given a message in a support worker ↔ client conversation, analyse it and return structured classification data.**

It does not store data. It does not trigger alerts. It does not take actions. It does not know about your database, your users, or your notification system. It returns a JSON object and stops.

**Your team decides what to do with that data.**

---

## 2. What It Does and Does NOT Do

### It DOES:

| Capability | Details |
|---|---|
| NDIS compliance classification | Labels each message as `emergency`, `inappropriate`, or `normal` with a confidence score and reason |
| Participant sentiment analysis | 7 wellbeing-focused categories (not generic emotions) with confidence and reason |
| Risk level assessment | 4-tier NDIS risk assessment: `low`, `medium`, `high`, `critical` with specific indicators |
| Communication breakdown detection | Detects when communication has broken down and returns why |
| Outcome classification | `resolved`, `unresolved`, or `pending` |
| Recommended action | Plain-English instruction for coordinators when risk is high/critical or breakdown is detected |
| Conversation context | Accepts prior message history (up to last 5 messages) so classification is context-aware |
| Multi-label classification | A single message can be both `emergency` AND `inappropriate` simultaneously |

### It DOES NOT:

| Not in scope |
|---|---|
| **Store conversation data** | Your backend / your database |
| **Trigger alerts or notifications** | Your backend — you decide when to alert based on what we return |
| **Decide when to call this API** | Your backend — you call us when a message is sent |
| **Track conversation history itself** | You send us the history each time; we do not persist it |
| **Know your users** (client IDs, worker IDs, names) | We receive opaque IDs only; matching to real users is your concern |
| **Send webhooks or push events** | We only respond to HTTP requests; we never initiate contact |
| **Rate limiting per user or org** | Not implemented — add at your API gateway if needed |
| **Full conversation analysis** (trends, summaries) | As discussed in the meeting (with Varun), not in the current scope |
| **Exception-based alerting** (fire when threshold crossed) | Not in scope |

---

## 3. How It Works — Flow Overview

```
Your Backend
    │
    │  POST /api/v1/classify
    │  {current_message, history, conversation_id, provider_id}
    │
    ▼
Sena Classifier Service
    │
    ├─ Validates request (Pydantic)
    ├─ Trims history to last 5 messages
    ├─ Builds structured prompt
    │
    ▼
AWS Bedrock (Claude Sonnet 4.5 — Sydney ap-southeast-2)
    │
    ├─ Returns JSON with 6 classification sections
    │
    ▼
Parse & validate response
    │
    ▼
HTTP 200 — ClassificationResponse JSON
    │
    ▼
Your Backend receives the result
    │
    ├─ Your decision: store it, alert on it, display it.
```

**Key principle:** This service is stateless. Every request must be self-contained. If you want context-aware classification, include the conversation history in the request body. Nothing is stored on our side between calls.

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
│   │   └── classify.py               # HTTP layer — defines POST /api/v1/classify
│   │                                 # Validates request, calls ClassificationService,
│   │                                 # handles HTTP errors
│   │
│   ├── models/
│   │   └── schemas.py                # All Pydantic models (request + response shapes)
│   │                                 # ClassificationRequest, ClassificationResponse,
│   │                                 # SentimentResult, RiskAssessment, BreakdownAssessment
│   │                                 # Message, ClassificationResult, HealthResponse
│   │
│   ├── services/
│   │   ├── classification_service.py # Orchestration layer
│   │   │                             # Trims history, calls BedrockService,
│   │   │                             # determines is_uncertain, builds final response
│   │   │
│   │   └── bedrock_service.py        # AWS Bedrock layer
│   │                                 # Calls Claude via boto3 converse API
│   │                                 # Parses the AI response into BedrockOutput dataclass
│   │                                 # Safe fallback on every section — one bad field
│   │                                 # never breaks the whole response
│   │
│   ├── prompts/
│   │   └── classification_prompt.py  # Prompt engineering
│   │                                 # SYSTEM_PROMPT: full instruction set for Claude
│   │                                 # build_user_prompt(): formats conversation
│   │                                 # history + current message into the user turn
│   │
│   └── core/
│       └── config.py                 # All configuration via pydantic-settings
│                                     # Reads from .env or environment variables
│
├── tests/
│   ├── test_unit.py                  # Offline unit tests — boto3 fully mocked
│   │                                 # Tests every parser, all labels, all edge cases
│   │                                 # No AWS credentials needed
│   │
│   └── test_classify.py              # Live integration tests — hits real API + Bedrock
│                                     # Requires running server + AWS credentials
│
├── chat.py                           # Interactive CLI tester
│                                     # Lets you hold a real conversation and see
│                                     # full analysis output per turn
│
├── pytest.ini                        # Test configuration
│                                     # testpaths = tests, pythonpath = .
│
└── .env                              # Local secrets (not committed to git)
                                      # API_KEY, AWS credentials if not using AWS CLI
```

---

## 5. Internal Data Flow — Request to Response

This section explains exactly what happens inside the service from the moment an HTTP request arrives to the moment a response is sent back. Every file and function involved is named.

### Step-by-step walkthrough

```
HTTP POST /api/v1/classify
{
  "conversation_id": "conv_001",
  "provider_id": "org_abc",
  "current_message": { "role": "client", "text": "...", "timestamp": "..." },
  "history": [ ... ]
}
```

---

#### Step 1 — API Key Middleware (`app/main.py`)

Before the request touches any handler, the middleware in `main.py` checks the `X-API-Key` header.

- If `API_KEY` is empty in config → middleware is skipped, request passes through.
- If `API_KEY` is set and the header does not match → `401 Unauthorized` returned immediately.
- If header matches → request continues.

```
Request
  └─► api_key_middleware()   [app/main.py]
        ├─ key matches or auth disabled → continue
        └─ key missing/wrong → HTTP 401 (stops here)
```

---

#### Step 2 — Route Handler (`app/api/classify.py`)

FastAPI routes the `POST /api/v1/classify` request to `classify_communication()`.

FastAPI automatically parses and **validates the JSON body** against the `ClassificationRequest` Pydantic model (`app/models/schemas.py`). If any required field is missing or the wrong type, FastAPI returns `422 Unprocessable Entity` before the handler function even runs.

If validation passes, the handler calls `ClassificationService.classify(request)`.

```
Request body
  └─► Pydantic validation against ClassificationRequest   [app/models/schemas.py]
        ├─ invalid → HTTP 422 (stops here, no AI call made)
        └─ valid → ClassificationService.classify(request)
```

**What `ClassificationRequest` expects:**

| Field | Validated as |
|---|---|
| `conversation_id` | non-empty string |
| `provider_id` | non-empty string |
| `current_message.role` | exactly `"support_worker"` or `"client"` |
| `current_message.text` | string, minimum 1 character |
| `current_message.timestamp` | valid ISO 8601 datetime |
| `history[]` | optional, (oldest → newest) array of `Message` objects (same rules as `current_message`) |
| `metadata` | optional, any key-value dict |

---

#### Step 3 — Classification Service (`app/services/classification_service.py`)

`ClassificationService.classify()` does three things:

**3a. Trim history**

Only the last `N` messages from history are kept (default: 5, configurable via `CONVERSATION_HISTORY_LIMIT`). This prevents the prompt from growing unbounded in long conversations.

```python
trimmed_history = request.history[-settings.CONVERSATION_HISTORY_LIMIT:]
```

**3b. Call Bedrock**

Hands `current_message` and `trimmed_history` to `BedrockService.classify()`. Gets back a `BedrockOutput` dataclass (all parsed fields).

**3c. Determine uncertainty**

Checks if every classification confidence score is below `CONFIDENCE_THRESHOLD` (default: 0.5). If yes, `is_uncertain = True`.

```
ClassificationService.classify()
  ├─ trim history to last 5 messages
  ├─ call BedrockService.classify(current_message, trimmed_history)
  │     └─ returns BedrockOutput
  ├─ is_uncertain = all(c.confidence < 0.5 for c in output.classifications)
  └─ build ClassificationResponse from BedrockOutput + request fields
```

---

#### Step 4 — Prompt Builder (`app/prompts/classification_prompt.py`)

`BedrockService` calls `build_user_prompt()` before making the Bedrock call.

This formats the conversation into plain text that Claude can read:

```
=== CONVERSATION HISTORY (oldest → newest) ===
[2025-06-01 10:07:00 UTC] CLIENT: Can you explain why my support hours changed?
[2025-06-01 10:08:00 UTC] SUPPORT WORKER: Please check your plan.
[2025-06-01 10:09:00 UTC] CLIENT: I already did, but I don't understand.

=== CURRENT MESSAGE (classify this in context of history above) ===
[2025-06-01 10:10:00 UTC] SUPPORT WORKER: It's in the documents.

Analyse the current message using all five sections. Return ONLY the JSON object.
```

The `SYSTEM_PROMPT` (also in this file) contains the full instruction set: all 5 analysis sections (compliance labels, sentiment, risk, breakdown, outcome), their allowed values, their rules, and the exact JSON output template Claude must follow.

```
build_user_prompt(current_message, trimmed_history)
  └─ returns formatted string:
       - "CONVERSATION HISTORY" block (if history exists)
       - "CURRENT MESSAGE" block
       - closing instruction

SYSTEM_PROMPT (constant)
  └─ 5 sections of instruction + JSON output template
```

---

#### Step 5 — AWS Bedrock Call (`app/services/bedrock_service.py`)

`BedrockService.classify()` calls `boto3` with the `converse` API:

```python
response = self.client.converse(
    modelId="au.anthropic.claude-sonnet-4-5-20250929-v1:0",
    system=[{"text": SYSTEM_PROMPT}],
    messages=[{"role": "user", "content": [{"text": user_prompt}]}],
    inferenceConfig={
        "maxTokens": 1024,
        "temperature": 0.1,   # low = deterministic, consistent output
    },
)
```

Claude receives:
- **System role:** the full classification instruction set
- **User role:** the formatted conversation text

Claude returns a single JSON object as plain text (no markdown, instructed by the prompt).

```
boto3.client("bedrock-runtime").converse(...)
  ├─ network call to AWS Bedrock ap-southeast-2
  ├─ Claude processes: SYSTEM_PROMPT + formatted conversation
  └─ returns raw text: a JSON string
```

**If Bedrock fails** (throttling, network error, access denied), a `RuntimeError` is raised, caught by the API layer, and returned as HTTP 500.

---

#### Step 6 — Response Parsing (`app/services/bedrock_service.py`)

`_parse_response()` takes Claude's raw text and produces a `BedrockOutput` dataclass.

It strips any accidental markdown fences (` ```json ... ``` `), parses the JSON, then calls a dedicated parser for each of the 6 sections. **Each parser is independent with a safe fallback** — a bad value in one section does not crash the others.

```
Claude raw text (JSON string)
  └─► _parse_response()
        ├─ strip markdown fences if present
        ├─ json.loads() → dict
        │     └─ JSONDecodeError → raises ValueError → HTTP 500
        │
        ├─► _parse_classifications(data)
        │     validates label ∈ {emergency, inappropriate, normal}
        │     unknown label → skipped with warning
        │     no valid labels → raises ValueError → HTTP 500
        │
        ├─► _parse_sentiment(data)
        │     validates label ∈ 7 allowed values
        │     unknown label → defaults to "neutral" (no crash)
        │
        ├─► _parse_risk(data)
        │     validates level ∈ {low, medium, high, critical}
        │     unknown level → defaults to "low" (no crash)
        │
        ├─► _parse_breakdown(data)
        │     detected: bool coercion, reasons: list or empty
        │
        ├─► _parse_outcome(data)
        │     validates ∈ {resolved, unresolved, pending}
        │     unknown → defaults to "pending" (no crash)
        │
        └─► _parse_recommended_action(data)
              null / "null" / "" / "none" → Python None
              anything else → string
```

Returns a `BedrockOutput` dataclass:

```python
@dataclass
class BedrockOutput:
    classifications: list[ClassificationResult]
    sentiment:       SentimentResult
    risk:            RiskAssessment
    breakdown:       BreakdownAssessment
    outcome:         str
    recommended_action: Optional[str]
```

---

#### Step 7 — Build Final Response (`app/services/classification_service.py`)

`ClassificationService` maps `BedrockOutput` fields + original request fields into a `ClassificationResponse` Pydantic model:

```python
return ClassificationResponse(
    conversation_id    = request.conversation_id,
    provider_id        = request.provider_id,
    is_uncertain       = is_uncertain,           # computed in step 3c
    classifications    = output.classifications,
    sentiment          = output.sentiment,
    risk               = output.risk,
    breakdown          = output.breakdown,
    outcome            = output.outcome,
    recommended_action = output.recommended_action,
    messages_analysed  = len(trimmed_history) + 1,
    analysed_at        = datetime.utcnow(),
)
```

---

#### Step 8 — HTTP Response (`app/api/classify.py`)

FastAPI serializes `ClassificationResponse` to JSON automatically (Pydantic handles this) and returns:

```
HTTP 200 OK
Content-Type: application/json

{
  "conversation_id": "conv_001",
  "provider_id": "org_abc",
  "is_uncertain": false,
  "classifications": [...],
  "sentiment": {...},
  "risk": {...},
  "breakdown": {...},
  "outcome": "...",
  "recommended_action": "..." | null,
  "messages_analysed": 2,
  "analysed_at": "2025-06-01T10:10:01"
}
```

---

### Complete flow — one-page summary

```
Caller
  │
  │  POST /api/v1/classify  {conversation_id, provider_id, current_message, history}
  │
  ▼
app/main.py — api_key_middleware
  ├─ no key configured → pass through
  ├─ wrong key → HTTP 401 ◄── stops here
  └─ correct key → continue
  │
  ▼
app/api/classify.py — classify_communication()
  └─ FastAPI validates JSON body (Pydantic ClassificationRequest)
       ├─ invalid → HTTP 422 ◄── stops here
       └─ valid → continue
  │
  ▼
app/services/classification_service.py — ClassificationService.classify()
  ├─ trim history → last 5 messages max
  ├─ call BedrockService.classify()
  │     │
  │     ├─ app/prompts/classification_prompt.py
  │     │     build_user_prompt()  → formats conversation as text
  │     │     SYSTEM_PROMPT        → 5-section instruction set for Claude
  │     │
  │     ├─ boto3 → AWS Bedrock ap-southeast-2
  │     │     Claude Sonnet 4.5  (temperature=0.1, maxTokens=1024)
  │     │     ├─ Bedrock error → RuntimeError → HTTP 500 ◄── stops here
  │     │     └─ returns raw JSON text
  │     │
  │     └─ _parse_response()
  │           parse JSON → _parse_classifications()
  │                      → _parse_sentiment()
  │                      → _parse_risk()
  │                      → _parse_breakdown()
  │                      → _parse_outcome()
  │                      → _parse_recommended_action()
  │           └─ returns BedrockOutput dataclass
  │
  ├─ compute is_uncertain (all classification confidence < 0.5?)
  └─ build ClassificationResponse
  │
  ▼
app/api/classify.py — FastAPI serializes ClassificationResponse → JSON
  │
  ▼
HTTP 200 OK — response body returned to caller
```

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

The service uses the standard AWS credential chain. Any of the following work:

**Option A — Environment variables (recommended for local dev):**
```bash
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
CONVERSATION_HISTORY_LIMIT=5
CONFIDENCE_THRESHOLD=0.5
```

If `.env` is absent, defaults from `app/core/config.py` are used. Auth is **disabled** when `API_KEY` is empty.

### Step 4 — Start the server

```bash
cd ai-classifier
uvicorn app.main:app --reload --port 8000
```

The service is now running at `http://localhost:8000`.

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

Open in browser while the server is running:

- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc

---

## 7. API Reference

### POST /api/v1/classify

Classifies a single message in context of its conversation history.

| Property | Value |
|---|---|
| Method | `POST` |
| Path | `/api/v1/classify` |
| Content-Type | `application/json` |
| Auth | `X-API-Key` header (only required if `API_KEY` is configured) |
| Response | `200 OK` — JSON classification result |

#### Request body

```json
{
  "conversation_id": "string",
  "provider_id": "string",
  "current_message": {
    "role": "support_worker | client",
    "text": "string",
    "timestamp": "ISO 8601 UTC datetime"
  },
  "history": [
    {
      "role": "support_worker | client",
      "text": "string",
      "timestamp": "ISO 8601 UTC datetime"
    }
  ],
  "metadata": {
    "any_key": "any_value"
  }
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `conversation_id` | string | Yes | Your ID for the conversation thread. Echoed back in the response. |
| `provider_id` | string | Yes | Your organisation/provider ID. Echoed back. Used for scoping — never mixed. |
| `current_message` | object | Yes | The message that just arrived — this is what gets classified. |
| `current_message.role` | string | Yes | `"support_worker"` or `"client"` only. |
| `current_message.text` | string | Yes | Minimum 1 character. |
| `current_message.timestamp` | datetime | Yes | ISO 8601 format. Example: `"2025-06-01T10:05:00Z"` |
| `history` | array | No | Prior messages, oldest first. Up to last 5 are used. |
| `metadata` | object | No | Pass anything extra (shift ID, client ID, worker ID). We echo nothing back, but it can be useful for your logging. |

---

### GET /health  {#get-health}

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

### Example 1 — Normal, Low Risk

**Scenario:** Client reports a missed service. Worker responds promptly.

**Request:**
```json
{
  "conversation_id": "conv_20250601_001",
  "provider_id": "org_abc_123",
  "current_message": {
    "role": "support_worker",
    "text": "Sorry about that. I'll check and get back to you today.",
    "timestamp": "2025-06-01T10:05:00Z"
  },
  "history": [
    {
      "role": "client",
      "text": "I haven't received my transport support this week.",
      "timestamp": "2025-06-01T10:03:00Z"
    }
  ]
}
```

**Response:**
```json
{
  "conversation_id": "conv_20250601_001",
  "provider_id": "org_abc_123",
  "is_uncertain": false,
  "classifications": [
    {
      "label": "normal",
      "confidence": 0.97,
      "reason": "Support worker acknowledges the issue and commits to follow-up action."
    }
  ],
  "sentiment": {
    "label": "positive_satisfied",
    "confidence": 0.88,
    "reason": "Worker's response is reassuring and action-oriented."
  },
  "risk": {
    "level": "low",
    "indicators": [],
    "reason": "Worker is actively addressing the support gap. No safety concern detected."
  },
  "breakdown": {
    "detected": false,
    "reasons": []
  },
  "outcome": "resolved",
  "recommended_action": null,
  "messages_analysed": 2,
  "analysed_at": "2025-06-01T10:05:01Z"
}
```

---

### Example 2 — Communication Breakdown

**Scenario:** Participant cannot get a clear answer about their plan changes.

**Request:**
```json
{
  "conversation_id": "conv_20250601_002",
  "provider_id": "org_abc_123",
  "current_message": {
    "role": "support_worker",
    "text": "It's in the documents.",
    "timestamp": "2025-06-01T10:10:00Z"
  },
  "history": [
    {
      "role": "client",
      "text": "Can you explain why my support hours changed?",
      "timestamp": "2025-06-01T10:07:00Z"
    },
    {
      "role": "support_worker",
      "text": "Please check your plan.",
      "timestamp": "2025-06-01T10:08:00Z"
    },
    {
      "role": "client",
      "text": "I already did, but I don't understand.",
      "timestamp": "2025-06-01T10:09:00Z"
    }
  ]
}
```

**Response:**
```json
{
  "conversation_id": "conv_20250601_002",
  "provider_id": "org_abc_123",
  "is_uncertain": false,
  "classifications": [
    {
      "label": "normal",
      "confidence": 0.72,
      "reason": "No abuse or emergency — but support quality is poor."
    }
  ],
  "sentiment": {
    "label": "frustrated_dissatisfied",
    "confidence": 0.91,
    "reason": "Client has explicitly said they do not understand and their question has not been answered."
  },
  "risk": {
    "level": "medium",
    "indicators": ["Participant's legitimate question left unresolved", "Repeated deflection by worker"],
    "reason": "Failure to explain plan changes is a service quality concern that could escalate."
  },
  "breakdown": {
    "detected": true,
    "reasons": [
      "Participant's question not adequately addressed across multiple turns",
      "Worker deflecting without explanation"
    ]
  },
  "outcome": "unresolved",
  "recommended_action": "Review the support hours change with the participant directly and provide a clear explanation.",
  "messages_analysed": 4,
  "analysed_at": "2025-06-01T10:10:01Z"
}
```

---

### Example 3 — High Risk / Distress

**Scenario:** Participant expresses they cannot cope without support.

**Request:**
```json
{
  "conversation_id": "conv_20250601_003",
  "provider_id": "org_abc_123",
  "current_message": {
    "role": "client",
    "text": "I'm feeling overwhelmed and don't know how I'll manage without support this week.",
    "timestamp": "2025-06-01T10:15:00Z"
  },
  "history": []
}
```

**Response:**
```json
{
  "conversation_id": "conv_20250601_003",
  "provider_id": "org_abc_123",
  "is_uncertain": false,
  "classifications": [
    {
      "label": "emergency",
      "confidence": 0.88,
      "reason": "Participant expresses inability to cope and dependency on supports they are not receiving."
    }
  ],
  "sentiment": {
    "label": "distressed_upset",
    "confidence": 0.95,
    "reason": "Client explicitly says they are overwhelmed and cannot manage."
  },
  "risk": {
    "level": "high",
    "indicators": [
      "Participant cannot manage without required support",
      "Emotional distress expressed",
      "Support not being received"
    ],
    "reason": "Participant's wellbeing is directly at risk due to absence of required NDIS support."
  },
  "breakdown": {
    "detected": false,
    "reasons": []
  },
  "outcome": "unresolved",
  "recommended_action": "Escalate to coordinator for immediate review of support provision.",
  "messages_analysed": 1,
  "analysed_at": "2025-06-01T10:15:01Z"
}
```

---

## 9. Field Reference

### Response — top level

| Field | Type | Always present | Description |
|---|---|---|---|
| `conversation_id` | string | Yes | Echoed from request |
| `provider_id` | string | Yes | Echoed from request |
| `is_uncertain` | boolean | Yes | `true` if ALL classification confidence scores are below 0.5. Use as a signal that the message was ambiguous and may need human review. |
| `classifications` | array | Yes | 1 or more items. `normal` is never returned alongside `emergency` or `inappropriate`. |
| `sentiment` | object | Yes | Participant wellbeing analysis |
| `risk` | object | Yes | NDIS risk assessment |
| `breakdown` | object | Yes | Communication breakdown detection |
| `outcome` | string | Yes | `resolved` / `unresolved` / `pending` |
| `recommended_action` | string or null | Yes | Non-null only when `risk.level` is `high`/`critical` or `breakdown.detected` is `true` |
| `messages_analysed` | integer | Yes | How many messages (current + history) were included in the analysis |
| `analysed_at` | ISO datetime | Yes | UTC timestamp of when classification ran |

### `classifications[]`

| Field | Type | Values |
|---|---|---|
| `label` | string | `emergency` / `inappropriate` / `normal` |
| `confidence` | float | 0.0 – 1.0 |
| `reason` | string | Why this label was assigned, citing specific text |

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
| `indicators` | string[] | Specific NDIS risk indicators detected. Empty array for `low` with no concerns. |
| `reason` | string | Overall risk assessment summary |

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

**Breakdown is triggered by:**
- Participant's question ignored or repeatedly deflected
- Repeated clarification requests without resolution
- Conflicting information given by worker
- Conversation becoming circular
- Worker failing to address the actual concern

### `outcome`

| Value | Meaning |
|---|---|
| `resolved` | The concern or question was addressed in this exchange |
| `unresolved` | The issue remains open or was not addressed |
| `pending` | Awaiting action (worker said they will follow up, for example) |

---

## 10. Integration Guide — Backend Team

### When to call this API

Call `POST /api/v1/classify` **every time a new message is sent** in a support worker ↔ client conversation. The classification runs against the message that just arrived (`current_message`) using prior messages as context (`history`).


### What to send

```python
# Pseudocode — adapt to your stack

def on_message_received(conversation, message):
    # Build history: last N messages before this one
    history = conversation.get_last_messages(limit=5, before=message)

    payload = {
        "conversation_id": str(conversation.id),
        "provider_id": str(conversation.provider_org_id),
        "current_message": {
            "role": "support_worker" if message.sender_is_worker else "client",
            "text": message.body,
            "timestamp": message.created_at.isoformat() + "Z",
        },
        "history": [
            {
                "role": "support_worker" if m.sender_is_worker else "client",
                "text": m.body,
                "timestamp": m.created_at.isoformat() + "Z",
            }
            for m in history
        ],
        "metadata": {
            "shift_id": str(conversation.shift_id),
            "client_id": str(conversation.client_id),
            "worker_id": str(message.sender_id),
        }
    }

    response = requests.post(
        url="http://your-classifier-url/api/v1/classify",
        json=payload,
        headers={"X-API-Key": CLASSIFIER_API_KEY},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()
```

### What to do with the response

**You decide.** The classifier returns data — your system decides what to do with it. Common patterns:

```python
result = classify(conversation, message)

# Store the classification against the message
message.classification = {
    "label": result["classifications"][0]["label"],
    "risk_level": result["risk"]["level"],
    "sentiment": result["sentiment"]["label"],
    "breakdown": result["breakdown"]["detected"],
    "outcome": result["outcome"],
}
message.save()

# Trigger an alert? Your call — example thresholds:
if result["risk"]["level"] in ("high", "critical"):
    alert_coordinator(
        conversation=conversation,
        reason=result["risk"]["reason"],
        action=result["recommended_action"],
    )

if result["breakdown"]["detected"]:
    flag_for_supervisor_review(
        conversation=conversation,
        reasons=result["breakdown"]["reasons"],
    )

if result["classifications"][0]["label"] == "emergency":
    send_urgent_notification(conversation)
```

### Timeout recommendation

Set your HTTP timeout to **30 seconds**. AWS Bedrock calls typically take 2–8 seconds. If you are under strict latency requirements, consider calling this asynchronously — store the message first, then classify in the background and update the stored record.

### Retry recommendation

If you receive a `500` error, retry **once** with exponential backoff. Transient Bedrock failures do occur. Do not retry `422` errors — those indicate a malformed request.

### What to change for production deployment

1. **`CORS` origins** — currently set to `"*"` (open). In `app/main.py`, change:
   ```python
   # CHANGE THIS:
   allow_origins=["*"]

   # TO YOUR BACKEND ORIGIN(S):
   allow_origins=["https://api.yourdomain.com", "https://yourdomain.com"]
   ```

2. **`API_KEY`** — set a strong secret in your `.env` or environment variables. Without it, auth is disabled.

3. **AWS credentials** — use an IAM role with `bedrock:InvokeModel` permission scoped to the Sydney region. Do not use long-lived access keys in production.

4. **AWS region** — configured as `ap-southeast-2` (Sydney) for Australian data residency. Do not change this without confirming NDIS data sovereignty requirements.

5. **History limit** — currently 5 messages. Increase via `CONVERSATION_HISTORY_LIMIT` in `.env` for more context. More history = longer prompt = slightly higher latency.

---

## 11. Integration Guide — Frontend Team

### What the frontend receives

The frontend does not call this API directly. The **backend classifies the message**, stores the result, and exposes it to the frontend through your own API in whatever shape you design.

The classifier is a backend-to-backend service.

### Suggested data to surface in the UI

Based on what the classifier returns, here are common UI patterns:

#### Risk badge on a conversation

Use `risk.level` to display a visual indicator next to a conversation in the list:

| Value | Suggested UI |
|---|---|
| `low` | No badge or subtle green indicator |
| `medium` | Yellow/amber badge — "Attention" |
| `high` | Orange badge — "Review Required" |
| `critical` | Red badge with alert — "Urgent" |

#### Sentiment indicator on a message

Use `sentiment.label` to colour-code or annotate messages:

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

When `recommended_action` is non-null, surface it prominently:
```
⚠ Action Required
Escalate to coordinator for immediate review of support provision.
```

#### Breakdown flag

When `breakdown.detected = true`, show a banner or tag on the conversation:
```
⚠ Communication Breakdown Detected
• Participant's question not adequately addressed
• Worker deflecting without explanation
```

#### Outcome chip

Use `outcome` for quick visual status:
- `resolved` — Green chip
- `pending` — Yellow chip
- `unresolved` — Red chip

#### Hover tooltip using `reason` fields

Each field (`classifications[].reason`, `sentiment.reason`, `risk.reason`) contains a plain-English explanation. Use these in tooltips for coordinators who want to understand why something was flagged.

---

## 12. Authentication and Security

### API key

The service uses a simple header-based API key.

- **Key:** `API_KEY` in `.env`
- **Header:** `X-API-Key: your-key-here`
- **No key configured:** Auth is **disabled** — all requests are accepted. Safe for local dev, not for production.

```bash
# With auth enabled:
curl -X POST http://localhost:8000/api/v1/classify \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-secret-key" \
  -d '{...}'
```

If the key is wrong or missing when auth is enabled:
```json
{
  "detail": "Invalid or missing API key"
}
```
HTTP status: `401 Unauthorized`

### What data leaves the service

Every API call sends conversation text to **AWS Bedrock (Sydney region)**. The data path is:

```
Your message text → Sena Classifier (your infra) → AWS Bedrock ap-southeast-2 (Sydney)
```

AWS Bedrock does not train on your data by default. Confirm your Bedrock data privacy settings and NDIS data handling obligations with your compliance team.

### Provider isolation

The `provider_id` field is echoed back in responses but is not used as an access control boundary within the classifier — the service has no database. Data isolation is the responsibility of your backend (ensure one provider's calls cannot query another's stored results in your own system).

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
| `BEDROCK_MODEL_ID` | `au.anthropic.claude-sonnet-4-5-20250929-v1:0` | Claude model used for classification |
| `BEDROCK_MAX_TOKENS` | `1024` | Max tokens in model response |
| `BEDROCK_TEMPERATURE` | `0.1` | Low temperature for consistent, deterministic output |
| `CONVERSATION_HISTORY_LIMIT` | `5` | Max prior messages sent as context |
| `CONFIDENCE_THRESHOLD` | `0.5` | Below this, `is_uncertain` is set to `true` |

---

## 14. Error Handling

| HTTP Status | Meaning | What to do |
|---|---|---|
| `200 OK` | Classification successful | Use the response body |
| `401 Unauthorized` | Missing or wrong API key | Check `X-API-Key` header |
| `422 Unprocessable Entity` | Request body validation failed | Check the `detail` field — it lists which fields failed and why |
| `500 Internal Server Error` | Bedrock API error or model parsing failure | Log the `detail` field. Retry once. If persistent, check AWS Bedrock status. |

### 422 example — missing required field

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "current_message"],
      "msg": "Field required",
      "input": {...}
    }
  ]
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

### Unit tests (no AWS, no network — runs offline)

```bash
cd ai-classifier
pytest tests/test_unit.py -v
```

Uses mocked boto3. No credentials needed. Covers all parsing logic, all 7 sentiment labels, all 4 risk levels, all 3 outcomes, breakdown detection, and all 3 SCOPE examples end-to-end.

### Integration tests (requires live AWS Bedrock + running server)

```bash
# Start the server first:
uvicorn app.main:app --reload --port 8000

# In a separate terminal:
cd ai-classifier
pytest tests/test_classify.py -v
```

Hits the real API and real AWS Bedrock. Requires valid AWS credentials and model access.

### Run all tests

```bash
cd ai-classifier
pytest -v
```

### Run a single test

```bash
pytest tests/test_unit.py::TestParseRisk::test_high -v
```

### Test output

```
tests/test_unit.py::TestParseSentiment::test_label_positive_satisfied PASSED
tests/test_unit.py::TestParseSentiment::test_label_distressed_upset    PASSED
tests/test_unit.py::TestParseRisk::test_low                            PASSED
tests/test_unit.py::TestParseRisk::test_critical                       PASSED
...
```

---

## 16. Interactive Conversation Tester

To get a feel for how the classifier behaves in a real back-and-forth conversation without writing scripts, use the interactive tester:

```bash
cd ai-classifier
python chat.py
```

This will:
1. Connect to `http://localhost:8000` (start the server first)
2. Prompt you to pick a role (`sw` for support worker, `c` for client)
3. Let you type a message
4. Show the full analysis with colour-coded output
5. Automatically build conversation history across turns

```
Role [sw/c]: c
Message (Client): I haven't received my transport support this week.

[1] CLIENT         I haven't received my transport support this week.
────────────────────────────────────────────────
  Classifications:
    NORMAL            ██████████  97%
      → Worker acknowledged the issue and committed to follow up.

  Sentiment:  😤 Frustrated Dissatisfied  (85%)
    → Client explicitly states they did not receive an expected service.

  Risk:       LOW
    → No safety concern. Service delivery gap only.

  Breakdown:  No

  Outcome:    Pending

  Messages analysed: 1  |  2025-06-01T10:05:01
────────────────────────────────────────────────
```

**Commands inside the tester:**

| Command | What it does |
|---|---|
| `reset` | Starts a fresh conversation (clears history) |
| `history` | Shows all messages in the current conversation |
| `quit` | Exits |

**Against a deployed URL:**

```bash
python chat.py --url https://your-deployed-classifier.com --key your-api-key
```

---

## 17. Placeholders and Future Work

The following capabilities are identified in the project scope but **not yet implemented**. They are listed here so integration teams know what is coming and what is not available today.

---

### PLACEHOLDER — Exception-Based Alert Triggers

**What it is:**  
Instead of returning data on every message (current behaviour), the service would additionally fire webhook callbacks or events only when predefined thresholds are crossed — for example:
- Risk level reaches `high` or `critical`
- Sentiment has been `frustrated_dissatisfied` for 3 or more consecutive messages
- `breakdown.detected` becomes `true`
- Classification shifts from `normal` to `emergency`

**Current state:**  
Not implemented. Today, every message returns a full classification response. Your backend can implement this alerting logic itself by inspecting the `risk.level`, `sentiment.label`, `breakdown.detected`, and `classifications` fields on each response and deciding when to alert.

**When available:**  
`[ TO BE DETERMINED ]`

---

### PLACEHOLDER — Full Conversation Analysis Endpoint

**What it is:**  
A new endpoint (`POST /api/v1/analyse`) that accepts a complete conversation (all messages) and returns a holistic report covering:
- Sentiment trend across the full conversation
- Worker responsiveness quality
- Key discussion topics
- All action items and commitments made
- Highest risk point in the conversation
- Overall breakdown summary
- Conversation summary (plain English paragraph)
- Recommended follow-up actions

**Difference from `/classify`:**  

| `/classify` (current) | `/analyse` (planned) |
|---|---|
| Classifies one message at a time | Analyses the whole conversation at once |
| Real-time, called as messages arrive | Called on demand or at end of conversation |
| Returns classification for the current message | Returns trends, summaries, overall picture |
| Good for live monitoring | Good for audits, supervisor review, reporting |

**Current state:**  
Not implemented.

---

### PLACEHOLDER — Rate Limiting

Per-provider or per-API-key rate limiting is not implemented. Add at your API gateway (e.g. AWS API Gateway, nginx, Cloudflare) if needed before production deployment.

---

### PLACEHOLDER — Audit Logging

The service logs classification events to standard output (structured logs via Python `logging`). There is no built-in audit trail or log persistence. Wire your deployment to a log aggregator (CloudWatch, Datadog, ELK) to retain classification history for audit purposes.

---

*End of documentation.*
