# Sena — AI Communication Log Classifier

FastAPI service that classifies `support_worker ↔ client` conversations  
as **emergency**, **inappropriate**, or **normal** using **AWS Bedrock (Claude 3.5 Sonnet)**.  
Built for NDIS compliance on the Sena platform.

---

## Project Structure

```
sena-communication-classifier/
├── app/
│   ├── main.py                          # FastAPI app + CORS + routes
│   ├── api/
│   │   └── classify.py                  # POST /api/v1/classify endpoint
│   ├── core/
│   │   └── config.py                    # All config via .env (pydantic-settings)
│   ├── models/
│   │   └── schemas.py                   # Request / Response Pydantic models
│   ├── prompts/
│   │   └── classification_prompt.py     # System prompt + user prompt builder
│   └── services/
│       ├── bedrock_service.py           # AWS Bedrock API calls + response parsing
│       └── classification_service.py    # Orchestration — trim history, call bedrock, build response
├── .env.example
├── requirements.txt
└── README.md
```

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your AWS credentials / region
```

### 3. AWS credentials

**Recommended (production):** Attach an IAM role to your EC2 / ECS / Lambda with Bedrock permissions.  
**Local dev:** Set `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` in `.env`.

Required IAM permission:
```json
{
  "Effect": "Allow",
  "Action": ["bedrock:InvokeModel"],
  "Resource": "arn:aws:bedrock:ap-southeast-2::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0"
}
```

### 4. Run

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

---

## API

### `POST /api/v1/classify`

#### Request Body

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

| Field | Type | Required | Description |
|---|---|---|---|
| `conversation_id` | string | ✅ | Unique ID for this conversation thread |
| `provider_id` | string | ✅ | Org ID — ensures data isolation |
| `current_message` | Message | ✅ | The message that triggered this call |
| `history` | Message[] | ❌ | Last N messages for memory context. Server trims to `CONVERSATION_HISTORY_LIMIT` |
| `metadata` | object | ❌ | Extra context: shift_id, client_id, worker_id etc. |

#### Response

```json
{
  "conversation_id": "conv_20250601_001",
  "provider_id": "org_abc_123",
  "is_uncertain": false,
  "classifications": [
    {
      "label": "inappropriate",
      "confidence": 0.91,
      "reason": "Support worker expressed dismissiveness and refusal to assist client with a basic care need, violating NDIS Code of Conduct obligations."
    }
  ],
  "messages_analysed": 2,
  "analysed_at": "2025-06-01T10:05:01Z"
}
```

| Field | Description |
|---|---|
| `is_uncertain` | `true` if all confidence scores are below `CONFIDENCE_THRESHOLD` |
| `classifications` | Multi-label — can be `emergency`, `inappropriate`, and/or `normal` |
| `messages_analysed` | Total messages sent to model (current + trimmed history) |

### `GET /health`

```json
{
  "status": "ok",
  "version": "1.0.0",
  "model": "anthropic.claude-3-5-sonnet-20241022-v2:0"
}
```

---

## Configuration Reference

All config lives in `.env` and maps to `app/core/config.py`:

| Key | Default | Description |
|---|---|---|
| `CONVERSATION_HISTORY_LIMIT` | `5` | Max past messages sent as context |
| `AWS_REGION` | `ap-southeast-2` | Sydney — closest AUS data residency |
| `BEDROCK_MODEL_ID` | `anthropic.claude-3-5-sonnet-20241022-v2:0` | Bedrock model |
| `BEDROCK_MAX_TOKENS` | `1024` | Max tokens in model response |
| `BEDROCK_TEMPERATURE` | `0.1` | Low = consistent classification |
| `CONFIDENCE_THRESHOLD` | `0.5` | Below this → `is_uncertain: true` |

---

## Adding Docker Later

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## Classification Labels

| Label | When assigned |
|---|---|
| `emergency` | Immediate risk to life/safety — self-harm, medical emergency, abuse, violence |
| `inappropriate` | NDIS Code of Conduct violation — verbal abuse, boundary violation, coercion, restrictive practice |
| `normal` | Professional, respectful conversation — no concerns detected |

Multi-label: a single message can be both `emergency` + `inappropriate`.  
`normal` is never combined with other labels.
