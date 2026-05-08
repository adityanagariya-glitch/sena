# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SENA is an AI-powered multi-tenant SaaS platform for Australian NDIS service providers. This repo contains the **AI/ML backend layer only** — the broader platform (HR, payroll, shifts, client management) is built by a separate client team.

**Domain:** NDIS (National Disability Insurance Scheme) — Australian disability services compliance, case note drafting, voice-based workflows.

<hard_constraints priority="MANDATORY" type="legal-compliance">
**Hard constraints:** Multi-tenant data isolation (legally mandated), human-in-the-loop approval for all AI outputs, Australian data residency, NDIS compliance.
</hard_constraints>

## Architecture

Monorepo at `sena-ai/` with Python microservices. Active services: voice (8082), onboarding (8083), case_review (8084). OCR scaffolded.

**Root-level files:**
```
SENA/
├── AGENTS.md           # Guidance for agentic coding agents in this repo
├── sena-ai/            # Monorepo — all AI/ML services
└── graphify-out/       # Auto-generated knowledge graph
```

**`sena-ai/` monorepo:**
```
sena-ai/
├── services/
│   ├── voice/          # Active — Flow B case note dictation (port 8082)
│   ├── onboarding/     # Active — Voice onboarding API (Gemini Live, port 8083)
│   ├── case_review/    # Active — Case note review + intelligence layer (port 8084)
│   └── ocr/            # Skeleton only (main.py + pyproject); no tests/ dir; not wired into routing
├── shared/             # sena-common shared library (DB, middleware, schemas)
├── migrations/         # Alembic DB migrations + init SQL + RLS setup scripts
├── scripts/            # Dev/ops scripts
├── Makefile            # Stub only — comment header, no targets implemented yet
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
| Services | `services/gemini_live.py` | Gemini Live bridge: b2g/g2b tasks, transcript events, WS↔Gemini audio, screen_state inject (Phase B/D ✓) |
| Services | `services/prompt_builder.py` | System prompt renderer: injects schema + FormState + grounding/resume context (Phase B/E ✓) |
| Services | `services/tools.py` | Tool dispatcher: update_field, get_session_context, advance_step (idempotent), escalate_incident (Phase C ✓) |
| Services | `services/screen_context.py` | Pure: ScreenStateMessage validation + render_injection_text + payload_hash (Phase D ✓) |
| Services | `services/grounding.py` | Pure: build_live_tools — assembles function_declarations + optional GoogleSearch tool (Phase E ✓) |
| Services | `services/resumption.py` | Redis-backed: issue_handle, redeem_handle (GETDEL single-use), build_replay_context (Phase E ✓) |
| Services | `services/webhook.py` | Outbound webhook to app backend, 3-retry exp backoff |
| Services | `services/cross_screen_context.py` | Pure: build_summary, compress_residual/decompress (lossless), render_for_prompt — feeds the EARLIER IN THIS ONBOARDING block |
| Repositories | `repositories/state_repo.py` | Redis only — no Postgres. FormState, transcript, WS lock, resumption handles. Plus `assert_session_owner` for cross-tenant isolation. |
| Repositories | `repositories/user_context_repo.py` | Redis only. Per-(tenant_id, participant_id) cross-screen bucket: step summaries (Hash) + session-id index (Set), 7-day TTL refreshed on every write |
| Models | `models/schema_spec.py` | StepSchema, SectionSpec, FieldSpec (incl. visible_if, repeatable) |
| Models | `models/form_state.py` | FormState, FieldValue, CompletionStats |
| Models | `models/session_bootstrap.py` | SessionBootstrap envelope (Rule 1+2 hygiene contract — mode, current_page_values, readonly_paths, prior_pages); rendered into prompt as `[LIVE_STATE_JSON]` |
| Fixtures | `fixtures/schema_*.json` | 5 step schemas from real app screens |

**Key routes:**
- `POST /v1/onboarding/session` — create session (app sends schema inline)
- `GET/PUT /v1/onboarding/session/{id}/state` — read/write FormState (PUT blocked when WS active)
- `POST /v1/onboarding/session/{id}/complete` — finalize + fire webhook
- `WSS /ws/onboarding/{session_id}` — voice stream (Phase B)

**WS server→client events (Flutter must handle all):**
| Event | Payload | Action required |
|-------|---------|----------------|
| `ready` | `{state, prompt_version, coverage}` | Session live, start mic |
| `turn_start` | — | Gemini began speaking, start playback |
| `turn_complete` | — | Gemini finished turn |
| `interrupted` | — | User barged in, clear audio queue |
| `user_said` | `{text}` | Input transcript |
| `agent_said` | `{text}` | Output transcript |
| `go_away` | `{time_left_ms}` | **Gemini session closing in N ms — call resume endpoint before expiry to avoid silent drop** |
| `resumable` | `{handle, ttl_sec}` | App-level resume handle issued on close |
| `error` | `{code, message}` | Handle or close |

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

**Env vars (prefix `SENA_AI_`):** `GEMINI_API_KEY`, `GEMINI_LIVE_MODEL_ID`, `ONBOARDING_PORT`, `APP_WEBHOOK_URL`, `APP_WEBHOOK_SECRET`, `REDIS_URL`, `ONBOARDING_GROUNDING_ENABLED` (default false), `ONBOARDING_CROSS_SCREEN_CONTEXT_ENABLED` (default true — controls per-(tenant_id, participant_id) shared-context bucket reads/writes; rollback flag), `SCREEN_STATE_MAX_BYTES` (default 8192), `RESUMPTION_HANDLE_TTL_SEC` (default 600), `RESUMPTION_REPLAY_TURNS` (default 4)

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
- **Google Gemini** (`gemini-3-flash-preview`) — LLM for case review (summarise, classify, review); Live API (`gemini-3.1-flash-live-preview`) for onboarding voice stream
- **AWS SNS** — event publishing for case note lifecycle
- **LiveKit** — real-time voice conferencing
- **Redis** — session state, rate limiting, distributed locks
- **PostgreSQL + pgvector** (ai-db, port 5433) — voice session/case note data + case review tables
- **PostgreSQL** (shared-db, port 5434) — cross-service platform data
- **Other engineer's drafting service** (port 8085, stub in Phase A) — source of past case notes for context

### LLM split

| Flow | Provider | Model | Env var |
|------|----------|-------|---------|
| Flow B — case note dictation | AWS Bedrock | Claude 3.5 Sonnet | `SENA_AI_BEDROCK_MODEL_ID` |
| Onboarding voice (Live API) | Google Gemini Live | `gemini-3.1-flash-live-preview` | `SENA_AI_GEMINI_API_KEY` + `SENA_AI_GEMINI_LIVE_MODEL_ID` |
| Case review (summarise/classify/review) | Google Gemini | `gemini-3-flash-preview` | `SENA_AI_GEMINI_API_KEY` + `SENA_AI_GEMINI_MODEL_ID` |

### Case Review Service — AI intelligence layer around case notes

At `sena-ai/services/case_review/src/case_review/`. Port 8084, ai-db (pgvector).

| Layer | Path | Purpose |
|-------|------|---------|
| API | `api/routes.py` | 6 REST endpoints (context, classify, review, incident/*, submit) + health |
| API | `api/deps.py` | DI: AsyncSession, ReviewRepo, CaseNoteClient, AuthContext (dev_header) |
| Models | `models/db.py` | 4 ORM tables: RollingSummary, ReviewSession, IncidentDraft, ReviewAuditLog |
| Models | `models/schemas.py` | Pydantic DTOs for all endpoints |
| Repositories | `repositories/review_repo.py` | CRUD + upsert (rolling summary) + audit append |
| Clients | `clients/case_note_client.py` | Stub (fixtures) + real HTTP client (future) |
| Fixtures | `fixtures/sample_notes.json` | 3 fake case notes for stub client |
| Migrations | `migrations/versions/0001_*.py` | Creates 4 tables + RLS policies on tenant_id |

**Key routes (all 501 in Phase A — implemented progressively):**
- `POST /v1/case-review/context` — fetch + rolling summary (Phase B)
- `POST /v1/case-review/classify` — paragraph → fields + reask prompts (Phase C)
- `POST /v1/case-review/review` — risk/restrictive-practice/anomaly flags (Phase D)
- `POST /v1/case-review/incident/detect` + `/draft` + `PATCH .../confirm` (Phase E)
- `POST /v1/case-review/submit` — final gate (Phase F, BLOCKED)

<non_negotiables service="case_review" priority="MANDATORY" type="legal-compliance">
**Non-negotiables:**
- `tenant_id` on every DB row + RLS enforced (legal mandate)
- Staff must acknowledge every AI flag — no auto-submit
- Audit log entry for every AI action + staff decision
- `GEMINI_REGION=australia-southeast1` (data residency)
</non_negotiables>

**Run:**
```bash
cd sena-ai/services/case_review
uvicorn src.case_review.main:create_app --factory --reload --port 8084
# Alembic: alembic upgrade head  (requires ai-db running)
# Install once via the per-service Setup block in Build & Run Commands.
```

**Env vars (prefix `SENA_AI_`):** `CASE_REVIEW_PORT`, `AI_DB_URL`, `GEMINI_API_KEY`, `GEMINI_MODEL_ID`, `GEMINI_REGION`, `DRAFTING_SERVICE_URL`, `DRAFTING_SERVICE_API_KEY`, `CASE_NOTE_FETCH_LIMIT`

---

## Build & Run Commands

```bash
# Setup — install per service (matches CI; root pyproject has no dev extra)
cd sena-ai
cp .env.example .env                       # configure env vars
pip install -e "services/voice[dev]"       # voice service (also pulls shared lib)
pip install -e "services/onboarding[dev]"  # onboarding service
pip install -e "services/case_review[dev]" # case review service

