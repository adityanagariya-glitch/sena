# Casenote Monthly Report Service

> FastAPI service that generates 7-section NDIS monthly progress reports using AWS Bedrock (Claude Sonnet). Fetches case note data from the Sena backend, computes deterministic metrics in Python, and generates narrative HTML reports with trend analysis and risk registers.

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

This service generates the monthly NDIS Progress Summary Report (PSR) for a client. It is called by the Sena backend or directly by an authorised coordinator/admin with a JWT token. The service:

1. Fetches all case note data for the client and date range from the Sena backend
2. Computes statistical metrics deterministically in Python (no LLM math)
3. Sends bounded, pre-computed evidence to Claude Sonnet to generate 7 report sections in parallel
4. Post-processes output with language linting (SBLC + TILA compliance)
5. Returns the complete HTML report

**Key design principle:** The LLM receives only Python-computed metrics and bounded excerpts — it never sees raw arrays it could miscount. This eliminates hallucination on numerical claims.

---

## How It Works

```
POST /psr-report/monthly-report
  ├─ Validate JWT + request body
  ├─ Fetch client data from Sena backend (paginated: /ai/client-data)
  ├─ Compute stats: fulfillment rate, risk register, milestones, quotes, trends
  │
  ├─ [PARALLEL — asyncio.gather]
  │   ├─ Section 1: Participant Information  (~3–5s)
  │   ├─ Section 2: Introduction             (~8–12s)
  │   ├─ Section 3: Strengths & Progress     (~10–15s)
  │   ├─ Section 4: Risk Factors             (~8–12s)
  │   ├─ Section 5: Trend Analysis           (~5–8s)
  │   └─ Section 6: Support & Approach       (~8–12s)
  │
  ├─ [SEQUENTIAL — waits for sections 3, 4, 5]
  │   └─ Section 7: Summary & Recommendations (~10–15s)
  │
  ├─ Lint each section (SBLC + TILA language enforcement)
  ├─ Convert Markdown → HTML
  └─ Return HTML response with X-*-Tokens headers

Total: ~50–70 seconds
```

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| API Framework | FastAPI + Uvicorn (port 8602) |
| AI Model | AWS Bedrock — Claude Sonnet 4.6 (`au.anthropic.claude-sonnet-4-6`) |
| Parallelism | `asyncio.gather()` + `ThreadPoolExecutor` |
| Metrics Engine | Pure Python (`stats.py`) |
| Language Linting | Custom regex (SBLC + TILA maps) |
| HTML Output | `python-markdown` |
| Trend Storage | JSON files (`trends/{client_id}/{YYYY-MM}.json`) |
| Auth | JWT Bearer token (expiry check only) |
| Data Source | Sena backend REST API (`/ai/client-data`) |
| Port | 8602 |

---

## API Reference

### `POST /psr-report/monthly-report`

**Headers**
```
Authorization: Bearer <jwt-token>
Content-Type: application/json
```

**Request Body**
```json
{
  "client_id": "0ce6359f-9138-4e05-b83b-6c39875f1828",
  "organization_id": "org-123e4567-e89b-12d3-a456-426614174000",
  "date_from": "2026-05-01",
  "date_to": "2026-05-31"
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `client_id` | UUID string | Yes | Client whose data is fetched |
| `organization_id` | UUID string | Yes | Passed to backend for data filtering |
| `date_from` | date string | Yes | `YYYY-MM-DD` format |
| `date_to` | date string | Yes | `YYYY-MM-DD` format |

**Response `200 OK`**

Returns raw HTML (`Content-Type: text/html`). Token usage is in response headers:

```
X-Input-Tokens: 2450
X-Output-Tokens: 1823
X-Total-Tokens: 4273
```

**Error Responses**

| Code | Reason |
|------|--------|
| `401` | Missing, invalid, or expired JWT token |
| `400` | Missing required fields |
| `500` | Bedrock failure or backend data fetch error |

> **Note:** Report generation takes 50–70 seconds. Frontend must use a long timeout and show a loading state.

---

### `GET /psr-report/health`

```json
{ "status": "ok" }
```

---

### `POST /psr-report/trend/save`
Manually save or override a trend entry for a client-month.

**Request Body**
```json
{
  "client_id": "0ce6359f-...",
  "period": "2026-04",
  "trend_text": "Significant improvement in social engagement during April."
}
```

**Response**
```json
{
  "status": "saved",
  "period": "2026-04",
  "file": "trends/0ce6359f-.../2026-04.json"
}
```

---

### `GET /psr-report/trend/{client_id}`
List all stored monthly trends for a client (newest first).

```json
{
  "count": 3,
  "entries": [
    { "period": "2026-05", "trend_text": "...", "saved_at": "2026-06-01T..." },
    { "period": "2026-04", "trend_text": "...", "saved_at": "2026-05-01T..." }
  ]
}
```

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AWS_REGION` | No | `ap-southeast-2` | Hardcoded in `config.py` — AUS data residency |
| `SENA_AI_VERBOSE` | No | `0` | Set to `1` for verbose logging |
| `SENA_AI_BEDROCK_GUARDRAIL_IDS` | No | — | Comma-separated list of `id:version` guardrail pairs |
| `SENA_AI_BEDROCK_GUARDRAIL_ID` | No | — | Single guardrail ID (fallback if _IDS not set) |
| `SENA_AI_BEDROCK_GUARDRAIL_VERSION` | No | `DRAFT` | Guardrail version |
| `BEDROCK_API_KEY` | No | — | Optional Bedrock bearer token |

