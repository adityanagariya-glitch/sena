---
id: "0009"
title: Embedding model 404 — different model names for AI Studio vs Vertex AI
date: 2026-05-01
symptom_keywords: embedding model 404 not found gemini-embedding-2 gemini-embedding-001 ai studio vertex
files_affected: .env, config.py, ingestion/embedder.py
---

## Symptom
```
google.api_core.exceptions.NotFound: 404 Model 'gemini-embedding-2' not found
# or the inverse: 'gemini-embedding-001' not found on AI Studio
```
Ingestion step crashes; no chunks are stored.

## Root Cause
Gemini embedding models have DIFFERENT names depending on provider:
- AI Studio (API key, `SENA_AI_GCP_PROJECT` empty): `gemini-embedding-2`
- Vertex AI (`SENA_AI_GCP_PROJECT` set): `gemini-embedding-001`

Using the wrong name for the active provider returns a 404.

## Fix
Set `.env` correctly for the active provider:

For AI Studio:
```
SENA_AI_GCP_PROJECT=
SENA_AI_EMBEDDING_MODEL=gemini-embedding-2
```

For Vertex AI:
```
SENA_AI_GCP_PROJECT=mobileappdev-2c1bd
SENA_AI_EMBEDDING_MODEL=gemini-embedding-001
```

## Verification
`python scripts/ingest_docs.py --sample` completes without 404; chunks appear in DB.

## Watch Out For
- **CRITICAL**: Ingest-time and query-time embedding models MUST match. If you change
  the model, all existing chunks become stale and must be re-ingested.
- Treat `config.py` as source of truth for the current model — SESSION_START.md may lag
- `config.embedding_model` is what the running code uses — always verify against that file
