# curl
curl -X POST http://localhost:8000/api/v1/classify \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": "test_001",
    "provider_id": "org_001",
    "current_message": {
      "role": "client",
      "text": "I need help urgently.",
      "timestamp": "2025-06-01T10:05:00Z"
    }
  }'


# OR
pytest tests/test_classify.py -v