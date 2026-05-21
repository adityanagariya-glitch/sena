---
id: "0010"
title: 422 Unprocessable Entity from Swagger UI — literal newlines in JSON string
date: 2026-05-01
symptom_keywords: 422 unprocessable entity swagger ui json newline transcript invalid body
files_affected: (no code change needed — user input issue)
---

## Symptom
```
POST /v1/restrictive-practices/evaluate → 422 Unprocessable Entity
{
  "detail": [{"type": "json_invalid", "loc": ["body"], "msg": "JSON decode error", ...}]
}
```
Occurs when entering the transcript in Swagger UI's "Try it out" box and pressing Enter
to break the text across multiple lines.

## Root Cause
JSON does not allow literal newline characters inside string values. Pressing Enter in
Swagger UI's textarea inserts an actual `\n` byte (0x0A) into the string, making the
JSON body syntactically invalid. FastAPI/Pydantic receives malformed JSON and returns 422.

## Fix
No code change required. User must either:

**Option A** — keep the entire transcript on one line in Swagger:
```json
{"case_note_id":"...","client_id":"liam-001","worker_id":"w-001","transcript":"I held both his arms..."}
```

**Option B** — use escaped `\n` instead of actual line breaks:
```json
{"transcript": "Line one.\nLine two.\nLine three."}
```

**Option C** — use curl (pre-escaped in DEMO.md):
```bash
curl -s -X POST http://localhost:8084/v1/restrictive-practices/evaluate \
  -H "Content-Type: application/json" \
  -d '{"case_note_id":"...","client_id":"liam-001","worker_id":"w-001","transcript":"..."}'
```

## Verification
Request returns HTTP 200 with pipeline result JSON.

## Watch Out For
- This is NOT a validation error on the Pydantic model — it's a JSON parsing error BEFORE
  Pydantic even sees the data
- The 422 error body will say `json_invalid` not `value_error` — that's the tell
