# SENA AI — API Endpoint Reference

> **Canonical per-endpoint truth lives in `openapi-specs/*.json`** — refreshed 2026-06-18 from live FastAPI introspection. This document is the SERVICE CATALOG + integration cheatsheet. For request/response schemas, route parameters, and example payloads, open the matching OpenAPI spec.

## Service catalog (10 live services)

| Service | Dev port | Prod port | OpenAPI spec | Purpose |
|---------|----------|-----------|--------------|---------|
| voice | 8082 | 8008 | `voice-openapi.json` | Flow B case note dictation (Bedrock + LiveKit) |
| onboarding | 8083 | 8009 | `onboarding-openapi.json` | Gemini Live voice onboarding (NDIS participant intake) |
| case_review | 8084 | 8002 | `case-review-openapi.json` | Review / classify / restrictive-practices / voice draft (19 routes) |
| casenote_monthly | 8602 | 8004 | `casenote-monthly-openapi.json` | NDIS monthly 7-section report (Bedrock Claude Sonnet 4.6) |
| policy_proc | 8000 | 8000 | `policy-openapi.json` | RAG over NDIS policies/procedures (Bedrock KB + Rerank) |
| staff | 8601 | 8001 | `staff-openapi.json` | Staff/client SSE Q&A with scoped agent tools |
| ai_chatbot | 8003 | 8003 | `ai-chat-openapi.json` | Gateway/router (chip-driven) to staff + policy backends |
| ai-communication-log | 8005 | 8005 | `ai-communication-log-openapi.json` | Sentiment + risk + outcome batch classifier (Bedrock Claude Sonnet 4.5) |
| shift-summary | 8006 | 8006 | `shift-summary-openapi.json` | Multi-summary consolidation (Bedrock Claude Haiku 4.5) |
| ai-text-extraction | 8007 | 8007 | `ai-text-extraction-openapi.json` | Identity-doc field extraction (Bedrock Nova Lite vision) |

`services/ocr/` is an empty skeleton — no `main.py`, no spec.

## Base URLs

### Local development
| Service | URL |
|---------|-----|
| voice | `http://localhost:8082` |
| onboarding | `http://localhost:8083` |
| case_review | `http://localhost:8084` |
| casenote_monthly | `http://localhost:8602` |
| policy_proc | `http://localhost:8000` |
| staff | `http://localhost:8601` |
| ai_chatbot | `http://localhost:8003` |
| ai-communication-log | `http://localhost:8005` |
| shift-summary | `http://localhost:8006` |
| ai-text-extraction | `http://localhost:8007` |

### Production (single host via nginx path-prefix proxy)

Host: `https://dev-api.isena.org`. Reverse-proxy config: `services/nginx/dev-api.isena.org.conf`.

| Public path prefix | Routes to internal | Notes |
|--------------------|---------------------|-------|
| `/voice/*` | sena-voice:8008 | 5-min `proxy_read_timeout` for long audio |
| `/onboarding/*` | sena-onboarding:8009 | WS upgrade enabled; 24h read timeout |
| `/case-review/*` | sena-case-review:8002 | WS upgrade enabled; 180s; 10m body |
| `/v1/restrictive-practices/*` | sena-case-review:8002 | Same backend as `/case-review/*` (separate prefix because no `/case-review/` prefix in path) |
| `/casenote/*` | sena-casenote-monthly:8004 | 1000s timeout (7 sequential Bedrock sections) |
| `/policy/*` | sena-policy-proc:8000 | 60s |
| `/staff/*` | sena-staff:8001 | SSE streaming |
| `/ai-chatbot/*` | sena-ai-chatbot:8003 | SSE; `proxy_buffering off` |
| `/ai-comm-log/*` | sena-ai-communication-log:8005 | |
| `/shift-summary/*` | sena-shift-summary:8006 | |
| `/text-extraction/*` | sena-ai-text-extraction:8007 | 120s (S3 fetch + Bedrock) |
| `/case-review-ui/*` | sena-case-review-ui:8501 | Streamlit, `proxy_buffering off`, 1h timeout |
| `/practices/*` | restrictive_practices-api-1:8084 | External container; resolves at request-time via Docker DNS |

## Auth conventions

```
X-Tenant-Id:  <uuid>
X-User-Id:    <uuid>
X-User-Roles: worker | staff | manager | admin | support_worker (comma-separated)
```

Per-service exceptions:
- `case_review` restrictive-practices evaluate: HTTP Basic.
- `policy_proc` admin endpoints: `X-API-Key` header.
- `casenote_monthly` all routes: `HTTPBearer`.
- `ai-communication-log`, `shift-summary`: `X-API-Key`.
- `ai-text-extraction` `/extract`: `Authorization: Bearer <JWT>` (HS256 or RS256).
- `ai_chatbot`: JWT signed with `JWT_SECRET`; downstream JWT forwarded to staff/policy.

## Per-service references

Open the matching OpenAPI spec for full route signatures, request/response schemas, security schemes, and server URLs.

| Service | Spec file |
|---------|-----------|
| voice | `openapi-specs/voice-openapi.json` (10 paths, 18 schemas) |
| onboarding | `openapi-specs/onboarding-openapi.json` (7 paths, 19 schemas) |
| case_review | `openapi-specs/case-review-openapi.json` (19 paths, 42 schemas) |
| casenote_monthly | `openapi-specs/casenote-monthly-openapi.json` (4 paths, 8 schemas) |
| policy_proc | `openapi-specs/policy-openapi.json` (11 paths, 9 schemas) |
| staff | `openapi-specs/staff-openapi.json` (4 paths, 3 schemas) |
| ai_chatbot | `openapi-specs/ai-chat-openapi.json` (3 paths, 3 schemas) |
| ai-communication-log | `openapi-specs/ai-communication-log-openapi.json` (2 paths, 8 schemas) |
| shift-summary | `openapi-specs/shift-summary-openapi.json` (1 path, 3 schemas) |
| ai-text-extraction | `openapi-specs/ai-text-extraction-openapi.json` (3 paths, 4 schemas) |

Service-specific rule files (autoload when editing that service): `.claude/rules/service-*.md`.

## WebSocket endpoints

Two services expose WS:

| WS path | Service | Protocol notes |
|---------|---------|----------------|
| `/ws/onboarding/{session_id}` | onboarding | Hello → ready → bidirectional Gemini Live audio + transcript events |
| `/ws/case-review/voice/{session_id}` | case_review | Same shape as onboarding; emits `turn_start`/`turn_complete`/`interrupted`/`user_said`/`agent_said`/`field_updated`/`state`/`step_completed`/`error` |

For full WS protocol detail see `.claude/rules/service-onboarding.md` and `.claude/rules/service-case-review.md`.

## Audit trail

- **`openapi-specs/*.json`** — current canonical specs.
- **`openapi-specs/*.json.bak`** — original hand-curated specs preserved (NOT deleted).
- **`openapi-specs/*.extracted.json`** — pure live-FastAPI dump (no merge), forensic reference.

Last refresh: 2026-06-18 (live introspection via `app.openapi()` per service).
