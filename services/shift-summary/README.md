# Summary Consolidation API

Receives N text summaries, consolidates them via **AWS Bedrock (Claude)**, and returns a single summary.

---

## Project Structure

```
summarizer_api/
├── main.py          # FastAPI app & routes
├── auth.py          # API key dependency
├── bedrock.py       # Boto3 Bedrock client & invocation
├── prompts.py       # Prompt builder
├── schemas.py       # Pydantic request/response models
├── config.py        # Centralised settings (pydantic-settings)
├── tests.py         # Full pytest test suite
├── requirements.txt
└── .env.example     # Copy to .env and fill in values
```

---

## Setup

```bash
# 1. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env — fill in API_KEY and AWS credentials

# 4. Run the server
uvicorn main:app --reload       # development
uvicorn main:app --host 0.0.0.0 --port 8000  # production
```

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
    "First summary text...",
    "Second summary text...",
    "Third summary text..."
  ]
}
```

**Success Response `200`**
```json
{
  "consolidated_summary": "Combined summary produced by Claude..."
}
```

**Error Responses**

| Code | Reason |
|------|--------|
| 401  | Missing or invalid `X-API-Key` |
| 422  | Validation error (wrong count, empty strings, etc.) |
| 502  | Bedrock invocation or response parsing failure |

---

### `GET /health`

No auth required. Returns `{ "status": "ok", "version": "1.0.0" }`.

---

## Configuration Reference

All settings live in `.env`. Nothing is hardcoded.

| Variable | Default | Description |
|---|---|---|
| `API_KEY` | **required** | Secret key clients send in `X-API-Key` |
| `AWS_REGION` | `us-east-1` | Bedrock region |
| `BEDROCK_MODEL_ID` | `anthropic.claude-3-5-sonnet-20241022-v2:0` | Claude model on Bedrock |
| `BEDROCK_MAX_TOKENS` | `1024` | Max tokens in model response |
| `BEDROCK_TEMPERATURE` | `0.3` | Model temperature (0.0-1.0) |
| `PROMPT_TEMPLATE` | *(see .env.example)* | Prompt with `{count}` and `{summaries}` placeholders |
| `MIN_SUMMARIES` | `1` | Minimum summaries per request |
| `MAX_SUMMARIES` | `20` | Maximum summaries per request |
| `MIN_SUMMARY_LENGTH` | `1` | Min chars per individual summary |
| `MAX_SUMMARY_LENGTH` | `5000` | Max chars per individual summary |
| `APP_ENV` | `development` | `development` / `production` / `test` |

---

## Running Tests

```bash
pytest tests.py -v
```

AWS credentials are never called during tests — Bedrock is fully mocked.

---

## AWS IAM Permissions Required

```json
{
  "Effect": "Allow",
  "Action": ["bedrock:InvokeModel"],
  "Resource": "arn:aws:bedrock:<region>::foundation-model/anthropic.claude-*"
}
```
