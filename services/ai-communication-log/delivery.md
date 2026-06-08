# Integration
1. For the Integration Team (developers calling your API)
Give them these four things:

Base URL:
http://<EC2-PUBLIC-IP>:8000

API Key (put in every request header):
X-API-Key: 8fd93889f6dc02e5566ad06c16a15e46e4d9d89f8a92958e29e4d353495d77ab

Endpoint:
POST /api/v1/classify

Content-Type: application/json

Request shape:
{
  "conversation_id": "string",
  "provider_id": "string",
  "current_message": {
    "role": "support_worker" | "client",
    "text": "string",
    "timestamp": "2025-06-01T10:00:00Z"
  },
  "history": [
    { "role": "...", "text": "...", "timestamp": "..." }
  ]
}
Response shape:

{
  "conversation_id": "string",
  "provider_id": "string",
  "is_uncertain": false,
  "classifications": [
    { "label": "emergency|inappropriate|normal", "confidence": 0.98, "reason": "string" }
  ],
  "messages_analysed": 1,
  "analysed_at": "2026-06-08T09:39:02Z"
}
They can also open http://<EC2-PUBLIC-IP>:8000/docs in a browser — FastAPI auto-generates interactive Swagger docs.


# QA
2. For QA Testing
Hand them the existing test suite. Point it at the deployed URL:

$env:BASE_URL = "http://<EC2-PUBLIC-IP>:8000"
$env:API_KEY  = "8fd93889f6dc02e5566ad06c16a15e46e4d9d89f8a92958e29e4d353495d77ab"
pytest ai-classifier/tests/test_classify.py -v

That runs all 20+ tests (normal, emergency, inappropriate, multi-label, validation, response structure) against the live server. They need pytest and requests installed (pip install pytest requests).



# Note:
3. One thing to do before you share the URL
Lock down CORS in ai-classifier/app/main.py — currently it's allow_origins=["*"]. Ask the integration team for their backend domain and replace it:


allow_origins=["https://their-backend-domain.com"]
Then rebuild and redeploy the image. Don't share the URL publicly until this is set.

Summary of what to send:

Base URL + API key (to integration team)
/docs link for interactive API exploration
tests/test_classify.py + the two env var commands (to QA)
Their domain → you update CORS before go-live
