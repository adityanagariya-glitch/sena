# AWS Deployment Plan — Restrictive Practices Demo (existing EC2)

## Context

The NDIS restrictive-practice detection pipeline is verified working locally (FastAPI + Postgres/pgvector + Gemini). Client demo coming up. **An EC2 instance already exists in the account with the other backend deployed** — so we just piggy-back on it. No new infrastructure.

**Deployment shape:** SSH onto the existing EC2 → run our API + Postgres in `docker-compose` → expose through whatever reverse proxy is already there (nginx most likely) → done.

This is a demo, not production. Keep it small.

Legend: 🛠️ **MANUAL** = you do it. 🤖 **AUTO** = a script/command does it.

---

## Phase 0 — Tiny code prep (LOCAL)

| # | File | Change | Why |
|---|------|--------|-----|
| 0.1 | `requirements.txt` | Pin `google-genai>=1.74.0` (currently `>=0.8.0`) | Lower SDK lacks `thinking_budget` → triage will 500 |
| 0.2 | `Dockerfile` | NEW — `python:3.12-slim` base, copy repo + `pdfs/`, `pip install -r requirements.txt`, run uvicorn on `0.0.0.0:8084` | Container needs a build recipe |
| 0.3 | `.dockerignore` | NEW — exclude `.venv`, `.env`, `__pycache__`, `.claude`, `archive`, `wiki`, `graphify-out` | Smaller image, no leak |
| 0.4 | `docker-compose.prod.yml` | NEW — two services: `api` (built from Dockerfile) and `db` (`pgvector/pgvector:pg16`). API depends on DB. Both on a shared bridge network. Persistent volume for DB | One-command stack |
| 0.5 | `main.py:24` | Change `allow_origins=["*"]` → `["https://<demo-host>"]` | CORS hygiene |
| 0.6 | `api/routes.py` | Add a tiny HTTP Basic auth dependency on `/evaluate` and `/demo`, reading user/pass from env vars | Public URL needs minimal auth |
| 0.7 | Commit + push to your git remote (private branch fine) | n/a | EC2 will `git pull` |

Reuse as-is (no edit needed): `db/session.py:create_tables()` (creates pgvector ext + HNSW index on startup), `scripts/ingest_ndis_policies.py` (idempotent), `scripts/seed_demo.py`, `demo_ui.html`, `pipeline/webhook.py`.

---

## Phase 1 — Inspect what's already on the EC2

