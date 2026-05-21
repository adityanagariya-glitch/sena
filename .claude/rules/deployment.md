---
paths:
  - "sena-ai/Dockerfile"
  - "sena-ai/docker-compose.deploy.yml"
  - "sena-ai/.env.deploy*"
  - "sena-ai/DEPLOY_EC2_CHECKLIST.md"
  - "sena-ai/services/onboarding/Dockerfile"
---

# Deployment — EC2 (Docker)

Full checklist: `sena-ai/DEPLOY_EC2_CHECKLIST.md`. This file is loaded when touching docker-compose / Dockerfile / .env.deploy.

## Abbreviated flow

```bash
# On EC2 box (Amazon Linux 2 / Ubuntu)
git clone <repo> && cd sena-ai
cp .env.deploy.example .env.deploy   # fill GEMINI_API_KEY, APP_WEBHOOK_URL, etc.
docker compose -f docker-compose.deploy.yml --env-file .env.deploy up -d
curl http://localhost:8083/health/live   # smoke test
```

## Deploy compose

`docker-compose.deploy.yml` runs two containers:
- `sena-onboarding` — onboarding service on port 8083 (published to host)
- `redis` — ephemeral session state, not exposed externally

## Key differences from local dev

- **No local Postgres** — app backend is DB of record; onboarding uses Redis only
- **Nginx reverse-proxy with TLS** expected in front (see checklist §5)
- `SENA_AI_REDIS_URL=redis://redis:6379/0` — uses docker network alias
- Image built from `sena-ai/services/onboarding/Dockerfile`

## Demo-grade shortcuts (FIX before any real environment)

Documented in checklist §7:
- No TLS termination inside container
- No secrets manager — env file on disk
- Single-node Redis (no persistence)

## Current state (2026-05-14)

Voice + onboarding deployed to EC2. Case review shelved at Phase C — not deployed.
