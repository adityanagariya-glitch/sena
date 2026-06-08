# AI Classification Service – Integration Guide

## Message Flow
```
┌─────────────────────────┐
│ Their Backend           │
└───────────┬─────────────┘
            │
            ▼
Fetch last N messages
from their database
            │
            ▼
Build classification payload
            │
            ▼
POST /api/v1/classify
            │
            ▼
┌─────────────────────────┐
│ AI Classification API   │
└───────────┬─────────────┘
            │
            ▼
Receives payload
            │
            ▼
Trims history to last 5 messages
(configurable)
            │
            ▼
Sends conversation context
to Amazon Bedrock
            │
            ▼
Bedrock returns:
• Labels
• Confidence scores
• Reasons
            │
            ▼
Classification API returns
response to backend
            │
            ▼
┌─────────────────────────┐
│ Their Backend           │
└───────────┬─────────────┘
            │
            ▼
Decides action:
• Alert
• Flag
• Notify Manager
• Escalate
• Store Result
```

---

# What We Provide

## Endpoints

### POST `/api/v1/classify`

Main classification endpoint.

### GET `/health`

Health check endpoint.

### API docs

GET /docs (Swagger UI, auto-generated)

---

## Features

### Multi-label Classification
A message can receive multiple classifications simultaneously.

Example:

```json
[
  {
    "label": "emergency",
    "confidence": 0.94
  },
  {
    "label": "inappropriate",
    "confidence": 0.88
  }
]
```

### Confidence Scores
Each classification includes a confidence score.

### Classification Reasoning
Each classification includes a human-readable explanation.

### Uncertainty Detection
```json
{
  "is_uncertain": true
}
```
Indicates the result should be reviewed by a human.

### Automatic History Trimming
Only the most recent 5 messages are analysed.
This limit is configurable.

### Provider Isolation
Data is isolated by `provider_id`.
No cross-provider data contamination occurs.
---

# Responsibilities of the Integrating Team
The client system is responsible for:
* Fetching conversation history from its own database.
* Building the request payload.
* Calling the classification API whenever a new message is sent.
* Handling classification outcomes.
* Triggering alerts, flags, notifications, or escalations.
* Maintaining conversation records.

The classification service only analyses messages and returns classifications.

---
# Request Payload

## POST `/api/v1/classify`
```json
{
  "conversation_id": "conv_001",
  "provider_id": "org_abc",
  "current_message": {
    "role": "support_worker",
    "text": "message text here",
    "timestamp": "2025-06-01T10:05:00Z"
  },
  "history": [
    {
      "role": "client",
      "text": "previous message",
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

---
## Field Requirements
| Field           | Required | Description                             |
| --------------- | -------- | --------------------------------------- |
| conversation_id | Yes      | Unique conversation identifier          |
| provider_id     | Yes      | Unique provider/organisation identifier |
| current_message | Yes      | Latest message being analysed           |
| history         | Optional | Previous messages in conversation       |
| metadata        | Optional | Additional business context             |

---
## Message Role Values
The `role` field must be exactly one of:

```text
support_worker
client
```
No other values are supported.

---
## Timestamp Format
All timestamps must be:

```text
UTC ISO 8601
```

Example:

```text
2025-06-01T10:05:00Z
```

---

## History Ordering
History must be supplied:

```text
Oldest → Newest
```

Example:

```text
Message 1
    ↓
Message 2
    ↓
Message 3
    ↓
Current Message
```

---

# Response Format
```json
{
  "conversation_id": "conv_001",
  "provider_id": "org_abc",
  "is_uncertain": false,
  "classifications": [
    {
      "label": "inappropriate",
      "confidence": 0.91,
      "reason": "Support worker used dismissive language violating NDIS Code of Conduct."
    }
  ],
  "messages_analysed": 3,
  "analysed_at": "2025-06-01T10:05:01Z"
}
```

---
# Response Fields

| Field             | Description                            |
| ----------------- | -------------------------------------- |
| conversation_id   | Conversation identifier                |
| provider_id       | Provider identifier                    |
| is_uncertain      | Indicates human review may be required |
| classifications   | List of detected classifications       |
| messages_analysed | Total messages analysed                |
| analysed_at       | Timestamp of analysis                  |

---
# Integration Checklist

Before going live, confirm:

* [ ] Conversation history is fetched from your database.
* [ ] History is ordered oldest → newest.
* [ ] Timestamps are UTC ISO 8601.
* [ ] `role` values are exactly `support_worker` or `client`.
* [ ] API is called whenever a new message is created.
* [ ] Classification results are stored if required.
* [ ] Alerts and escalation workflows are implemented.
* [ ] Human review process exists for uncertain classifications.

---

# Summary
### Classification Service Responsibilities
* Receive conversation context.
* Analyse messages.
* Generate labels.
* Generate confidence scores.
* Generate reasoning.
* Return classification results.

### Client Application Responsibilities
* Store conversations.
* Fetch history.
* Trigger API calls.
* Process results.
* Alert staff.
* Escalate incidents.
* Maintain audit records.


# URL
The endpoint: POST /api/v1/classify
Your deployed URL: https://your-service.com