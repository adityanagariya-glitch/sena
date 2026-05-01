---
id: "0004"
title: response.parsed returns None for gemini-2.5-x models
date: 2026-05-01
symptom_keywords: response.parsed None NoneType gemini 2.5 flash pro json structured output
files_affected: pipeline/triage.py, pipeline/evaluator.py
---

## Symptom
```python
result = response.parsed   # returns None
# → AttributeError: 'NoneType' object has no attribute 'flagged'
```
Only affects `gemini-2.5-flash` and `gemini-2.5-pro`. Works on `gemini-1.5` series.

## Root Cause
`response.parsed` is populated by the older `response_schema=` automatic parsing path.
`gemini-2.5-x` models return thinking tokens + JSON text — the SDK's auto-parser
fails silently and returns None instead of raising.

## Fix
Always use `json.loads(response.text)` and parse manually:
```python
import json
raw = json.loads(response.text)
flagged = raw.get("flagged", False)
```

For evaluator with Pydantic model:
```python
raw = json.loads(response.text)
parsed = _EvaluatorResponse(**raw)
```

Wrap in try/except for safety:
```python
try:
    raw = json.loads(response.text)
except json.JSONDecodeError as exc:
    raise ValueError(f"LLM returned non-JSON: {response.text[:200]}") from exc
```

## Verification
Both triage and evaluator return structured results without AttributeError.

## Watch Out For
- If Gemini SDK is updated and `response.parsed` starts working again, remove the workaround
- Do not use `response_schema=` param on triage — it forces verbose thinking mode (latency hit)
