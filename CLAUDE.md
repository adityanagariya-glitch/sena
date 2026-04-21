# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SENA is an AI-powered multi-tenant SaaS platform for Australian NDIS service providers. This repo contains the **AI/ML backend layer only** — the broader platform (HR, payroll, shifts, client management) is built by a separate client team. API contracts between the two teams are defined in `api_contracts.py` at the root.

**Domain:** NDIS (National Disability Insurance Scheme) — Australian disability services compliance, case note drafting, voice-based workflows.

**Hard constraints:** Multi-tenant data isolation (legally mandated), human-in-the-loop approval for all AI outputs, Australian data residency, NDIS compliance.

## Architecture

Monorepo at `sena-ai/` with Python microservices. Currently one active service (voice), one scaffolded (ocr).

**Root-level files:**
```
SENA/
├── api_contracts.py    # Shared API contracts between AI layer and client platform
├── AGENTS.md           # Guidance for agentic coding agents in this repo
├── requirements.txt    # Root-level Python dependencies
├── sena-ai/            # Monorepo — all AI/ML services
├── wiki/               # LLM-maintained knowledge base
└── graphify-out/       # Auto-generated knowledge graph
```

**`sena-ai/` monorepo:**
```
sena-ai/
├── services/
│   ├── voice/          # Active — Flow B case note dictation
│   ├── onboarding/     # Active — Voice onboarding API (Gemini Live, port 8083)
│   └── ocr/            # Scaffolded, not yet implemented
├── shared/             # sena-common shared library (DB, middleware, schemas)
├── migrations/         # Alembic DB migrations + init SQL + RLS setup scripts
├── scripts/            # Dev/ops scripts
├── Makefile            # Common task shortcuts
├── docker-compose.yml  # Redis + 2x PostgreSQL (ai-db with pgvector, shared-db)
├── .env.example        # All env vars with SENA_AI_ prefix
└── pyproject.toml      # Workspace root — ruff, mypy, pytest config
```

### Onboarding Service — voice-driven participant onboarding

API-first service at `sena-ai/services/onboarding/src/onboarding/`. Mobile app integrates; no frontend shipped.

| Layer | Path | Purpose |
|-------|------|---------|
| API | `api/routes.py` | REST: session lifecycle, state, webhook fire |
| API | `api/ws_routes.py` | WebSocket: start handshake, WS lock, Gemini bridge, error close codes (Phase B ✓) |
| Services | `services/gemini_live.py` | Gemini Live bridge: b2g/g2b tasks, transcript events, WS↔Gemini audio (Phase B ✓) |
| Services | `services/prompt_builder.py` | System prompt renderer: injects schema + FormState via `__PLACEHOLDER__` replacements (Phase B ✓) |
| Services | `services/tools.py` | Tool dispatcher: update_field, get_session_context, advance_step, escalate_incident (Phase C ✓) |
| Services | `services/webhook.py` | Outbound webhook to app backend, 3-retry exp backoff |
| Repositories | `repositories/state_repo.py` | Redis only — no Postgres. FormState, transcript, WS lock, resumption handles |
| Models | `models/schema_spec.py` | StepSchema, SectionSpec, FieldSpec (incl. visible_if, repeatable) |
| Models | `models/form_state.py` | FormState, FieldValue, CompletionStats |
| Fixtures | `fixtures/schema_*.json` | 5 step schemas from real app screens |

**Key routes:**
- `POST /v1/onboarding/session` — create session (app sends schema inline)
- `GET/PUT /v1/onboarding/session/{id}/state` — read/write FormState (PUT blocked when WS active)
- `POST /v1/onboarding/session/{id}/complete` — finalize + fire webhook
- `WSS /ws/onboarding/{session_id}` — voice stream (Phase B)

**Design decisions:**
- One WS session = one onboarding step (clean resumption semantics)
- App backend owns schema + final DB; we own ephemeral Redis state
- Voice holds write lock during WS; app PUTs only when WS closed
- No Postgres — Redis TTL only; app backend is DB of record

**Run:**
```bash
cd sena-ai/services/onboarding
uvicorn src.onboarding.main:create_app --factory --reload --port 8083
```

**Env vars (prefix `SENA_AI_`):** `GEMINI_API_KEY`, `GEMINI_LIVE_MODEL_ID`, `ONBOARDING_PORT`, `APP_WEBHOOK_URL`, `APP_WEBHOOK_SECRET`, `REDIS_URL`

---

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

- **AWS Bedrock** (Claude 3.5 Sonnet) — LLM for case note generation (Flow B dictation)
- **Google Gemini** (`gemini-2.0-flash`) — LLM for personal details onboarding flow (replaces Bedrock for that flow)
- **AWS SNS** — event publishing for case note lifecycle
- **LiveKit** — real-time voice conferencing
- **Redis** — session state, rate limiting, distributed locks
- **PostgreSQL + pgvector** (ai-db, port 5433) — voice session/case note data
- **PostgreSQL** (shared-db, port 5434) — cross-service platform data

### LLM split

| Flow | Provider | Model | Env var |
|------|----------|-------|---------|
| Flow B — case note dictation | AWS Bedrock | Claude 3.5 Sonnet | `SENA_AI_BEDROCK_MODEL_ID` |
| Onboarding voice (Live API) | Google Gemini Live | `gemini-3.1-flash-live-preview` | `SENA_AI_GEMINI_API_KEY` + `SENA_AI_GEMINI_LIVE_MODEL_ID` |

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

