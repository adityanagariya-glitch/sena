---
id: "0008"
title: gemini-2.5-pro 404 on Vertex AI in australia-southeast1
date: 2026-05-01
symptom_keywords: gemini-2.5-pro 404 vertex ai australia-southeast1 evaluator model not found
files_affected: .env, config.py
---

## Symptom
```
google.api_core.exceptions.NotFound: 404 Model 'gemini-2.5-pro' not found
# or: 404 Publisher model 'publishers/google/models/gemini-2.5-pro' not found
```
Only evaluator step fails; triage (Flash) works fine.

## Root Cause
The GCP project `mobileappdev-2c1bd` in `australia-southeast1` only has Gemini Flash
provisioned. Gemini Pro requires a separate model garden enablement request.

## Fix
Short-term: use Flash as fallback in `.env`:
```
SENA_AI_EVALUATOR_MODEL=gemini-2.5-flash
```

Long-term: request gemini-2.5-pro enablement via GCP console for the project + region.

## Verification
Evaluator step completes without 404. Note: Flash gives lower-quality reasoning for
compliance verdicts — watch for less precise policy citations in evaluator output.

## Watch Out For
- AI Studio (API key mode, no `SENA_AI_GCP_PROJECT`) does NOT have this problem — Pro is
  always available via AI Studio
- This is project-specific — a new GCP project provisioned fresh may need the same fix
- Once Pro is enabled, revert `.env` to `SENA_AI_EVALUATOR_MODEL=gemini-2.5-pro`