# Infrastructure
docker-compose up -d                       # Redis + both Postgres DBs

# Run voice service
cd services/voice
uvicorn src.voice.main:create_app --factory --reload --port 8082

# Run onboarding service
cd services/onboarding
uvicorn src.onboarding.main:create_app --factory --reload --port 8083

# Run case review service (install once via Setup block above)
cd services/case_review
uvicorn src.case_review.main:create_app --factory --reload --port 8084

# Tests — always pass an explicit path; root pytest testpaths excludes active services
pytest services/voice/tests/               # voice service
pytest services/onboarding/tests/          # onboarding service
pytest services/case_review/tests/         # case review service
pytest services/voice/tests/test_file.py   # single file
pytest services/voice/tests -k "test_name" # single test by name

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


<issues_solved_protocol priority="MANDATORY" trigger="before-any-debugging">
## Issues-Solved Knowledge Base (MANDATORY — CHECK BEFORE DEBUGGING)

<path>Path: `.claude/issues-solved/`</path>

<lookup_rule>
**Rule:** before debugging ANY issue, grep `.claude/issues-solved/INDEX.md` for symptom keywords.
- If match → read linked detail file → apply fix. Do NOT re-derive.
- If no match → solve, then append a new entry via `TEMPLATE.md`.
</lookup_rule>