# Run onboarding service
cd services/onboarding
uvicorn src.onboarding.main:create_app --factory --reload --port 8083

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

**SessionStart** (`.claude/hooks/session-start.sh`):
- Injects SESSION_START.md read-order as additionalContext on every new session
- Ensures Claude lands in the same state every time regardless of what's "remembered"

**PreToolUse** (`.claude/hooks/pre-tool-use.sh`):
- Blocks dangerous commands (`rm -rf` on critical dirs, force push to main)
- Warns when committing directly to main/master
- Reminds to check graphify knowledge graph before searching
- Flags critical file modifications (CLAUDE.md, .env, settings.json)

**PostToolUse** (`.claude/hooks/post-tool-use.sh` + `.claude/hooks/bump-updated.sh`):
- Maintains per-service `requirements.txt` via pipreqs on Python file edits
- Auto-bumps `updated: YYYY-MM-DD` frontmatter on SESSION_START.md, TASKS.md, MEMORY.md, CLAUDE.md whenever Claude edits them
- Logs tool usage to `wiki/log.md`
- Auto-rebuilds graphify knowledge graph when code files change

**Stop** (`.claude/hooks/stop.sh`):
- Emits reminder at every session boundary (stop, /clear, /compact, resume) to verify `.claude/tasks/TASKS.md` is current

### Philosophy

> "If it must **always** happen, use a hook, not a prompt."

Hooks are **deterministic** — they enforce invariants that should never be violated. For conditional guidance, use CLAUDE.md instructions instead.

## Session Start (READ FIRST in any new session)

The authoritative read-order guide is `.claude/SESSION_START.md`. Read it BEFORE doing anything else in a new session. It tells you which files to read next based on the task, the current project state, and verification steps to confirm nothing broke between sessions.

## Persistent Task List

The canonical, session-persistent task list lives at `.claude/tasks/TASKS.md`. Read this file at the start of every session — it survives `/compact`, context resets, and session switches. Update it whenever a task's status changes or a new task is added. Keep completed entries around for a few sessions as a trail before pruning to a separate archive.

## Setup Rules
- Always use Context7 (`get-library-docs`) to verify API or setup steps before running automation.
- For all browser-based tasks, prioritize using the Playwright MCP server to execute the workflow rather than asking me to do it in the browser.

## Gemini API Rules (MANDATORY)

For ANY code touching Gemini API or Gemini Live API:

1. **Invoke the skill first** — before writing/editing any Gemini code, run `Skill: gemini-live-api-dev` (Live API) or `Skill: gemini-api-dev` (general). Do NOT rely on training data — it is stale.
2. **Query the MCP** — use `search_documentation` from `gemini-api-docs-mcp` MCP server for method signatures and configuration details.
3. **Current models (2026-04):**
   - Gemini Live (personal details voice flow): `gemini-3.1-flash-live-preview`
   - Deprecated (do NOT use): `gemini-2.5-flash-native-audio-latest`, `gemini-2.5-flash-native-audio-preview-*`, `gemini-live-2.5-flash-preview`, `gemini-2.0-flash-live-001`
4. **Current Live API patterns:**
   - Send audio: `await session.send_realtime_input(audio=types.Blob(data=raw, mime_type="audio/pcm;rate=16000"))`
   - Send text: `await session.send_realtime_input(text="...")`
   - Signal end-of-speech: `await session.send_realtime_input(audio_stream_end=True)`
   - Do NOT use: `session.send(input=..., end_of_turn=True)` (old API, misroutes to `send_client_content`)
   - Do NOT use: `LiveClientRealtimeInput(media_chunks=[...])` (old wire format)
5. **Proactive audio NOT supported** on `gemini-3.1-flash-live-preview` — model will NOT speak first without user audio input. Greeting must be triggered by user speaking first (system prompt handles the actual greeting content).
6. **NEVER gate mic audio on an `_agent_speaking` flag.** Doing so causes VAD to silently stop after 2-4 turns (model sends audio for next turn before user speaks, gate mutes mic, VAD never fires). Always stream audio unconditionally; rely on `activity_handling=START_OF_ACTIVITY_INTERRUPTS` for barge-in. Use `START_SENSITIVITY_LOW` — HIGH fires on ambient noise between turns.

## Demo Stack

Standalone Gemini Live demo (separate from the production voice service):
- `sena-ai/demo_live_server.py` — FastAPI server bridging browser WebSocket ↔ Gemini Live
- `sena-ai/demo_client.html` — browser UI with mic capture + audio playback + file upload mode
- Run: `cd sena-ai && uvicorn demo_live_server:app --reload --port 8082`
- Env required: `SENA_AI_GEMINI_API_KEY`, `SENA_AI_GEMINI_LIVE_MODEL_ID`

## Cleanup Rule

When removing "dead code", ALWAYS grep the full codebase for the file/symbol name first. Previous audits have produced false positives that would have broken production (e.g., `gemini_service.py` was flagged dead but is actively called by HTTP personal-details turn endpoint).

## Ignored Folders

**NEVER** try to read or analyze anything inside the `/archive`, `.venv`, or `.vscode` folders. They are a massive token consumption disaster and are likely useless for your analysis. Pretend they do not exist unless explicitly instructed by the user to restore something.

<!-- Last auto-updated: 2026-04-16 00:23:07 by hook -->
