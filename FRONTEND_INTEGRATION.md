# SENA Backend — Frontend Integration Guide

Temporary **test** backend (a developer laptop behind a Cloudflare tunnel). Not production.
All three AI services sit behind **ONE** base URL; a reverse proxy routes by URL path.

---

# ⚡ START HERE — do these 2 things first, or nothing works

### 1. Point the app at THIS URL (not the old EC2 one)
```
https://bosc-sena-backend.loca.lt
```
If you see `SocketException: Connection reset … astride-supremacy-constant.ngrok-free.dev`,
the app is still on the OLD address. In the Flutter project, find/replace the base URL:
```
grep -rn "astride-supremacy-constant" .      # old EC2 ngrok — replace all
grep -rn "ngrok-free" .                        # also check here
```
Set it to `bosc-sena-backend.loca.lt`. WS base = `wss://bosc-sena-backend.loca.lt`.

### 2. Send these headers on EVERY request (or you get 401)
```
X-User-Id: dev
X-User-Roles: staff          # use: manager,admin  for approval endpoints
```
(No real JWT in this test env — `dev_header` auth. No `ngrok-skip` header needed — this is Cloudflare, no interstitial.)

> Do 1 + 2 and **onboarding + voice work immediately** — no Docker, no DB needed.

---

## Base URLs
| | URL |
|--|-----|
| HTTPS | `https://bosc-sena-backend.loca.lt` |
| WebSocket | `wss://bosc-sena-backend.loca.lt` |

## Required headers (all requests)
| Header | Value |
|--------|-------|
| `X-User-Id` | any id, e.g. `dev` |
| `X-User-Roles` | `staff` (or `manager,admin`) |
| `bypass-tunnel-reminder` | `true` (skips loca.lt reminder page) |
| `X-Tenant-Id` | (onboarding, recommended) tenant id |
| `X-Participant-Id` | (onboarding, recommended) participant id |
| `Content-Type` | `application/json` (except multipart/audio) |

---

# 1) Onboarding — voice participant onboarding

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/v1/onboarding/session` | Create session. Body: `participant_id`, `step`, `schema` (StepSchema), optional `bootstrap`, `initial_state`, `tenant_id`, `locale`. Returns `session_id`, `ws_url`. |
| GET | `/v1/onboarding/session/{id}/state` | Read FormState |
| PUT | `/v1/onboarding/session/{id}/state` | Write FormState (blocked while WS active) |
| POST | `/v1/onboarding/session/{id}/complete` | Finalize + fire webhook |
| WSS | `/ws/onboarding/{session_id}` | Live voice stream |
| GET | `/health/live`, `/health/ready` | Health |

**WebSocket flow (VERIFIED end-to-end — follow exactly):**
1. Build the WS URL yourself — do NOT use the `ws_url` from the `POST /session` response (it returns `ws://`/internal host and FAILS over the HTTPS tunnel). Use: `wss://bosc-sena-backend.loca.lt/ws/onboarding/{session_id}` (must be `wss://`).
2. Send header on the WS handshake: `bypass-tunnel-reminder: true` (loca.lt blocks the upgrade without it).
3. First frame after connect: `{"type":"hello","client_proto":"v2"}`.
4. **Speak first** — the model does NOT greet on its own (no proactive audio).
Audio in = PCM16 mono **16 kHz**; audio out = PCM16 mono **24 kHz**. Mute mic between `turn_start` and `turn_complete` (echo).
**Server -> client events** (handle all): `ready`, `turn_start`, `turn_complete`, `interrupted`, `user_said`, `agent_said`,
`field_updated`, `state`, `step_completed`, `row_added`, `repeatable_section_entered`, `repeatable_section_exited`,
`validation_rejection`, `field_advisory_warning`, `field_confirmed`, `go_away`, `resumable`, `error`.

# 2) Voice — case note dictation (Flow B, Bedrock + LiveKit)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/v1/voice/session` | Start dictation (returns LiveKit token) |
| POST | `/v1/voice/session/turn` | Process a voice turn |
| POST | `/v1/voice/session/end` | Compile case note + create approval item |
| GET | `/v1/voice/session/{id}` | Session status |
| POST | `/v1/voice/personal-details/session` (`/turn`,`/end`) | Personal-details voice flow |
| POST | `/v1/approval/decision` | Approve/reject (roles: manager/admin) |
| GET | `/health/live`, `/health/ready` | Health |

# 3) Case note — case_review (AI review / classify / incident)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/v1/case-review/context` | Fetch + rolling summary |
| POST | `/v1/case-review/classify` | Paragraph -> fields + reask prompts |
| POST | `/v1/case-review/review` | Risk / restrictive-practice / anomaly flags |
| POST | `/v1/case-review/incident/detect` / `/draft` | Incident detect / draft |
| PATCH | `/v1/case-review/incident/confirm` | Staff confirm |
| POST | `/v1/case-review/submit` | Final submit gate |

> ⚠️ case_review endpoints need a **Postgres DB** running on the backend. If you get a `500`
> with a DB connection error, ask the backend dev to start it (it''s off by default in this test env).

---

# Quick smoke test (paste into a terminal)
```bash
B=https://bosc-sena-backend.loca.lt
curl $B/                       # gateway -> 200 "SENA local backend..."
curl $B/health/live            # onboarding -> {"status":"ok"}
# onboarding + voice with auth headers:
curl -X POST $B/v1/voice/session -H "Content-Type: application/json" -H "X-User-Id: dev" -H "X-User-Roles: staff" -d "{}"
```

# Troubleshooting
| You see | Cause | Fix |
|---------|-------|-----|
| `Connection reset … astride…ngrok-free.dev` | App on OLD URL | START HERE #1 |
| `401 Unauthorized` | Missing auth headers | START HERE #2 |
| `404` on `/v1/<svc>/openapi.json` or `/v1/<svc>/health` | wrong path probing | health is `/health/live`; ignore openapi probes |
| `500` on `/v1/case-review/*` with DB error | backend DB not running | ask backend dev to start Postgres (case_review only) |
| onboarding `500` on create-session | known edge-case when the `schema` body is malformed | send a complete, valid `schema` object; valid bodies return `201` |

# Notes / caveats (test env)
- **The base URL changes if the backend tunnel restarts.** If everything suddenly "connection refused / 404 page", ask the backend dev for the new `trycloudflare.com` URL.
- Best-effort uptime — it''s a laptop behind a free tunnel. If the machine sleeps, it drops.
- Webhook calls to `mock.example.com` failing in backend logs are **expected** (placeholder) — ignore.
- Australian data-residency / production hardening are pre-prod concerns, not relevant to this test pass.