<entry_threshold>
**When to add an entry:** issue took >2 debugging iterations OR >5 min OR required external research. One file per issue, numbered `NNNN-kebab-symptom.md`, row added to `INDEX.md` (newest first).
</entry_threshold>

<goal>
**Goal:** zero re-solved bugs, zero token-waste on problems already cracked.
</goal>

See `.claude/issues-solved/README.md` for full protocol.
</issues_solved_protocol>

## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- After modifying code files in this session, run `python3 -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))"` to keep the graph current. The Stop hook also rebuilds the graph at every session boundary.

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
- **Rule 3 — Gemini Live Config Gate (STRICT):** any Write/Edit to a `gemini*` or `demo_live*` file is blocked until BOTH `skills-gemini.flag` (Skill: gemini-live-api-dev invoked) AND `ctx7-gemini.flag` (Context7 queried for google-genai/gemini this session) are present. Either missing → block with specific remediation steps.

**PostToolUse** (`.claude/hooks/post-tool-use.sh` + `.claude/hooks/bump-updated.sh`):
- Maintains per-service `requirements.txt` via pipreqs on Python file edits
- Auto-bumps `updated: YYYY-MM-DD` frontmatter on SESSION_START.md, TASKS.md, MEMORY.md, CLAUDE.md whenever Claude edits them
- Auto-rebuilds graphify knowledge graph when code files change

