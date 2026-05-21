---
id: "0011"
title: Pydantic Settings validation error — extra fields from shared .env
date: 2026-05-01
symptom_keywords: pydantic settings validation error extra fields env SENA_AI unexpected
files_affected: config.py
---

## Symptom
```
pydantic_settings.errors.SettingsError: 1 validation error for Settings
SENA_AI_BEDROCK_MODEL_ID
  Extra inputs are not permitted [type=extra_forbidden]
```
App fails to start. Only happens in the full SENA monorepo env where a shared `.env`
is used across all services.

## Root Cause
The shared `.env` at the SENA project root contains env vars for ALL services
(voice, onboarding, OCR, etc.), including things like `SENA_AI_BEDROCK_MODEL_ID`
and `SENA_AI_LIVEKIT_URL`. Pydantic Settings with default `model_config` raises on
any field that doesn't have a corresponding class attribute.

## Fix
Add `extra="ignore"` to `SettingsConfigDict` in `config.py`:
```python
model_config = SettingsConfigDict(
    env_prefix="SENA_AI_",
    env_file=str(Path(__file__).parent / ".env"),
    env_file_encoding="utf-8",
    extra="ignore",   # ← silently drops keys not in this class
)
```

## Verification
`uvicorn main:app --reload --port 8084` starts without validation errors.

## Watch Out For
- `extra="ignore"` means typos in env var names will be silently ignored — double-check
  spelling if a config value isn't being picked up
- This is intentional for this module — do NOT remove it when refactoring Settings
