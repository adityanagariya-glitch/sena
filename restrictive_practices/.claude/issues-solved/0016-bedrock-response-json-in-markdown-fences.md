---
id: 0016
title: Bedrock Claude models wrap JSON in markdown code fences — JSONDecodeError on json.loads()
date: 2026-05-13
symptom_keywords: JSONDecodeError Expecting value Extra data markdown fence backtick json.loads bedrock claude converse response text
files_affected: pipeline/triage.py, pipeline/evaluator.py, pipeline/drafter.py
---

## Symptom

Two distinct `JSONDecodeError` variants depending on how the response is parsed:

**Variant A** (naïve string strip):
```
json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
```
Seen when using `text.split("\n", 1)[-1]` and checking `text.endswith("```")` — the trailing fence isn't caught if there's a trailing newline.

**Variant B** (after partial strip):
```
json.decoder.JSONDecodeError: Extra data: line 5 column 1 (char 253)
```
Seen after the leading fence is stripped but the closing ` ``` ` remains, or when the model appends additional explanation text after the JSON block.

Raw response example:
```
'```json\n{\n  "flagged": true,\n  "action_summary": "..."\n}\n```'
```

## Root Cause

Claude models on AWS Bedrock frequently wrap their JSON responses in markdown code fences (` ```json ... ``` `) even when the prompt asks for JSON only. Additionally, the model may append explanatory text after the closing fence — so even a correct fence-strip can leave trailing non-JSON content that `json.loads()` rejects as "Extra data".

Simple approaches fail:
- `text.endswith("```")` — fails if there's a trailing `\n` or extra lines
- Splitting on `\n` — fragile; breaks on models that append notes

## Fix

Use `json.JSONDecoder().raw_decode()` which parses JSON starting from the first `{` and stops at the end of the first valid JSON value, completely ignoring anything before or after:

```python
def _extract_json(text: str) -> dict:
    """Extract JSON object from model output, tolerating markdown fences and trailing text."""
    start = text.find("{")
    if start == -1:
        raise json.JSONDecodeError("No JSON object found", text, 0)
    obj, _ = json.JSONDecoder().raw_decode(text, start)
    return obj
```

Replace every `json.loads(text)` call with `_extract_json(text)` in all three pipeline files.

**Before:**
```python
data = json.loads(text)
```

**After:**
```python
data = _extract_json(text)
```

Add this helper function to each pipeline file above `_make_client()`.

## Verification

```bash
conda activate sena_env
python scripts/test_triage.py
# Should print FLAGGED/CLEAN results without JSONDecodeError
```

## Watch Out For

- **`raw_decode` index parameter**: Pass `text.find("{")` not `0` — otherwise it starts at position 0 which is ` ``` ` and immediately fails.
- **No JSON object at all**: If the model returns a pure text error (e.g. rate limit message), `text.find("{")` returns -1. The guard raises a clean `JSONDecodeError` rather than an unhelpful `TypeError`.
- **JSON arrays**: `raw_decode` with `text.find("{")` misses top-level `[...]` arrays. None of our prompts expect arrays at top level, but if they ever do, use `text.find("[")` with `min()` logic.
- **Prompt instruction still needed**: Even with `_extract_json`, add "Respond with a single flat JSON object only — no markdown, no extra text." to each prompt. It reduces (but doesn't eliminate) fence wrapping, which keeps the raw response cleaner for debugging.