**Stop** (`.claude/hooks/stop.sh`):
- Rebuilds graphify knowledge graph at every session boundary (stop, /clear, /compact, resume)
- Emits reminder to verify `.claude/tasks/TASKS.md` is current

### Philosophy

> "If it must **always** happen, use a hook, not a prompt."

Hooks are **deterministic** — they enforce invariants that should never be violated. For conditional guidance, use CLAUDE.md instructions instead.

## Session Start (READ FIRST in any new session)

The authoritative read-order guide is `.claude/SESSION_START.md`. Read it BEFORE doing anything else in a new session. It tells you which files to read next based on the task, the current project state, and verification steps to confirm nothing broke between sessions.

## Persistent Task List

The canonical, session-persistent task list lives at `.claude/tasks/TASKS.md`. Read this file at the start of every session — it survives `/compact`, context resets, and session switches. Update it whenever a task's status changes or a new task is added. Keep completed entries around for a few sessions as a trail before pruning to a separate archive.

<setup_rules priority="MANDATORY">
## Setup Rules
- Always use Context7 (`get-library-docs`) to verify API or setup steps before running automation.
- For all browser-based tasks, prioritize using the Playwright MCP server to execute the workflow rather than asking me to do it in the browser.
</setup_rules>

## Gemini API Rules (MANDATORY)

<gemini_rules priority="MANDATORY" scope="any-gemini-code">
<applies_to>
For ANY code touching Gemini API or Gemini Live API:
</applies_to>

<rule id="1" type="prerequisite">
1. **Invoke the skill first** — before writing/editing any Gemini code, run `Skill: gemini-live-api-dev` (Live API) or `Skill: gemini-api-dev` (general). Do NOT rely on training data — it is stale.
</rule>
<rule id="2" type="prerequisite">
2. **Query the MCP** — use `search_documentation` from `gemini-api-docs-mcp` MCP server for method signatures and configuration details.
</rule>
<rule id="3" type="model-selection">
3. **Current models (2026-04):**
   - Gemini Live (personal details voice flow): `gemini-3.1-flash-live-preview`
   - Deprecated (do NOT use): `gemini-2.5-flash-native-audio-latest`, `gemini-2.5-flash-native-audio-preview-*`, `gemini-live-2.5-flash-preview`, `gemini-2.0-flash-live-001`
</rule>
<rule id="4" type="api-pattern">
4. **Current Live API patterns:**
   - Send audio: `await session.send_realtime_input(audio=types.Blob(data=raw, mime_type="audio/pcm;rate=16000"))`
   - Send text: `await session.send_realtime_input(text="...")`
   - Signal end-of-speech: `await session.send_realtime_input(audio_stream_end=True)`
   - Do NOT use: `session.send(input=..., end_of_turn=True)` (old API, misroutes to `send_client_content`)
   - Do NOT use: `LiveClientRealtimeInput(media_chunks=[...])` (old wire format)
</rule>
<rule id="5" type="capability-limit">
5. **Proactive audio NOT supported** on `gemini-3.1-flash-live-preview` — model will NOT speak first without user audio input. Greeting must be triggered by user speaking first (system prompt handles the actual greeting content).
</rule>
<rule id="6" type="forbidden-pattern" severity="critical">
6. **NEVER gate mic audio in server Python (`_browser_to_gemini`).** A server-side `_agent_speaking` flag causes VAD to silently stop after 2-4 turns: model audio for turn N+1 arrives before `turn_complete` of turn N fires, keeping the gate closed when the user tries to speak. Always forward audio unconditionally in `_browser_to_gemini`; rely on `activity_handling=START_OF_ACTIVITY_INTERRUPTS` for barge-in. Use `START_SENSITIVITY_LOW` — HIGH fires on ambient noise.
   **Flutter client MUST mute mic during agent speech (echo fix):** set `_agentSpeaking=true` on `turn_start`, `false` on `turn_complete`/`interrupted`. Gate in the mic stream listener (`if (!_agentSpeaking) _sendAudio(chunk)`), not in the recorder itself. Server also calls `send_realtime_input(audio_stream_end=True)` on `turn_start` to flush Gemini's VAD buffer of any echo frames already in flight.
