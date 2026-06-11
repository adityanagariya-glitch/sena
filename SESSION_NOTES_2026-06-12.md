# SENA — Session Notes (2026-06-11/12)

What was done this session: env consolidation, dead-code cleanup, onboarding merge-conflict repair,
EC2 case-note-drafter recovery, local 3-service test setup, and a frontend test backend behind a tunnel.

---

## 1. Environment (.env)
- Consolidated all service config into the **root `SENA/.env`** (UTF-8, no BOM; gitignored — holds live secrets).
- Fixed `services/voice/core/settings.py`: `env_file=["../../.env",".env"]` + `extra="ignore"` so voice reads the shared root `.env` and ignores other services'' keys.
- Added **bare** `GEMINI_API_KEY/MODEL_ID/LIVE_MODEL_ID` (voice uses `Field(alias=...)` which bypasses the `SENA_AI_` prefix).

## 2. Dead config removed (committed)
Removed unused settings fields (grep + ruff verified, services still boot):
- onboarding: `onboarding_session_ttl_min`+`session_ttl_sec`, `onboarding_resumption_ttl_min`+`resumption_ttl_sec`, `onboarding_frame_fps_limit`, `voice_coverage_enforced`, `onboarding_voice_validation_advisory`, `field_apply_log_level`
- voice: `max_concurrent_sessions_per_user`
- Commits: checkpoint `962639d`, deletion `3c74186`.

## 3. Onboarding merge-conflict repair
`api/routes.py`, `api/ws_routes.py`, `services/prompt_builder.py` had **committed Git conflict markers** (shipped broken in `3f98994`). Restored `routes.py`/`ws_routes.py` from clean `ddb5500`; de-duplicated `prompt_builder.py` (kept the V1 `TurnPayload`/modular-prompt design, dropped the older `__SCHEMA_JSON__` module). Onboarding boots again.

## 4. EC2 — case-note drafter (restrictive_practices, /draft/audio)
- ngrok tunnel was down (`ERR_NGROK_3200`) — it's a host process, not a container; restarted under tmux.
- Container was stale + missing deps: added `redis`, `structlog`, `google-genai` to `requirements.txt`; rebuilt.
- Amazon Transcribe failures fixed: IAM user `keval.shah.sena` needed `transcribe:StartTranscriptionJob`; bucket `test-dev-sena` is in `ap-south-1`, so set `S3_REGION=ap-south-1` (S3 + Transcribe must match region).
- Result: `/v1/restrictive-practices/draft/audio` returns 200 for real speech.
- ⚠️ Pre-prod: `ap-south-1` = data outside Australia (NDIS APP 8) — move the transcription bucket to `ap-southeast-2` before go-live.

## 5. Local 3-service test setup (Windows)
| Service | Port | Run from |
|---------|------|----------|
| voice | 8082 | `services\voice` |
| onboarding | **8090** (8083 was held by a ghost process) | `services\onboarding` |
| case note (case_review) | 8084 | `services\case_review` |
- Per-service venvs (`services\<svc>\.venv`). Each runs from its OWN folder + OWN venv.
- Python 3.13 wheel fixes for case_review-style installs: relax `pymupdf` -> `>=1.25`, `asyncpg` -> `>=0.30` (old pins have no 3.13 wheel and fail to compile on Windows).
- Redis = remote upstash (no local Redis needed for onboarding). voice + case_review DB endpoints need local Postgres (`docker compose up -d ai-db shared-db` — Docker Desktop must be running).

## 6. Frontend test backend (one URL, all 3 services)
- **Caddy** reverse proxy on `:8000` routes by path: `/v1/voice*`+`/v1/approval*`->8082, `/v1/onboarding*`+`/ws/onboarding*`->8090, `/v1/case-review*`->8084 (handles WebSocket). Config: `Caddyfile`.
- Tunnel: cloudflared quick-tunnel kept dropping (laptop sleep/WiFi -> new URL each time). Switched to **localtunnel** with a fixed subdomain: **`https://bosc-sena-backend.loca.lt`** (stable across restarts).
- Handoff doc: **`FRONTEND_INTEGRATION.md`** (base URL, headers, all endpoints, WS contract, troubleshooting).

### Frontend must do
1. Base URL -> `https://bosc-sena-backend.loca.lt`
2. Headers: `X-User-Id`, `X-User-Roles`, `bypass-tunnel-reminder: true`
3. Voice WS: connect `wss://bosc-sena-backend.loca.lt/ws/onboarding/{session_id}` (build it yourself, NOT the response `ws_url`), send `bypass-tunnel-reminder` header + `{"type":"hello","client_proto":"v2"}`, then **speak first** (no auto-greeting).

## 7. Verified
- All 3 services boot locally; Caddy + localtunnel pass HTTP **and** WebSocket end-to-end (tested `wss://bosc-sena-backend.loca.lt/ws/onboarding/...` -> server replied).
- Voice "silence" was an **app-side** WS issue (wrong scheme / missing bypass header), not the backend.

## 8. Git
- Commits on `ai-services`: `cec14d5` (Caddyfile + docs + sentrux), `aeab45b`/`05326ec` (frontend doc).
- A teammate had force-pushed a restructure to `origin/ai-services`; per decision, **force-pushed local working code over it** (`05326ec`). Their version is backed up locally at branch `backup/teammate-restructure-2026-06-12` (`32c07f4`).
- Anyone with the old branch must `git fetch` + `git reset --hard origin/ai-services` to resync.

## Keep running while the FE dev tests
5 windows: voice (8082) · onboarding (8090) · case note (8084) · Caddy (8000) · localtunnel. If the laptop sleeps or WiFi drops, the tunnel goes down (recovers on the SAME URL when back).

## Outstanding / pre-prod
- Onboarding `schema` body-field collides with Pydantic `.schema()` -> intermittent 500 on malformed bodies (documented, not patched).
- case_review DB endpoints need Postgres + `alembic upgrade head`.
- Transcription bucket must move to `ap-southeast-2` (NDIS data residency) before production.
- `restrictive_practices/` local copy is stale; its real home is the `onboarding_casenote` branch.