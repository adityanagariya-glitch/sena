# AI Text Extraction Service

> Stateless FastAPI microservice that extracts structured identity fields from documents (PDFs, images) using AWS Bedrock Nova Lite (vision + language). Returns a standardised 5-field JSON payload for use in participant/worker identity verification workflows.

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

When a participant or support worker uploads an identity document during onboarding, the backend calls this service with either an S3 object key (production) or a local file path (dev/testing). The service reads the document, sends it to AWS Bedrock Nova Lite for multimodal extraction, and returns exactly 5 standardised fields. Any field that cannot be extracted is returned as `null`.

**This service does not store any data.** Stateless — one document in, one extraction result out.

---

## How It Works

```
Backend uploads document to S3
        │
        ▼
POST /extract  { "s3_key": "uploads/org/doc123/passport.pdf" }
  ├─ Validate request
  ├─ Download document from S3 (or read from local path)
  ├─ Detect file format (PDF / DOCX / JPG / PNG)
  ├─ Build Bedrock content block (document block or image block)
  ├─ Call AWS Bedrock Nova Lite (ap-southeast-2)
  ├─ Parse JSON response → map to 5 fixed fields
  ├─ Normalise dates to DD/MM/YYYY
  └─ Return: { document_no, name, issue_date, expiry_date, address }
        │
        ▼
Backend displays results for human review / edit before saving
```

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| API Framework | FastAPI + Uvicorn |
| AI Model | AWS Bedrock — Amazon Nova Lite (`amazon.nova-lite-v1:0`) |
| AWS Region | `ap-southeast-2` (Sydney — AUS data residency) |
| Document Reading | PyMuPDF (PDF), Pillow (images), python-docx (DOCX) |
| File Storage | Amazon S3 (production) / local path (dev) |
| Validation | Pydantic v2 |
| Auth | None implemented (security gap — see below) |
| Database | None (stateless) |
| Containerization | Not yet (Dockerfile TODO) |

---

## API Reference

### `POST /extract` — Production Endpoint

**Headers**
```
Content-Type: application/json
```

> **No authentication is currently implemented.** This endpoint must be protected before production deployment (see Integration Requirements).

**Request Body**
```json
{
  "s3_key": "uploads/org_abc/user_42/doc_xyz/passport.pdf"
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `s3_key` | string | Yes | S3 object key — must exist in the configured bucket |

**Response `200 OK`**
```json
{
  "document_no": "P1234567",
  "name": "Jane Citizen",
  "issue_date": "21/06/2022",
  "expiry_date": "21/06/2027",
  "address": "123 Main Street, Sydney NSW 2000"
}
```

All fields can be `null` if the model cannot extract them. Dates are always normalised to `DD/MM/YYYY`.

**Error Responses**

| Code | Reason |
|------|--------|
| `404` | S3 object not found, or `S3_BUCKET_NAME` env var not set |
| `422` | Unsupported file format |
| `500` | Bedrock extraction failure or response parsing error |

---

### `POST /extract/local` — Dev/Testing Only

> **WARNING: Do NOT expose this endpoint in production.** It reads from the local filesystem using an absolute path — a serious security risk if accessible externally.

**Request Body**
```json
{
  "file_path": "/absolute/path/to/document.jpg"
}
```

**Response:** Same as `/extract`.

---

### `GET /health`

```json
{ "status": "ok" }
```

---

## Supported Document Types

| Format | Extension | Method |
|--------|-----------|--------|
| PDF | `.pdf` | PyMuPDF — first page rendered |
| JPEG image | `.jpg`, `.jpeg` | Pillow |
| PNG image | `.png` | Pillow |
| Word document | `.docx` | python-docx |
| WebP image | `.webp` | Listed as supported — testing coverage unclear |

---

## Extracted Fields

| Field | Description | Format |
|-------|-------------|--------|
| `document_no` | Document/ID number | String |
| `name` | Full name as printed | String |
| `issue_date` | Date the document was issued | `DD/MM/YYYY` |
| `expiry_date` | Document expiry date | `DD/MM/YYYY` |
| `address` | Residential address if present | String |

The service validates that `issue_date` is not later than `expiry_date`. If it is, it logs a warning (likely the model returned a date of birth instead of issue date) but still returns the values.

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AWS_REGION` | No | `ap-southeast-2` | Bedrock + S3 region |
| `S3_BUCKET_NAME` | Yes (for `/extract`) | — | Bucket where documents are stored |
| `AWS_ACCESS_KEY_ID` | Yes* | — | AWS credentials (*or use IAM role) |
| `AWS_SECRET_ACCESS_KEY` | Yes* | — | AWS credentials (*or use IAM role) |