</rule>
</gemini_rules>

## Demo Stack

Standalone Gemini Live demo (separate from the production voice service):
- `sena-ai/demo_live_server.py` — FastAPI server bridging browser WebSocket ↔ Gemini Live
- `sena-ai/demo_client.html` — browser UI with mic capture + audio playback + file upload mode
- Run: `cd sena-ai && uvicorn demo_live_server:app --reload --port 8082`
- Env required: `SENA_AI_GEMINI_API_KEY`, `SENA_AI_GEMINI_LIVE_MODEL_ID`

<cleanup_rule priority="MANDATORY" trigger="dead-code-removal">
## Cleanup Rule

When removing "dead code", ALWAYS grep the full codebase for the file/symbol name first. Previous audits have produced false positives that would have broken production (e.g., `gemini_service.py` was flagged dead but is actively called by HTTP personal-details turn endpoint).
</cleanup_rule>

<ignored_folders priority="MANDATORY" type="forbidden-paths">
## Ignored Folders

<never_read>
**NEVER** try to read or analyze anything inside the `/archive`, `.venv`, `.vscode`, or `ndis_markdown_docs/` folders. They are a massive token consumption disaster. Pretend they do not exist unless explicitly instructed.
</never_read>

<exception target="ndis_markdown_docs">
**`ndis_markdown_docs/` exception:** raw NDIS source PDFs converted to markdown. For NDIS compliance questions you MAY suggest reading a **specific file** from this folder — never the whole folder, never speculatively.
</exception>
</ignored_folders>

<add_component_protocol priority="MANDATORY" trigger="user-says-I-am-adding-X">
## Adding New Project Components (MANDATORY PROTOCOL)

<trigger_phrase>
When the user says **"I am adding X"** (a new directory, service, file, or external resource), you MUST update ALL of the following before doing anything else:
</trigger_phrase>

<update_sweep>
| File | What to update |
|------|---------------|
| `CLAUDE.md` (this file) | Add to root-level file tree + add a dedicated section describing the component |
| `.claude/SESSION_START.md` | Add to the READ-IF-RELEVANT table under the appropriate task area |
| `.claude/tasks/TASKS.md` | Update any blocked tasks that are now unblocked by the new component |
| `~/.claude/projects/.../memory/MEMORY.md` | Add an index entry pointing to a new memory file |
| Create `memory/project_<name>.md` | Describe what the component is and how to use it |
</update_sweep>

<blocking_rule>
**Rule:** Do NOT start any other work until this update sweep is complete. The sweep ensures future sessions land in the correct state.
</blocking_rule>
</add_component_protocol>

## Paused Features

(none)

## Sena Agent System

- Read `.claude/rules/sena-rules.md` at session start for routing rules and constraints.
- Read `.claude/memory/sena-memory.md` to recall past decisions and outcomes.
- For non-trivial multi-file or multi-subsystem tasks, route through the Sena agents in `.claude/agents/`. Never handle work of that scope directly in the main session thread.
- The numbered prompt templates in `.agents/01-08*.md` are templates for an external multi-model orchestrator (see `.agents/WORKFLOW_PLAN.md`). They are **not** Claude Code subagents — do not invoke them via the Task tool.
- After completing any significant task, append one line to `.claude/memory/sena-memory.md`:
  `[YYYY-MM-DD] [agent name or "main"] — [what was done] — [key outcome]`

<!-- Last auto-updated: 2026-04-16 00:23:07 by hook -->