**Hardcoded values in `config.py` (must update before production):**

| Value | Current | Change To |
|-------|---------|-----------|
| `API_BASE_URL` | `https://dev-api.isena.org/api` | Production backend URL |
| `MODEL_ID` | `au.anthropic.claude-sonnet-4-6` | Can leave as-is |
| `REGION` | `ap-southeast-2` | Can leave as-is |

**AWS IAM permissions required:**
```json
{
  "Effect": "Allow",
  "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
  "Resource": "arn:aws:bedrock:ap-southeast-2::foundation-model/anthropic.claude-sonnet*"
}
```

---

## Running the Service

**Install dependencies**
```bash
cd casenote_monthly
pip install -r requirements.txt   # or use the shared venv
```

**Development**
```bash
python api_main.py
# Starts on http://localhost:8602
# Swagger UI: http://localhost:8602/docs
```

**Production**
```bash
uvicorn api_main:app --host 0.0.0.0 --port 8602 --workers 4
```

**Run tests**
```bash
python test.py
# Offline tests: instant
# API tests (real Bedrock): ~60 seconds
```

---

## Integration Guide

### For Backend Teams

The backend (or a reporting service) calls this endpoint on behalf of a coordinator who wants to generate a monthly report. The backend passes its own JWT — the same token used for other API calls.

**Integration Pattern:**
```
Coordinator requests monthly report (UI)
→ Backend calls POST /psr-report/monthly-report with JWT + client details
→ Service fetches data from backend's /ai/client-data (using same JWT)
→ Service returns HTML
→ Backend stores or streams HTML to frontend
```

**Important:** This service calls back to the backend at `API_BASE_URL/ai/client-data`. The JWT must be valid for both calls. The endpoint must:
- Accept `GET /ai/client-data?client_id=...&date_from=...&date_to=...&page=N`
- Return paginated response: `{ data: { client: {...}, days: [...], pagination: { hasNext, totalPages } } }`

If the backend `/ai/client-data` endpoint is not implemented or returns a different shape, this service will fail.

### For Frontend Teams

**Display the HTML response** inside a `<iframe>` (React) or `WebView` (Flutter).

**React:**
```jsx
const [reportHtml, setReportHtml] = useState(null);
const [loading, setLoading] = useState(false);

const generateReport = async () => {
  setLoading(true);
  const res = await fetch('/api/psr-report/monthly-report', {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ client_id, organization_id, date_from, date_to })
  });
  const html = await res.text();
  setReportHtml(html);
  setLoading(false);
};

// Render:
<iframe srcDoc={reportHtml} style={{ width: '100%', height: '800px' }} />
```

**Flutter:**
```dart
final response = await http.post(
  Uri.parse('${baseUrl}/psr-report/monthly-report'),
  headers: { 'Authorization': 'Bearer $token', 'Content-Type': 'application/json' },
  body: jsonEncode({ 'client_id': clientId, ... }),
).timeout(const Duration(seconds: 90));

// Display in WebView with htmlData parameter
```

**Set timeout to at least 90 seconds.** Reports take 50–70 seconds to generate.

---

### Pre-Integration Checklist

