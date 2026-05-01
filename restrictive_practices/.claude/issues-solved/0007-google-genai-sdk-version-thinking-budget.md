---
id: "0007"
title: AttributeError ThinkingConfig.thinking_budget — google-genai SDK too old
date: 2026-05-01
symptom_keywords: ThinkingConfig thinking_budget AttributeError google-genai sdk version
files_affected: pipeline/triage.py, pyproject.toml
---

## Symptom
```
AttributeError: 'ThinkingConfig' object has no attribute 'thinking_budget'
```
Triage step crashes on first call.

## Root Cause
`ThinkingConfig.thinking_budget` was added in `google-genai 1.74.0`.
Earlier versions (e.g. 1.2.0 which was installed) don't have this attribute.

## Fix
Upgrade the SDK:
```bash
pip install "google-genai>=1.74.0"
```

In `pyproject.toml`:
```toml
"google-genai>=1.74.0",
```

## Verification
`python -c "from google.genai.types import ThinkingConfig; print(ThinkingConfig(thinking_budget=0))"` — no error.

## Watch Out For
- `conda activate sena_env` must be active before installing — otherwise installs to system Python
- After upgrading, run `python scripts/test_triage.py` to verify triage still returns YES/NO correctly