**IAM permissions required:**
```json
{
  "Effect": "Allow",
  "Action": [
    "bedrock:InvokeModel",
    "s3:GetObject"
  ],
  "Resource": [
    "arn:aws:bedrock:ap-southeast-2::foundation-model/amazon.nova-lite-v1:0",
    "arn:aws:s3:::<your-bucket>/*"
  ]
}
```

---

## Running the Service

**Install dependencies** (use the provided venv or install manually)
```bash
pip install fastapi uvicorn boto3 pymupdf pillow python-docx pydantic
```

**Development**
```bash
cd ai-text-extraction
uvicorn scripts.api:app --reload --host 0.0.0.0 --port 8000
```

**Production**
```bash
uvicorn scripts.api:app --host 0.0.0.0 --port 8000
```

**Swagger UI** — http://localhost:8000/docs

**Token usage log** — written to `tokens_logs.json` in the service root after each extraction (append-only).

---

## Integration Guide

### For Backend Teams

The backend owns the document upload flow. The typical integration is:

```
User uploads document (frontend) → backend validates file type → backend uploads to S3
→ backend calls POST /extract with S3 key
→ backend receives 5 fields
→ backend presents fields to user for confirmation/editing
→ backend saves confirmed fields to its own DB
```

**Never save raw extraction results directly without human review.** The model can make errors, especially on damaged or non-standard documents.

**Example call (Python/httpx):**
```python
import httpx

response = httpx.post(
    "http://ai-text-extraction:8000/extract",
    json={"s3_key": f"uploads/{org_id}/{user_id}/{doc_id}/{filename}"}
)

if response.status_code == 200:
    fields = response.json()
    # Present to user for confirmation
elif response.status_code == 500:
    # Log error, show manual entry fallback to user
```

**Retry logic:** Bedrock may throttle on busy periods. Retry once after 2 seconds on `500`.

### For Frontend Teams

Frontend does **not** call this service directly. The backend handles the extraction and returns the pre-filled fields to the frontend for user confirmation.

**Expected UX flow:**
1. User uploads document
2. Frontend shows loading state ("Extracting document details...")
3. Backend calls this service and returns pre-filled fields
4. Frontend renders a review form with the extracted fields pre-populated
5. User confirms or corrects the fields before saving

**Do not auto-save extraction results** — always show a review step.

---

### Pre-Integration Checklist

- [ ] `S3_BUCKET_NAME` is set and the bucket exists
- [ ] AWS credentials or IAM role has `bedrock:InvokeModel` + `s3:GetObject` permissions
- [ ] S3 upload path format is agreed upon between backend and this service (e.g., `uploads/{org_id}/{user_id}/{doc_id}/{filename}`)
- [ ] API authentication added before production deployment (currently none)
- [ ] `/extract/local` endpoint is either removed or blocked from external access in production
- [ ] CORS is restricted to backend IP (currently `allow_origins=["*"]`)
- [ ] Backend has a fallback to manual data entry when extraction returns `null` fields
- [ ] Token logging path updated for containerized environments (currently writes to local JSON file)

### What to Confirm Before Integration

