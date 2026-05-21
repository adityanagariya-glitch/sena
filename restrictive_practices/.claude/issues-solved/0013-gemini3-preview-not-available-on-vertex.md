---
id: "0013"
title: gemini-3-flash-preview / gemini-3.1-pro-preview 404 on Vertex AI
date: 2026-05-01
symptom_keywords: gemini-3 flash preview pro 404 vertex ai not found provisioned preview model
files_affected: .env
---

## Symptom
```
google.genai.errors.ClientError: 404 NOT_FOUND
Publisher Model `projects/.../locations/australia-southeast1/publishers/google/models/gemini-3-flash-preview`
was not found or your project does not have access to it.
```
Triage step fails immediately. Only happens when `SENA_AI_GCP_PROJECT` is set (Vertex AI mode).

## Root Cause
`gemini-3-flash-preview` and `gemini-3.1-pro-preview` are preview models available on
AI Studio only. They are not yet GA on Vertex AI and require explicit allowlist access
per project. The GCP project `mobileappdev-2c1bd` does not have this access.

The `.env` had two `SENA_AI_GCP_PROJECT=` lines — the second one (`=mobileappdev-2c1bd`)
at the bottom of the file overrode the first empty line, forcing Vertex AI mode.

## Fix
Switch to AI Studio mode for dev by commenting out the populated `SENA_AI_GCP_PROJECT` line
and updating the embedding model to the AI Studio name:

In `.env`:
```
# SENA_AI_GCP_PROJECT=mobileappdev-2c1bd   ← comment out
SENA_AI_EMBEDDING_MODEL=gemini-embedding-2  ← AI Studio name
```

**After this change, re-ingest all chunks** — embedding model changed, existing vectors
in DB are incompatible:
```bash
# Delete old chunks then re-ingest from local pdfs/ folder
docker exec -it sena-ai-db psql -U sena_ai -d sena_ai -c "TRUNCATE rp_ndis_policy_chunks;"
python scripts/ingest_ndis_policies.py
```

## Verification
Server starts; `POST /v1/restrictive-practices/evaluate` returns 200 with triage result.

## Watch Out For
- **Single `.env` rule**: having two `SENA_AI_GCP_PROJECT=` lines is a trap — the last one wins
  with pydantic-settings. Keep only one, either blank (AI Studio) or populated (Vertex AI).
- For production on Vertex AI: request gemini-3 model access via GCP Model Garden once GA
- Embedding model names differ by provider (see issue 0009) — always update both GCP_PROJECT
  AND EMBEDDING_MODEL together when switching providers
- After switching provider, ALWAYS re-ingest — embedding spaces are incompatible across providers
