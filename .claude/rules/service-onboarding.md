---
paths:
  - "sena-ai/services/onboarding/**/*.py"
  - "sena-ai/services/onboarding/**/*.md"
  - "sena-ai/services/onboarding/Dockerfile"
  - "sena-ai/services/onboarding/pyproject.toml"
---

# Onboarding Service — voice-driven participant onboarding (port 8083)

API-first service at `sena-ai/services/onboarding/src/onboarding/`. Mobile app integrates; no frontend shipped. **Redis-only state — no Postgres.** App backend is DB of record; we own ephemeral state with TTL.

## Layer map

| Layer | Path | Purpose |
|-------|------|---------|
| API | `api/routes.py` | REST: session lifecycle, state, webhook fire |
| API | `api/ws_routes.py` | WebSocket: start handshake, WS lock, Gemini bridge, error close codes |
| Services | `services/gemini_live.py` | Gemini Live bridge: b2g/g2b tasks, transcript events, WS↔Gemini audio, screen_state inject |
| Services | `services/prompt_builder.py` | System prompt renderer: schema + FormState + grounding/resume context |
| Services | `services/tools.py` | Tool dispatcher: update_field, get_session_context, advance_step (idempotent), escalate_incident |
| Services | `services/screen_context.py` | Pure: ScreenStateMessage validation + render_injection_text + payload_hash |
| Services | `services/grounding.py` | Pure: build_live_tools — function_declarations + optional GoogleSearch |
| Services | `services/resumption.py` | Redis-backed: issue_handle, redeem_handle (GETDEL single-use), build_replay_context |
| Services | `services/webhook.py` | Outbound webhook to app backend, 3-retry exp backoff |
| Services | `services/cross_screen_context.py` | Pure: build_summary, compress_residual/decompress, render_for_prompt |
| Services | `services/coverage.py` | Pure: voice coverage eligibility (is_eligible, is_repeatable_eligible, coverage_paths) |
| Services | `services/field_apply.py` | Pure: build_envelope — wraps field updates with coverage + confidence + row_index |
| Services | `services/validators/` | Pure no-IO validators: field_rules, cross_field, sequencing — raises `ValidationRejection` |
| Repositories | `repositories/state_repo.py` | Redis only. FormState, transcript, WS lock, resumption handles. `assert_session_owner` for cross-tenant isolation. |
| Repositories | `repositories/user_context_repo.py` | Redis only. Per-(tenant_id, participant_id) cross-screen bucket: step summaries (Hash) + session-id index (Set), 7-day TTL refreshed on every write |
| Models | `models/schema_spec.py` | StepSchema, SectionSpec, FieldSpec (incl. visible_if, repeatable) |
| Models | `models/form_state.py` | FormState, FieldValue, CompletionStats |
| Models | `models/session_bootstrap.py` | SessionBootstrap envelope (Rule 1+2 hygiene contract); rendered into prompt as `[LIVE_STATE_JSON]` |
| Models | `models/cross_screen_summary.py` | StepSummary + CrossScreenContext; verbatim vs compressed split |
| Fixtures | `fixtures/schema_*.json` | 5 step schemas from real app screens |

## Key routes
- `POST /v1/onboarding/session` — create session (app sends schema inline)
- `GET/PUT /v1/onboarding/session/{id}/state` — read/write FormState (PUT blocked when WS active)
- `POST /v1/onboarding/session/{id}/complete` — finalize + fire webhook
- `WSS /ws/onboarding/{session_id}` — voice stream

## WS server→client events (Flutter must handle all)

| Event | Payload | Action |
|-------|---------|--------|
| `ready` | `{state, prompt_version, coverage}` | Session live, start mic |
| `turn_start` | — | Gemini began speaking, start playback |
| `turn_complete` | — | Gemini finished turn |
| `interrupted` | — | User barged in, clear audio queue |
| `user_said` | `{text}` | Input transcript |
| `agent_said` | `{text}` | Output transcript |
| `go_away` | `{time_left_ms}` | **Gemini session closing — call resume endpoint before expiry** |
| `resumable` | `{handle, ttl_sec}` | App-level resume handle |
| `error` | `{code, message}` | Handle or close |

## Design decisions
- One WS session = one onboarding step (clean resumption semantics)
- App backend owns schema + final DB; we own ephemeral Redis state
- Voice holds write lock during WS; app PUTs only when WS closed
- No Postgres — Redis TTL only

## Run
```bash
cd sena-ai/services/onboarding
uvicorn src.onboarding.main:create_app --factory --reload --port 8083
```

## Env vars (`SENA_AI_` prefix)
`GEMINI_API_KEY`, `GEMINI_LIVE_MODEL_ID`, `ONBOARDING_PORT`, `APP_WEBHOOK_URL`, `APP_WEBHOOK_SECRET`, `REDIS_URL`, `ONBOARDING_GROUNDING_ENABLED` (default false), `ONBOARDING_CROSS_SCREEN_CONTEXT_ENABLED` (default true — controls per-(tenant_id, participant_id) bucket reads/writes; rollback flag), `SCREEN_STATE_MAX_BYTES` (default 8192), `RESUMPTION_HANDLE_TTL_SEC` (default 600), `RESUMPTION_REPLAY_TURNS` (default 4)
