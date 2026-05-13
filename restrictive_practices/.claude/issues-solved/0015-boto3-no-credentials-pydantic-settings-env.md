---
id: 0015
title: botocore.exceptions.NoCredentialsError — boto3 does not read pydantic-settings .env values
date: 2026-05-13
symptom_keywords: botocore NoCredentialsError Unable to locate credentials boto3 pydantic settings env AWS_ACCESS_KEY_ID bedrock
files_affected: config.py, pipeline/triage.py, pipeline/evaluator.py, pipeline/drafter.py, ingestion/embedder.py
---

## Symptom

```
botocore.exceptions.NoCredentialsError: Unable to locate credentials
```

Raised when calling `boto3.client("bedrock-runtime").converse(...)` or `invoke_model(...)`, even though `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` are present in the project `.env` file.

## Root Cause

`pydantic-settings` loads `.env` values into its `Settings` object fields but does **NOT** inject them into `os.environ`. boto3 credential resolution reads `os.environ` directly (step 3 of the boto3 credential chain). Because pydantic-settings never sets `os.environ["AWS_ACCESS_KEY_ID"]`, boto3 never finds the credentials.

The shared `.env` file also uses the `SENA_AI_` prefix for all project vars. Standard AWS SDK env vars (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`) don't have that prefix, so they can't be loaded via the `env_prefix` mechanism.

## Fix

**Step 1 — Add fields to `Settings` using `validation_alias` to bypass the `SENA_AI_` prefix:**

```python
# config.py
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SENA_AI_",
        ...
    )
    # validation_alias bypasses env_prefix — reads AWS_ACCESS_KEY_ID directly
    aws_access_key_id: str = Field(default="", validation_alias="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: str = Field(default="", validation_alias="AWS_SECRET_ACCESS_KEY")
    aws_region: str = "ap-southeast-2"
```

**Step 2 — Pass credentials explicitly in every `_make_client()` function:**

```python
def _make_client():
    kwargs: dict = {"region_name": settings.aws_region}
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
    return boto3.client("bedrock-runtime", **kwargs)
```

This must be applied to all 4 files: `pipeline/triage.py`, `pipeline/evaluator.py`, `pipeline/drafter.py`, `ingestion/embedder.py`.

The conditional `if settings.aws_access_key_id` means the function gracefully falls back to IAM role / `~/.aws/credentials` when no keys are set (e.g., in production with an instance role).

## Verification

```bash
conda activate sena_env
python scripts/test_triage.py
# Should return flagged=True/False without NoCredentialsError
```

## Watch Out For

- **Singleton client caching**: `ingestion/embedder.py` uses a `_client` global. If `_make_client()` is called before creds are loaded (e.g. at import time), the cached client will have no creds. Always call `_make_client()` inside `_get_client()` lazily — never at module top-level.
- **IAM role fallback**: When `aws_access_key_id` is empty (production, EC2/ECS with role), boto3 will pick up the role automatically. The `if` guard ensures we don't pass empty strings, which would override the role lookup with invalid creds.
- **Don't use `SENA_AI_AWS_ACCESS_KEY_ID`**: The standard boto3 env var chain expects `AWS_ACCESS_KEY_ID` without prefix. Using `validation_alias` is the correct pydantic-settings pattern to read unprefixed vars.
