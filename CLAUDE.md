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


## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- After modifying code files in this session, run `python3 -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))"` to keep the graph current

## LLM Wiki

This project has an LLM-maintained wiki at `wiki/`. The wiki is a persistent, interlinked knowledge base covering NDIS domain knowledge, architecture decisions, client requirements, and technical learnings. The LLM writes and maintains all pages; the human curates sources and reviews output.

### Structure

```
wiki/
├── index.md               # Master index — read this first for any wiki query
├── overview.md            # Living synthesis of project state
├── log.md                 # Append-only chronological record of wiki operations
├── NDIS.md                # Hub: NDIS domain knowledge (Map of Content)
├── Architecture.md        # Hub: technical architecture (Map of Content)
├── Client-Requirements.md # Hub: client team specs (Map of Content)
├── sources/               # One summary per ingested raw document
└── pages/                 # All detail pages (entities, concepts, decisions, topics)
```

### Page conventions

- **Frontmatter required:** title, type (entity|concept|decision|source|topic|hub), tags, sources, created, updated
- **Wikilinks:** Use `[[page-name]]` for all internal links
- **Filenames:** kebab-case (e.g., `flow-b-voice-dictation.md`)
- **Connections section:** Every page ends with explicit cross-references
- **Source summaries:** Include `raw_path` field and `Pages Updated` section

### Ingest workflow (when adding new sources)

1. Read the raw source document
2. Create/update source summary in `wiki/sources/`
3. Create new detail pages in `wiki/pages/` for uncovered entities/concepts
4. Update existing pages (flag contradictions with `> [!warning] Contradiction` callout — never silently overwrite)
5. Update relevant hub pages with new links
6. Update `wiki/index.md` with any new pages
7. Append to `wiki/log.md`: `## [YYYY-MM-DD] ingest | Source Title`

### Query workflow (when answering questions from wiki)

1. Read `wiki/index.md` to find relevant pages
2. Read those pages, synthesize an answer
3. If the answer is worth keeping, offer to file it as a new wiki page

### Lint workflow (periodic maintenance)

1. Orphan pages (no inbound wikilinks)
2. Stale content (sources updated but pages not)
3. Mentioned-but-missing pages (broken wikilinks)
4. Contradictions between pages
5. Suggest new pages or sources to investigate

### Relationship to other knowledge layers

- **graphify-out/** — code-level structure. Wiki pages on architecture can link to `graphify-out/GRAPH_REPORT.md` but don't duplicate code analysis.
- **.planning/** — execution state. Wiki captures domain knowledge, not sprint progress.
- **archive/** — raw sources. Immutable. Wiki was bootstrapped from these.

### Browsing

The whole SENA repo is an Obsidian vault. Open the root folder in Obsidian to see the wiki graph view.

## Hooks

Automated hooks enforce safety rules and maintain documentation consistency. See `.claude/HOOKS_README.md` for full details.

### Active Hooks

**PreToolUse** (`.claude/hooks/pre-tool-use.sh`):
- Blocks dangerous commands (`rm -rf` on critical dirs, force push to main)
- Warns when committing directly to main/master
- Reminds to check graphify knowledge graph before searching
- Flags critical file modifications (CLAUDE.md, .env, settings.json)

**PostToolUse** (`.claude/hooks/post-tool-use.sh`):
- Auto-updates CLAUDE.md timestamp after edits
- Logs tool usage to `wiki/log.md`
- Auto-rebuilds graphify knowledge graph when code files change
- Tracks file modifications and significant commands

### Philosophy

> "If it must **always** happen, use a hook, not a prompt."

Hooks are **deterministic** — they enforce invariants that should never be violated. For conditional guidance, use CLAUDE.md instructions instead.

## Setup Rules
- Always use Context7 (`get-library-docs`) to verify API or setup steps before running automation.
- For all browser-based tasks, prioritize using the Playwright MCP server to execute the workflow rather than asking me to do it in the browser.

## Ignored Folders

**NEVER** try to read or analyze anything inside the `/archive`, `.venv`, or `.vscode` folders. They are a massive token consumption disaster and are likely useless for your analysis. Pretend they do not exist unless explicitly instructed by the user to restore something.

<!-- Last auto-updated: 2026-04-16 00:23:07 by hook -->
