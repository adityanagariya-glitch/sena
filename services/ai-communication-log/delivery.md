# Delivery Handoff — Sena AI Communication Classifier

---

## 1. For the Integration Team (backend developers calling the API)

Give them these four things:

**Base URL:**
```
http://<EC2-PUBLIC-IP>:8000
```

**API Key** (include in every request header):
```
X-API-Key: YOUR_API_KEY
```

**Endpoint:**
```
POST /api/v1/classify
```

**Content-Type:** `application/json`

**Interactive docs** (browser):
```
http://<EC2-PUBLIC-IP>:8000/docs
```

---

### Request shape

```json
{
  "conversation_id": "string",
  "provider_id": "string",
  "current_message": {
    "role": "support_worker | client",
    "text": "string",
    "timestamp": "2025-06-01T10:00:00Z"
  },
  "history": [
    { "role": "support_worker | client", "text": "string", "timestamp": "..." }
  ],
  "metadata": {
    "shift_id": "optional",
    "client_id": "optional",
    "worker_id": "optional"
  }
}
```

---

### Response shape

```json
{
  "conversation_id": "string",
  "provider_id": "string",
  "is_uncertain": false,
  "classifications": [
    {
      "label": "emergency | inappropriate | normal",
      "confidence": 0.95,
      "reason": "string"
    }
  ],
  "sentiment": {
    "label": "positive_satisfied | neutral | frustrated_dissatisfied | distressed_upset | confused_uncertain | engaged | disengaged",
    "confidence": 0.88,
    "reason": "string"
  },
  "risk": {
    "level": "low | medium | high | critical",
    "indicators": ["string"],
    "reason": "string"
  },
  "breakdown": {
    "detected": false,
    "reasons": ["string"]
  },
  "outcome": "resolved | unresolved | pending",
  "recommended_action": "string or null",
  "messages_analysed": 2,
  "analysed_at": "2025-06-01T10:05:01Z"
}
```

**Key fields for integration:**

| Field | When to act on it |
|---|---|
| `classifications[].label` | `emergency` or `inappropriate` → trigger alert workflow |
| `risk.level` | `high` or `critical` → escalate to coordinator |
| `recommended_action` | Non-null → surface this to the coordinator immediately |
| `breakdown.detected` | `true` → flag conversation for supervisor review |
| `is_uncertain` | `true` → route to human review queue |
| `outcome` | `unresolved` → may need follow-up |

---

## 2. For QA Testing

Hand them the existing test suite. Point it at the deployed URL:

```powershell
# PowerShell
$env:BASE_URL = "http://<EC2-PUBLIC-IP>:8000"
$env:API_KEY  = "YOUR_API_KEY"
cd ai-classifier
pytest tests/test_classify.py -v
```

```bash
# bash / Linux
export BASE_URL="http://<EC2-PUBLIC-IP>:8000"
export API_KEY="YOUR_API_KEY"
cd ai-classifier
pytest tests/test_classify.py -v
```

This runs all tests — normal, emergency, inappropriate, sentiment (7 labels), risk (4 levels), breakdown, outcome, multi-label, history trimming, validation — against the live server.

---

## 3. One thing to do before sharing the URL

Lock down CORS in `ai-classifier/app/main.py` — currently set to `allow_origins=["*"]`.

Ask the integration team for their backend domain and replace it:

```python
allow_origins=["https://their-backend-domain.com"]
```

Then rebuild the Docker image, push to ECR, and redeploy. Do not share the URL publicly until this is set.

---

## Summary of responsibilities

**This classifier:**
- Receives a message + history
- Analyses and returns: classification labels, sentiment, risk level, breakdown detection, outcome, recommended action
- Does nothing else — no storage, no alerts, no side effects

**Integration team's responsibility:**
- Call the API whenever a new message is sent
- Store the classification result if needed
- Decide when to alert, escalate, or flag based on the returned fields
- Maintain conversation records and history
