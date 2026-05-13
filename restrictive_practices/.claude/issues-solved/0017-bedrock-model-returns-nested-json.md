---
id: 0017
title: Bedrock Claude returns nested JSON structure — Pydantic ValidationError missing required fields
date: 2026-05-13
symptom_keywords: pydantic ValidationError missing field required nested json bedrock claude evaluator drafter converse response structure
files_affected: pipeline/evaluator.py, pipeline/drafter.py
---

## Symptom

```
pydantic_core._pydantic_core.ValidationError: 5 validation errors for _EvaluatorResponse
incident_detected
  Field required [type=missing, input_value={'determination': {'incid...
practice_category
  Field required [type=missing, ...]
action_summary
  Field required [type=missing, ...]
policy_violation_risk
  Field required [type=missing, ...]
reasoning
  Input should be a valid string [type=string_type, input_value={'summary': '...'}]
```

The JSON is valid and parses correctly, but the top-level keys don't match `_EvaluatorResponse` fields. Instead of a flat `{"incident_detected": ..., "reasoning": "..."}`, the model returns:
```json
{
  "determination": {
    "incident_detected": true,
    "practice_category": "Chemical Restraint"
  },
  "reasoning": {
    "summary": "...",
    "evidence": [...]
  }
}
```

## Root Cause

Unlike Gemini's `response_schema=` parameter (which enforced a specific Pydantic model structure), the AWS Bedrock `converse` API has no built-in schema enforcement for unstructured text responses. Claude is free to invent a JSON structure it considers logical for the content — and for complex evaluator prompts with 12+ fields across multiple conceptual groups, it naturally organises them into nested objects.

The old Gemini code used `response_schema=_EvaluatorResponse` which forced the flat structure. After migration, this enforcement was lost.

## Fix

Add an explicit flat-key instruction at the end of the evaluator and drafter prompts. The key phrase is **"single flat JSON object — no nested objects"** plus an explicit list of the expected top-level keys.

**For evaluator prompt (`_EVALUATOR_PROMPT` in `pipeline/evaluator.py`):**

```python
# Append to the end of the prompt string:
"""
Respond with a single flat JSON object — no nested objects, no markdown, no extra text. Use exactly these top-level keys:
incident_detected, practice_category, action_summary, policy_violation_risk, confidence, reasoning,
trigger_phrases, suppression_factors, bsp_mentioned_in_note, bsp_mention_excerpt, reporting_required, notification_timeframe.
"""
```

**For drafter prompt (`_DRAFT_PROMPT` in `pipeline/drafter.py`):**

```python
# Replace: "Respond with a JSON object containing all fields listed above."
# With:
"Respond with a single flat JSON object only — no markdown, no nested objects, no extra text. Include all fields listed above as top-level keys."
```

**Critical**: Do NOT include literal `{` or `}` in the prompt instruction. The prompt uses Python `.format(transcript=transcript)` and curly braces are format placeholders — they will raise `KeyError: '"incident_detected"'` at runtime.

**Wrong (causes KeyError):**
```python
'Use this structure: {"incident_detected": <bool>}'  # ← braces = .format() placeholder
```

**Right:**
```python
'Keys: incident_detected, practice_category, ...'  # ← no braces
```

## Verification

```bash
conda activate sena_env
python scripts/test_evaluator.py
# Should print evaluator output with incident_detected, practice_category etc. at top level
```

## Watch Out For

- **Same issue applies to drafter**: `_DrafterResponse` has 18 fields across 6 logical sections — Claude will nest them by section unless told otherwise.
- **Triage prompt**: Triage JSON is small (2 fields: `flagged`, `action_summary`) so nesting isn't typically a problem, but still add the explicit format instruction to be safe.
- **Curly braces in f-strings / .format()**: Any example JSON in prompt strings must use `{{` and `}}` to escape braces, OR avoid braces entirely by listing key names inline. Listing keys is cleaner and avoids the escape issue.
- **Tool use / structured output**: The Bedrock `converse` API supports `toolConfig` for schema-enforced output. This is the proper long-term fix but adds complexity. For now, the prompt instruction approach works reliably.
