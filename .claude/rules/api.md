---
paths:
  - "sena-ai/services/*/src/*/api/**/*.py"
---

# API Route Rules (path-scoped)

Loads ONLY when an edit touches a FastAPI route or WebSocket handler under any service's `api/` directory.

## Request validation
- Every body / query / path is a Pydantic v2 model. No raw `dict` bodies.
- Models live in `models/schemas.py` (or `models/<feature>.py`) — never inline in route files.
- Use `model_validate()` / `model_dump()`. NEVER `.dict()` or `.parse_obj()` (v1 API).

## Settings & secrets
- Settings come from `core/settings.py` via `Depends(get_settings)` — never `os.environ` directly.
- Tenant context: extract via the dependency that matches `SENA_AI_AUTH_MODE`, never reach into `request.headers` directly.
- Never log a setting value that contains a secret (GEMINI_API_KEY, APP_WEBHOOK_SECRET, DB URLs).

## Auth
- Every route requires `Depends(require_auth)` (or whatever the service's per-route auth dependency is).
- WebSocket routes: validate `session_id` against tenant claim BEFORE the upgrade. No unauthenticated WS upgrades — that is a tenant-isolation breach.

## Response shapes
- Use `response_model=` on every route. Never return raw ORM objects.
- Errors: `HTTPException` with structured `detail: {"code": "...", "message": "..."}`. No bare strings.

## Logging
- structlog only. Never `print()`. Pattern: `log.info("event_name", session_id=sid, tenant_id=tid)`.
- For WS emit payloads that cross to the browser: strip tenant_id (defense in depth). Server-side logs still include it.

## Size & rate limits
- WebSocket frames: enforce `SCREEN_STATE_MAX_BYTES` BEFORE Pydantic parse to prevent memory exhaustion via a giant `screen_state` payload.
- Audio chunks: bounded ring buffer only. Never an unbounded list for streaming data.

## Lifecycle
- Async-first. No sync calls in async route handlers.
- Acquire DB sessions per-request, release on response. Never share across requests.
- Background tasks: only for fire-and-forget (webhook delivery). NEVER for state mutations the response depends on.

## SENA WebSocket events (server → client) — canonical list

Emitted from `services/onboarding/src/onboarding/services/{tools.py, gemini_live.py}` and `api/ws_routes.py`. Flutter must handle every event type; an unhandled type in `default` arm must log WARN (silent `null` is the anti-AP-5 from the audit playbook).

| Event | Source | Payload | Flutter contract |
|-------|--------|---------|------------------|
| `ready` | `ws_routes.py` | `{state, prompt_version, coverage}` | Session live, start mic |
| `turn_start` | `gemini_live.py` | — | Start playback; set `_agentSpeaking=true` (mic mute) |
| `turn_complete` | `gemini_live.py` | — | Set `_agentSpeaking=false` |
| `interrupted` | `gemini_live.py` | — | Clear audio queue; set `_agentSpeaking=false` |
| `user_said` | `gemini_live.py` | `{text}` | Input transcript |
| `agent_said` | `gemini_live.py` | `{text}` | Output transcript |
| `field_updated` | `tools.py` | `{section, field, value, repeatable_index, confidence, source?, auto_copied_from?}` | Patch local state with `source` + `auto_copied_from` keys |
| `state` | `tools.py` | full FormState snapshot | Reconcile |
| `step_completed` | `tools.py` | `{webhook_delivered}` | Show success, close session |
| `escalated` | `tools.py` | `{reason, transcript_excerpt}` | Show calm acknowledgement |
| `row_added` | `tools.py` | `{section_id, new_index}` | Render empty card |
| `repeatable_section_entered` | `tools.py` | `{section_id, intent, row_index}` | Highlight focused row |
| `repeatable_section_exited` | `tools.py` | `{section_id}` | Release focus |
| `validation_rejection` | `tools.py` / `gemini_live.py` | `{section_id, field_id?, code, reason_human, repeatable_index?}` | Inline error display |
| `field_advisory_warning` | `tools.py` | `{section_id, field_id, repeatable_index?, code, reason_human, severity: "advisory", suggested_fix?, allowed_values?}` | Inline non-blocking hint; field written to state; agent acks once then moves on |
| `field_confirmed` | `tools.py` | `{section_id, field_id, repeatable_index?, value, confirmation_source: "voice", turn_id}` | Mark field user-confirmed this session; trigger local screen-save; emitted ≤ once per (section, field, row) per WS session |
| `field_skipped_warning` | `tools.py` | `{section_id, field_id, reason}` | Banner + highlight |
| `schema_drift_detected` | `tools.py` | `{...}` | Inline notice + refresh strategy |
| `go_away` | `gemini_live.py` | `{time_left_ms}` | Call resume endpoint within N ms |
| `resumable` | `ws_routes.py` | `{handle, ttl_sec}` | Store handle for resume |
| `error` | any | `{code, message}` | Handle or close |

When adding a NEW event type:
1. Update `flutterhandoffdev.md` with a new section documenting the typed contract (payload shape, Flutter handler, AppStrings key if spoken text differs from on-screen).
2. Add a regression test that asserts the emit fires under the trigger condition.
3. Add the row to this table.
4. Confirm the Flutter `default` arm of `VoiceEventModel.parse` still logs WARN, never silently returns `null`.
