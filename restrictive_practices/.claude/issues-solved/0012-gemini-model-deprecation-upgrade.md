---
id: "0012"
title: Gemini model deprecation — upgrading triage and evaluator model IDs
date: 2026-05-01
symptom_keywords: deprecated model gemini 2.5 flash pro upgrade 3 3.1 preview triage evaluator
files_affected: .env, config.py
---

## Symptom
Models being called start returning deprecation warnings or errors. `gemini-2.5-flash`
and `gemini-2.5-pro` are scheduled for deprecation; `gemini-2.0-x` and `gemini-1.5-x`
are already removed.

## Root Cause
Gemini model generations are released and deprecated on a rolling basis. Training data
cutoffs mean the LLM's "current" model knowledge will always be stale.

## Fix
**Always use the Gemini API dev skill before updating model IDs.** The skill contains
up-to-date model names that override training data.

Current models as of 2026-05:
| Use | Model | Notes |
|-----|-------|-------|
| Triage (fast YES/NO gate) | `gemini-3-flash-preview` | 1M context, fast, balanced |
| Evaluator (complex reasoning) | `gemini-3.1-pro-preview` | 1M context, best reasoning |
| Embedding | `gemini-embedding-001` (Vertex) / `gemini-embedding-2` (AI Studio) | must match ingest+query |

Update two places:
1. `.env` — `SENA_AI_TRIAGE_MODEL` and `SENA_AI_EVALUATOR_MODEL`
2. `config.py` — default values for `triage_model` and `evaluator_model`

Pipeline files use `settings.triage_model` / `settings.evaluator_model` — no other changes needed.

## Verification
`python scripts/test_triage.py` and `python scripts/test_evaluator.py` return results without
deprecation warnings or 404 errors.

## Watch Out For
- Embedding model changes require full re-ingestion — `gemini-embedding-*` naming is stable
  but if it changes, ALL chunks must be deleted and re-ingested (vectors are incompatible)
- `thinking_budget=0` (triage) and `max_output_tokens=4096` (evaluator) params carry over
  to new model generations — they are standard ThinkingConfig/GenerationConfig fields
- `json.loads(response.text)` pattern (not `response.parsed`) applies to all gemini-3.x too
