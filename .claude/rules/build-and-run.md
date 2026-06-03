---
paths:
  - "sena-ai/Makefile"
  - "sena-ai/pyproject.toml"
  - "sena-ai/docker-compose.yml"
  - "sena-ai/docker-compose.deploy.yml"
  - "sena-ai/services/*/pyproject.toml"
  - "sena-ai/services/*/Dockerfile"
  - "sena-ai/.pre-commit-config.yaml"
---

# Build & Run Commands

## Setup (per service — root pyproject has no dev extra)

```bash
cd sena-ai
cp .env.example .env                       # configure env vars
pip install -e shared                       # sena-common — REQUIRED first; usage logging / DB / middleware live here
pip install -e "services/voice[dev]"
pip install -e "services/onboarding[dev]"
pip install -e "services/case_review[dev]"
```

> **`pip install -e shared` is not optional.** No service declares `sena-common` as a dependency, so if you skip it, imports like `sena_common.usage_logger` silently fall into their `ImportError` fallback (e.g. `emit_usage` becomes a no-op stub → zero token usage reaches MongoDB). Always install `shared` before the services.

## Infrastructure

```bash
docker-compose up -d   # Redis + both Postgres DBs (ai-db @ 5433, shared-db @ 5434)
```

## Run services

```bash
cd services/voice       && uvicorn src.voice.main:create_app       --factory --reload --port 8082
cd services/onboarding  && uvicorn src.onboarding.main:create_app  --factory --reload --port 8083
cd services/case_review && uvicorn src.case_review.main:create_app --factory --reload --port 8084
```

## Tests (root pytest excludes active services — always pass explicit path)

```bash
pytest services/voice/tests/
pytest services/onboarding/tests/
pytest services/case_review/tests/
pytest services/voice/tests/test_file.py        # single file
pytest services/voice/tests -k "test_name"      # single test by name
```

## Lint + format + typecheck

```bash
ruff check src/                # lint
ruff check --fix src/          # autofix
ruff format src/               # format
mypy src/<service>/            # type check
pre-commit install             # one-time hook setup
```

## Windows / PowerShell

PowerShell 5.1 has no `&&` operator. Use `;` + `$?`:

```powershell
Set-Location sena-ai
Copy-Item .env.example .env
pip install -e shared                          # sena-common — REQUIRED first (see note above)
pip install -e "services/voice[dev]"
pip install -e "services/onboarding[dev]"
pip install -e "services/case_review[dev]"

# Run a service (sequential, $? checks exit code)
Set-Location services\voice; if ($?) { uvicorn src.voice.main:create_app --factory --reload --port 8082 }
```

## Health check URLs (local dev)

| Service | Port | Health | Swagger |
|---------|------|--------|---------|
| voice | 8082 | http://localhost:8082/health/live | http://localhost:8082/docs |
| onboarding | 8083 | http://localhost:8083/health | http://localhost:8083/docs |
| case_review | 8084 | http://localhost:8084/health | http://localhost:8084/docs |