| # | Step | Mode |
|---|------|------|
| 1.1 | SSH into EC2: `ssh ec2-user@<ip>` (or whatever user) | 🛠️ MANUAL |
| 1.2 | Check if Docker is installed: `docker --version && docker compose version`. If missing → `sudo dnf install -y docker && sudo systemctl enable --now docker && sudo usermod -aG docker $USER` then re-login | 🛠️ MANUAL |
| 1.3 | Check what reverse proxy fronts the other backend: `sudo nginx -T 2>/dev/null \| head -50` (or `ps aux \| grep -E 'nginx\|caddy\|apache'`) | 🛠️ MANUAL |
| 1.4 | Find a free port for our API to bind on `127.0.0.1` (default plan: `127.0.0.1:8084`). Confirm it's not already used: `sudo ss -tlnp \| grep 8084` (should be empty) | 🛠️ MANUAL |
| 1.5 | Check the security group on this EC2 — confirm port 443 is open to public, port 5432 is NOT (we'll keep DB internal to docker network) | 🛠️ MANUAL |

---

## Phase 2 — Pull code onto the EC2

| # | Step | Mode |
|---|------|------|
| 2.1 | Pick a directory: `mkdir -p ~/sena-rp && cd ~/sena-rp` | 🛠️ MANUAL |
| 2.2 | `git clone <repo-url> .` (or `git pull` if already cloned). If repo is private, set up a deploy key first | 🛠️ MANUAL |
| 2.3 | `cd restrictive_practices` — this becomes the working dir | 🛠️ MANUAL |

---

## Phase 3 — Configure secrets on the server

| # | Step | Mode |
|---|------|------|
| 3.1 | `cp .env.example .env` (or create a fresh `.env`) and `chmod 600 .env` | 🛠️ MANUAL |
| 3.2 | Fill `.env` with: `SENA_AI_GEMINI_API_KEY=<AI Studio key>`, `SENA_AI_RP_DATABASE_URL=postgresql+asyncpg://sena_ai:sena_ai@db:5432/sena_ai`, `SENA_AI_EMBEDDING_MODEL=gemini-embedding-2`, `SENA_AI_TRIAGE_MODEL=gemini-3-flash-preview`, `SENA_AI_EVALUATOR_MODEL=gemini-3.1-pro-preview`, `SENA_AI_BASIC_AUTH_USER=demo`, `SENA_AI_BASIC_AUTH_PASSWORD=<pick a password>`, `SENA_AI_GCP_PROJECT=` (empty → AI Studio mode) | 🛠️ MANUAL |
| 3.3 | Note the DB host is `db` (the docker-compose service name), not `localhost` — both services on the same docker bridge network | 🛠️ MANUAL |

---

## Phase 4 — Bring up the stack

| # | Step | Mode |
|---|------|------|
| 4.1 | `docker compose -f docker-compose.prod.yml up -d --build` | 🤖 AUTO |
| 4.2 | Watch startup logs: `docker compose -f docker-compose.prod.yml logs -f api`. Wait for `Application startup complete` and confirm `DB tables ready.` (no DB-not-reachable warnings) | 🛠️ MANUAL |
| 4.3 | Local smoke test from the EC2: `curl -u demo:<pwd> http://127.0.0.1:8084/v1/restrictive-practices/health` → expect `{"status":"ok",...}` | 🛠️ MANUAL |

---

## Phase 5 — Ingest NDIS policies + seed demo BSPs (one-shot)

| # | Step | Mode |
|---|------|------|
| 5.1 | `docker compose -f docker-compose.prod.yml exec api python scripts/ingest_ndis_policies.py` (PDFs are baked into the image — no upload needed) | 🤖 AUTO |
| 5.2 | `docker compose -f docker-compose.prod.yml exec api python scripts/seed_demo.py` | 🤖 AUTO |
| 5.3 | Verify chunk count: `docker compose -f docker-compose.prod.yml exec db psql -U sena_ai -d sena_ai -c "SELECT document_type, COUNT(*) FROM rp_ndis_policy_chunks GROUP BY document_type;"` → expect ~400 chunks | 🛠️ MANUAL |
| 5.4 | Verify BSPs: `... -c "SELECT client_id, practice_type, status FROM behaviour_support_plans;"` → expect 4+ rows | 🛠️ MANUAL |

---

## Phase 6 — Wire it into the existing reverse proxy

Pick whichever matches what's already running on the box.

### If nginx is the reverse proxy:

| # | Step | Mode |
|---|------|------|
| 6.1 | Pick a path or subdomain. Easiest: subpath under existing domain — e.g. `https://<existing-host>/sena-rp/` | 🛠️ MANUAL |
| 6.2 | Add a `location` block to the existing nginx server config: `location /sena-rp/ { proxy_pass http://127.0.0.1:8084/; proxy_set_header Host $host; proxy_set_header X-Real-IP $remote_addr; proxy_read_timeout 60s; }` | 🛠️ MANUAL |
| 6.3 | `sudo nginx -t && sudo systemctl reload nginx` | 🛠️ MANUAL |
| 6.4 | Test: `curl -u demo:<pwd> https://<existing-host>/sena-rp/v1/restrictive-practices/health` | 🛠️ MANUAL |

### If subdomain instead of subpath (cleaner, needs DNS + cert):

| # | Step | Mode |
|---|------|------|
| 6.1 | Add A record `demo-rp.<yourdomain>` → EC2 public IP | 🛠️ MANUAL |
| 6.2 | Issue cert: `sudo certbot --nginx -d demo-rp.<yourdomain>` (if certbot is already installed for the other backend) | 🛠️ MANUAL |
| 6.3 | New nginx server block proxying everything to `127.0.0.1:8084` | 🛠️ MANUAL |

---

## Phase 7 — End-to-end demo verification (do this 24h before client meeting)

| # | Step | Expected |
|---|------|----------|
| 7.1 | Open `https://<host>/sena-rp/demo` in browser → basic-auth prompt → UI loads | UI visible |
| 7.2 | Click **Clean shift** chip → Analyse | Verdict: CLEAR, ~2s |
| 7.3 | Click **Physical restraint** chip → Analyse | Verdict: UNAUTHORISED, alert required, reasoning quotes the note |
| 7.4 | Click **Chemical restraint** chip → switch client_id internally to `client-demo-chem` if your UI hardcodes `client-demo-unauth` (or just verify the UNAUTHORISED path works) | Verdict produced |
| 7.5 | Click **Seizure med** chip → Analyse | Verdict: NO INCIDENT DETECTED |
| 7.6 | Tail logs during the test: `docker compose -f docker-compose.prod.yml logs -f api` | No ERROR / WARN / JSON parse failures |
| 7.7 | Confirm audit rows landing: `... -c "SELECT count(*) FROM rp_case_note_runs;"` after each run | Increments by 1 |
| 7.8 | If evaluator 404s on `gemini-3.1-pro-preview`: edit `.env` → `SENA_AI_EVALUATOR_MODEL=gemini-3-flash-preview`, then `docker compose -f docker-compose.prod.yml up -d` to reload | Fallback works (Issue 0008) |

---

## Phase 8 — Cost / cleanup

EC2 already running for the other backend → marginal cost is **near-zero** (~50 MB extra RAM, a few % CPU during a request). Just remember to:

| # | Step | Mode |
|---|------|------|
| 8.1 | After demo: optionally `docker compose -f docker-compose.prod.yml down` to stop containers (keep volume — has the ingested PDFs) | 🛠️ MANUAL |
| 8.2 | If demo is permanently done: `docker compose -f docker-compose.prod.yml down -v` (removes volume too) and `docker image prune -a` | 🛠️ MANUAL |

---

## Critical files to touch

| Path | Change type |
|------|-------------|
| `restrictive_practices/Dockerfile` | NEW |
| `restrictive_practices/.dockerignore` | NEW |
| `restrictive_practices/docker-compose.prod.yml` | NEW (two services: api + db) |
| `restrictive_practices/requirements.txt` | EDIT — pin `google-genai>=1.74.0` |
| `restrictive_practices/main.py` | EDIT — lock CORS to demo host |
| `restrictive_practices/api/routes.py` | EDIT — add HTTP Basic auth dependency |

Existing assets reused (no rewrites):
- `main.py:create_app()` — factory pattern
- `db/session.py:create_tables()` — runs pgvector + HNSW index creation on startup
- `scripts/ingest_ndis_policies.py` — idempotent (`ON CONFLICT DO UPDATE`)
- `scripts/seed_demo.py` — seeds 4 BSPs covering all auth paths
- `demo_ui.html` + `/demo` route in `main.py` — already wired
- `pdfs/*.pdf` — 5 NDIS PDFs already in repo, baked into image by Dockerfile
- `pipeline/webhook.py` — only fires when `alert_required=True`

---

## Known gotchas (already documented in `.claude/issues-solved/`)

- `google-genai>=1.74.0` required for `thinking_budget` (Issue 0007)
- AI Studio embedding model = `gemini-embedding-2`, Vertex = `gemini-embedding-001` — mismatch = 404 (Issue 0009)
- `gemini-3.1-pro-preview` may 404 in some regions; flash fallback always works (Issue 0008)
- `SettingsConfigDict(extra="ignore")` is intentional — shared `.env` has other module keys (Issue 0011)
- Ingest-time and query-time embedding models MUST match — re-run ingest if you swap models
- `document.evaluate` exists on `document` — never use `onclick="evaluate()"` in the UI (already fixed)

---

## Out of scope

- Separate RDS — overkill for demo, Postgres-in-docker is fine
- ECR / Copilot / Fargate — not needed when you have an EC2 already running
- ACM cert from scratch — reuse the cert nginx already has for the other backend
- CI/CD — `git pull && docker compose up -d --build` is enough for a demo
- Cognito / OIDC — HTTP Basic is fine for a one-off client demo
