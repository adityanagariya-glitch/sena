---
id: "0014"
title: dotenv inline comment parsed as value — causes non-empty string for blank setting
date: 2026-05-01
symptom_keywords: dotenv inline comment value truthy gcp_project use_vertex_ai vertex ai mode wrong url fragment 404
files_affected: .env
---

## Symptom
```
google.genai.errors.ClientError: 404 Not Found
The requested URL /v1beta1/projects/ was not found on this server.
```
Vertex AI URL path appears even though `SENA_AI_GCP_PROJECT` was intended to be blank.
The 404 HTML response is from google.com (not aiplatform.googleapis.com).

## Root Cause
python-dotenv parses inline comments as part of the value for unquoted settings.

```
SENA_AI_GCP_PROJECT=                         # e.g. sena-ai-prod-123456
```

After pydantic strips leading whitespace, `gcp_project` = `"# e.g. sena-ai-prod-123456"` — truthy,
so `use_vertex_ai = True`. The `#` character in the project value acts as a URL fragment separator,
truncating the Vertex AI endpoint URL to just `/v1beta1/projects/`, which Google's standard web
server catches and returns as an HTML 404 page.

## Fix
**Never put inline comments on the same line as a `.env` value.** Put comments on their own line above:

```
# GCP project ID (leave blank for AI Studio mode)
SENA_AI_GCP_PROJECT=
```

Not:
```
SENA_AI_GCP_PROJECT=    # e.g. my-project   ← WRONG — comment becomes the value
```

## Verification
`python -c "from config import settings; print(repr(settings.gcp_project), settings.use_vertex_ai)"`
Should print: `'' False`

## Watch Out For
- This applies to ALL `.env` values — model names, URLs, API keys — any inline comment
  becomes part of the string value
- Boolean-like settings are especially dangerous: `SOME_FLAG=true  # enable this`
  parses as `"true  # enable this"`, which pydantic may reject or interpret unexpectedly
- The fix is permanent: keep all `.env` comments on their own preceding line
