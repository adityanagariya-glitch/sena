# SENA Backend — Frontend Integration (local test via ngrok)

All three SENA AI services are exposed behind **ONE** ngrok URL (a local reverse proxy routes by path).
This is a temporary test backend running on a developer machine — not production.

## Base URL

```
https://grey-spiritual-simon-injection.trycloudflare.com
```
WebSocket base: `wss://grey-spiritual-simon-injection.trycloudflare.com`

> The URL may change if the tunnel restarts — confirm the current one with the backend dev.

## Required headers (send on EVERY request)

| Header | Value | Why |
|--------|-------|-----|
| `(none needed)` | — | cloudflared has no interstitial (drop the old ngrok-skip header) |
| `X-User-Id` | `<user id>` | Auth (dev_header mode) |
| `X-User-Roles` | e.g. `staff` or `manager,admin` | Auth/role gates |

Onboarding state endpoints also accept (recommended for tenant isolation):
| `X-Tenant-Id` | `<tenant id>` |
| `X-Participant-Id` | `<participant id>` |

---

## 1) Onboarding (voice participant onboarding)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/v1/onboarding/session` | Create session (body: participant_id, step, schema, bootstrap, tenant_id) -> returns `session_id`, `ws_url` |
| GET | `/v1/onboarding/session/{id}/state` | Read FormState |
| PUT | `/v1/onboarding/session/{id}/state` | Write FormState (blocked while WS active) |
| POST | `/v1/onboarding/session/{id}/complete` | Finalize + fire webhook |
| WSS | `/ws/onboarding/{session_id}` | Live voice stream (Gemini Live) |
| GET | `/health` | Health |

**WebSocket:** connect to `wss://.../ws/onboarding/{session_id}`, first frame `{"type":"hello","client_proto":"v2"}`.
Server -> client events to handle: `ready`, `turn_start`, `turn_complete`, `interrupted`, `user_said`, `agent_said`,
`field_updated`, `state`, `step_completed`, `row_added`, `validation_rejection`, `go_away`, `resumable`, `error`.
Audio in: PCM16 mono 16kHz. Audio out: PCM16 mono 24kHz. Mute mic while `turn_start`..`turn_complete` (echo).

## 2) Voice (Flow B — case note dictation, AWS Bedrock + LiveKit)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/v1/voice/session` | Start dictation session (returns LiveKit token) |
| POST | `/v1/voice/session/turn` | Process a voice turn (transcript -> draft update) |
| POST | `/v1/voice/session/end` | Compile case note + create approval item |
| GET | `/v1/voice/session/{id}` | Session status |
| POST | `/v1/voice/personal-details/session` (`/turn`, `/end`) | Personal-details voice flow (Gemini Live) |
| POST | `/v1/approval/decision` | Approve/reject case note (manager/admin only) |
| GET | `/health/live`, `/health/ready` | Health |

## 3) Case note (case_review — AI review/classify/incident)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/v1/case-review/context` | Fetch + rolling summary |
| POST | `/v1/case-review/classify` | Paragraph -> fields + reask prompts |
| POST | `/v1/case-review/review` | Risk / restrictive-practice / anomaly flags |
| POST | `/v1/case-review/incident/detect` | Detect incident |
| POST | `/v1/case-review/incident/draft` | Draft incident report |
| PATCH | `/v1/case-review/incident/confirm` | Staff confirm |
| POST | `/v1/case-review/submit` | Final submit gate |
| GET | `/health` | Health |

---

## Quick smoke test
```bash
# gateway alive -> 200 "SENA local backend..."
curl https://grey-spiritual-simon-injection.trycloudflare.com/
# onboarding alive -> {"status":"ok"}
curl https://grey-spiritual-simon-injection.trycloudflare.com/health/live
# case note routing (422 without a real body, but proves it reaches case_review)
curl -X POST https://grey-spiritual-simon-injection.trycloudflare.com/v1/case-review/context -H "Content-Type: application/json" -H "X-User-Id: dev" -H "X-User-Roles: staff" -d "{}"
```

## Notes / caveats (test env)
- Backend is a developer laptop behind ngrok — availability is best-effort; expect occasional restarts.
- Some endpoints need a live DB (Postgres) / external services and may return 5xx if those aren''t up locally.
- Interactive API docs per service (if reachable): append `/docs` after the relevant path is proxied, or ask backend dev for the OpenAPI JSON.
- Auth is `dev_header` (no real JWT) — just send `X-User-Id` + `X-User-Roles`.