- [ ] Sena backend has `/ai/client-data` endpoint implemented with correct response shape
- [ ] `API_BASE_URL` updated in `config.py` to point to the correct backend environment (not dev)
- [ ] AWS credentials or IAM role with `bedrock:InvokeModel` in `ap-southeast-2`
- [ ] JWT tokens used by coordinators are valid and not expired (service only checks expiry)
- [ ] Frontend has a 90-second timeout and visible loading state for report generation
- [ ] `trends/` directory is writable by the service process
- [ ] Backend handles `500` responses (Bedrock throttle) with retry + user-friendly message
- [ ] Frontend renders HTML in a sandboxed iframe or WebView

### What to Confirm Before Integration

1. **`/ai/client-data` endpoint shape** — The service expects a specific paginated response structure. Confirm the backend response exactly matches what the service expects (see `api_main.py` pagination logic).
2. **JWT sharing** — The frontend JWT is forwarded to the backend data endpoint. Confirm the same token is valid for both the report service and the data endpoint.
3. **Report storage** — Does the backend store the generated HTML, or does it regenerate on every view? Reports take 50–70s, so re-generation on every page view is expensive.
4. **Trend persistence** — Trend JSON files are written to the local filesystem. This will not persist across container restarts. Confirm if PostgreSQL or S3-backed trend storage is needed.

---

## QA & Testing

### Running Tests

```bash
python test.py
```

- **Offline tests** (instant): stats.py functions, linter SBLC/TILA replacements, milestone/quote extraction, risk register builders
- **API tests** (real Bedrock, ~60s): all 4 endpoints, token header validation, auth rejection check

### Manual Test Scenarios

| Scenario | Expected |
|----------|----------|
| Valid request with full month of data | HTML report returned in 50–70s with all 7 sections |
| Valid request with no data (empty month) | Report generated with "no data" language in each section |
| Missing `client_id` | `400 Bad Request` |
| Expired JWT | `401 Unauthorized` |
| Backend `/ai/client-data` returns 404 | `500` with meaningful error |
| Bedrock throttled | `500` — retry after 30s |
| Trend save + retrieve | Trend stored as JSON, appears in GET response |

### Known Edge Cases

- **Empty months** — The service handles zero case notes gracefully, but LLM output quality is low.
- **Very large data sets** — The service caps narrative input at 12,000 characters to prevent prompt overflow. Data beyond this is truncated with a log warning.
- **Slow Bedrock** — Section generation can take up to 30s individually. Total report time can reach 90s during peak AWS load.
- **Missing prior-month trends** — Section 5 trend comparison only works if a previous month's data was saved. First-ever report for a client will have no trend data.

---

## Implementation Status

### Done
- All 4 REST endpoints (monthly-report, health, trend/save, trend/{client_id})
- 7-section report generation (sections 1–6 parallel, section 7 sequential)
- Deterministic Python metrics engine (`stats.py`)
- Anti-hallucination guardrails (LLM only sees pre-computed facts)
- SBLC + TILA language linting
- Trend persistence (JSON files)
- JWT authentication (expiry check)
- Token tracking headers
- Bedrock retry wrapper
- Full test suite

### Missing / Not Yet Implemented

| Item | Impact | Notes |
|------|--------|-------|
| `API_BASE_URL` points to dev | Critical | Must update `config.py` before production |
| Trend storage is file-based | High | JSON files don't persist across container restarts — needs S3 or DB-backed storage |
| JWT signature not verified | Medium | Only expiry is checked. Backend is trusted to issue valid tokens |
| Bedrock model hardcoded | Low | `MODEL_ID = "au.anthropic.claude-sonnet-4-6"` in `config.py` — should be env var |

---

## Integration Requirements

**Mandatory before production integration:**

1. **Update `API_BASE_URL`** in `config.py` to production backend URL
2. **Backend `/ai/client-data` endpoint** — must be implemented and match the expected paginated response shape
3. **AWS IAM permissions** — `bedrock:InvokeModel` for Claude Sonnet in `ap-southeast-2`
4. **Frontend 90-second timeout** — report generation takes 50–70s; shorter timeouts will abort the request
5. **Trend storage migration** — move from local JSON files to persistent storage (S3 or PostgreSQL) for container deployments

**Nice to have:**
- JWT signature verification (currently only expiry checked)
- `MODEL_ID` moved to environment variable
- Async Bedrock streaming to reduce perceived latency