1. **Who uploads the document to S3?** The backend must upload the file and pass the S3 key to this service.
2. **What bucket and key structure?** Agree on the S3 path format before integration.
3. **Is human review mandatory?** Yes — this service should never auto-save results. Define the review UI flow.
4. **What file types will users upload?** Confirm the accepted formats match your UI file picker constraints.
5. **What happens if all fields are null?** Define the fallback — manual entry form.

---

## QA & Testing

### Running Tests

```bash
cd ai-text-extraction
python local_test/test_pipeline.py
```

The test file covers both local file extraction and S3 extraction scenarios.

### Manual Test Scenarios

| Document Type | Expected Outcome |
|---------------|-----------------|
| Clear passport scan (PDF) | All 5 fields extracted |
| Driver's licence (JPG, good quality) | `document_no`, `name`, `expiry_date` extracted; `address` likely null |
| Photo ID card (PNG, low resolution) | Some fields null; `is_uncertain` indicated by nulls |
| DOCX file with identity info | Fields extracted if content is structured |
| Completely blank/empty PDF | All 5 fields null, no error |
| Corrupted file | `500` error |
| Unsupported format (e.g., `.gif`) | `422` error |
| Issue date after expiry date | Server logs warning; both dates returned as-is |

### Known Edge Cases

- **Date of birth vs issue date confusion** — Nova Lite sometimes returns DOB as `issue_date` for passports. The service logs a warning but cannot auto-correct. Human review is essential.
- **Handwritten documents** — Not reliable. Extraction quality depends on scan clarity.
- **Double-sided documents** — Only the first page is processed. If key info is on page 2, it will be missed.
- **Non-English documents** — Extraction attempted; accuracy lower. Human review required.
- **WebP format** — Listed as supported but not fully tested. Treat as unreliable until confirmed.

---

## Implementation Status

### Done
- POST /extract — S3-based document extraction
- POST /extract/local — Local path testing endpoint
- GET /health
- AWS Bedrock Nova Lite integration (vision + language)
- Format detection (PDF, DOCX, JPG, PNG, WebP)
- Date normalisation to DD/MM/YYYY
- Date validation (issue vs expiry)
- Retry on Bedrock throttle (2 retries, 1.5s delay)
- Token usage logging to `tokens_logs.json`
- Pydantic response validation
- Comprehensive test file (1152 lines)

### Missing / Not Yet Implemented

| Item | Impact | Notes |
|------|--------|-------|
| Authentication | Critical | No auth middleware at all — must add before production |
| CORS restriction | High | Currently `allow_origins=["*"]` — restrict to backend IP |
| Dockerfile | Medium | No container support yet |
| Rate limiting | Medium | No per-IP or per-org limits |
| Centralised logging | Medium | Token logs go to local JSON file — breaks in multi-instance deployments |
| Confidence scores | Low | Model does not expose per-field confidence; all-or-nothing null/value |
| Multi-page documents | Low | Only first page processed |
| WebP testing | Low | Listed as supported but coverage unclear |

---

## Integration Requirements

**Mandatory before production integration:**

1. **Add authentication** — API key middleware (see commented example in `scripts/api.py`) or JWT validation
2. **Restrict CORS** — Change `allow_origins=["*"]` to the backend's domain/IP
3. **Block `/extract/local`** — Remove or disable this endpoint in production (do not expose filesystem access)
4. **Set `S3_BUCKET_NAME`** — Required for the `/extract` endpoint to function
5. **AWS IAM permissions** — `bedrock:InvokeModel` for Nova Lite + `s3:GetObject` for the document bucket
6. **Dockerfile** — Required for containerized deployment
7. **Token log path** — Move from local JSON file to a logging service or CloudWatch for production

**Nice to have:**
- Human-review webhook — notify backend when extraction completes for review-queue workflows
- Support for multi-page PDF extraction
- Confidence metadata per field
