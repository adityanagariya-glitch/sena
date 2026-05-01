---
id: "0008"
title: Evaluator model 404 on Vertex AI — model not provisioned in region
date: 2026-05-01
symptom_keywords: gemini pro 404 vertex ai australia-southeast1 evaluator model not found provisioned
files_affected: .env, config.py
---

## Symptom
```
google.api_core.exceptions.NotFound: 404 Model 'gemini-3.1-pro-preview' not found
# or: 404 Publisher model 'publishers/google/models/...' not found
```
Only evaluator step fails; triage (Flash) works fine.

## Root Cause
A GCP project or region may not have Pro-tier Gemini models provisioned. Model availability
varies by project tier, region, and model generation. Flash models are universally available.

## Fix
Short-term: use Flash as fallback in `.env`:
```
SENA_AI_EVALUATOR_MODEL=gemini-3-flash-preview
```

AI Studio (API key, `SENA_AI_GCP_PROJECT` empty) always has all models available — no
provisioning required.

For Vertex AI: request model enablement via GCP console → Model Garden for your project + region.

## Verification
Evaluator step completes without 404. Watch for lower reasoning quality with Flash.

## Watch Out For
- This is project-specific + region-specific — a new project or region may need the same fix
- AI Studio always has both Flash and Pro; Vertex AI needs provisioning
- After enabling Pro on Vertex, revert `.env` to `SENA_AI_EVALUATOR_MODEL=gemini-3.1-pro-preview`
- Current models (2026-05): triage=`gemini-3-flash-preview`, evaluator=`gemini-3.1-pro-preview`
