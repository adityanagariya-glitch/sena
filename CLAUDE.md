# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SENA is an AI-powered multi-tenant SaaS platform for Australian NDIS service providers. This repo contains the **AI/ML backend layer only** — the broader platform (HR, payroll, shifts, client management) is built by a separate client team. No API contracts exist yet between the two teams.

**Domain:** NDIS (National Disability Insurance Scheme) — Australian disability services compliance, case note drafting, voice-based workflows.

**Hard constraints:** Multi-tenant data isolation (legally mandated), human-in-the-loop approval for all AI outputs, Australian data residency, NDIS compliance.

## Architecture

Monorepo at `sena-ai/` with Python microservices. Currently one active service (voice), one scaffolded (ocr).

```
sena-ai/
├── services/
│   ├── voice/          # Active — Flow B case note dictation
│   └── ocr/            # Scaffolded, not yet implemented
├── shared/             # sena-common shared library (DB, middleware, schemas)
├── docker-compose.yml  # Redis + 2x PostgreSQL (ai-db with pgvector, shared-db)
├── .env.example        # All env vars with SENA_AI_ prefix
└── pyproject.toml      # Workspace root — ruff, mypy, pytest config
```

### Voice Service (Flow B) — the primary active service

Layered architecture at `sena-ai/services/voice/src/voice/`:

| Layer | Path | Purpose |
|-------|------|---------|
| API | `api/routes.py` | FastAPI endpoints, request orchestration |
| API | `api/deps.py` | Dependency injection (DB sessions, Redis client) |
| Services | `services/` | Business logic (dictation, approval, personal details, auth, transcription, Bedrock LLM, LiveKit, Redis state, SNS events) |
| Repositories | `repositories/voice_repo.py` | All database queries via SQLAlchemy async |
| Models | `models/db.py` | SQLAlchemy ORM entities |
| Models | `models/schemas.py` | Pydantic request/response models |
| Prompts | `prompts/` | LLM prompt templates for dictation and personal details |
| Config | `core/settings.py` | Pydantic-settings with `SENA_AI_` env prefix |

### Key API routes (all require auth)

- `POST /v1/voice/session` — start dictation session (creates LiveKit token)
- `POST /v1/voice/session/turn` — process a voice turn (transcript → Bedrock → draft update)
- `POST /v1/voice/session/end` — compile case note, create approval item, publish SNS event
- `GET /v1/voice/session/{id}` — session status
- `POST /v1/voice/personal-details/session[/turn|/end]` — parallel personal details flow
- `POST /v1/approval/decision` — approve/reject case note (manager/admin only)
- `GET /health/live`, `GET /health/ready` — health checks

### External dependencies

- **AWS Bedrock** (Claude 3.5 Sonnet) — LLM for case note generation
- **AWS SNS** — event publishing for case note lifecycle
- **LiveKit** — real-time voice conferencing
- **Redis** — session state, rate limiting, distributed locks
- **PostgreSQL + pgvector** (ai-db, port 5433) — voice session/case note data
- **PostgreSQL** (shared-db, port 5434) — cross-service platform data

## Build & Run Commands

```bash
# Setup
cd sena-ai
pip install -e ".[dev]"                    # workspace install (from sena-ai/)
cp .env.example .env                       # configure env vars

# Infrastructure
docker-compose up -d                       # Redis + both Postgres DBs

# Run voice service
cd services/voice
uvicorn src.voice.main:create_app --factory --reload --port 8082

# Tests
pytest                                     # all tests (from sena-ai/)
pytest services/voice/tests/               # voice service only
pytest services/voice/tests/test_file.py   # single test file
pytest -k "test_name"                      # single test by name

# Lint & Format
ruff check src/                            # lint
ruff check --fix src/                      # autofix
ruff format src/                           # format
mypy src/voice/                            # type check

# Pre-commit
pre-commit install                         # one-time setup
pre-commit run --all-files                 # manual run
```

## Code Style

- Python 3.12+, line length 100
- **Ruff** for linting (E, F, I, N, UP, B, SIM, TCH rules) and formatting
- **mypy** strict mode with Pydantic plugin
- isort first-party: `sena_common`, `ocr`, `rag`
- async-first: all DB operations use `AsyncSession`, all services are async
- Settings via `pydantic-settings` with `SENA_AI_` env prefix and `.env` file

## Authentication

Two modes controlled by `SENA_AI_AUTH_MODE`:
- `dev_header` (default): reads `X-User-Id` and `X-User-Roles` headers directly
- `jwt`: validates JWT bearer tokens against configured public key

## Key Technical Decisions (Already Decided)

- Python + FastAPI as framework
- Row-Level Security (RLS) for multi-tenant isolation
- pgvector for embeddings/vector search
- Hybrid search (vector + keyword)
- Structure-aware chunking for document processing

## Context Documents

- `Extras/CONTEXT_HANDOFF.md` — master context document for new sessions
- `Extras/TECHNICAL_DECISIONS.md` — architecture decision log
- `Extras/SPRINT_0_PLAN.md` — current sprint definition
- Docs in `Extras/docs/architecture/` are intern drafts — rough starting points, not finalized specs

## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- After modifying code files in this session, run `python3 -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))"` to keep the graph current
