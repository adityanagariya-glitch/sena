# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Session-start read order:** `.claude/SESSION_START.md` → `.claude/tasks/TASKS.md` → `~/.claude/projects/.../memory/MEMORY.md`. The SessionStart hook injects this automatically; if you don't see it, read these files manually before any work.

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
├── docker-compose.yml         # Redis + 2x PostgreSQL (ai-db with pgvector, shared-db) — local dev only
├── docker-compose.deploy.yml  # EC2 production deploy — onboarding + Redis, no local DBs
├── .env.example               # All env vars with SENA_AI_ prefix
├── .env.deploy.example        # Minimal env vars needed for EC2 deploy
├── DEPLOY_EC2_CHECKLIST.md    # Step-by-step EC2 deployment guide (demo-grade shortcuts documented)
└── pyproject.toml             # Workspace root — ruff, mypy, pytest config
```

### LLM split (cross-service reference)

| Flow | Provider | Model | Env var |
|------|----------|-------|---------|
| Case note dictation (Flow B) | AWS Bedrock | Claude 3.5 Sonnet | `SENA_AI_BEDROCK_MODEL_ID` |
| Onboarding + personal-details voice (Live API) | Google Gemini Live | `gemini-3.1-flash-live-preview` | `SENA_AI_GEMINI_API_KEY` + `SENA_AI_GEMINI_LIVE_MODEL_ID` |
| Case review summarise/classify/review | Google Gemini Flash | `gemini-3-flash-preview` | `SENA_AI_GEMINI_API_KEY` + `SENA_AI_GEMINI_MODEL_ID` |

### Per-service detail (autoload when editing that service)

| Topic | Rule file | Autoloads on |
|-------|-----------|--------------|
| Onboarding internals (Redis state, WS events, voice coverage, tools, validators) | `.claude/rules/service-onboarding.md` | `services/onboarding/**` |
| Voice internals (Bedrock, LiveKit, approval flow, SNS events) | `.claude/rules/service-voice.md` | `services/voice/**` |
| Case Review internals (pgvector, RLS, 4 ORM tables, audit log) | `.claude/rules/service-case-review.md` | `services/case_review/**` |
| Gemini API rules (current models, patterns, forbidden patterns) — hook-gated | `.claude/rules/gemini.md` | `**/gemini*.py`, `**/demo_live*` |
| Build / run / test commands per service | `.claude/rules/build-and-run.md` | `pyproject.toml`, `docker-compose*.yml`, `Makefile` |
| EC2 deployment (Docker) | `.claude/rules/deployment.md` | `Dockerfile`, `docker-compose.deploy.yml`, `.env.deploy*` |
| Demo stack (standalone Gemini Live testbed) | `.claude/rules/demo-stack.md` | `demo_live*.py`, `demo_live*.html` |

---

## Build & Run Commands

**Reference:** `.claude/rules/build-and-run.md` — autoloads when editing `pyproject.toml`, `Makefile`, `docker-compose*.yml`, or any service Dockerfile. Contains per-service install/run/test commands, lint/typecheck flow, PowerShell variant.

**Quick:** `pip install -e "services/<svc>[dev]"` from `sena-ai/` root; `uvicorn src.<svc>.main:create_app --factory --reload --port <8082|8083|8084>`; tests via `pytest services/<svc>/tests/` (always pass explicit path).

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
  - **Flag locations:** `.claude/state/skills-gemini.flag` and `.claude/state/ctx7-gemini.flag` (cleared by SessionStart hook on every new session — must be re-earned).
  - **To clear the gate:** (1) invoke `Skill: gemini-live-api-dev` (sets skills flag automatically); (2) call `mcp__plugin_context7_context7__resolve-library-id` then `query-docs` for `google-genai` (sets ctx7 flag). Then retry the Write/Edit.

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

## Gemini API Rules

**Hook-gated, MANDATORY** — `.claude/rules/gemini.md` autoloads on any `gemini*` / `demo_live*` file edit. Contains current models (`gemini-3.1-flash-live-preview` Live + `gemini-3-flash-preview` Flash), current API patterns (`send_realtime_input`), deprecated patterns (`session.send(input=...)`, `LiveClientRealtimeInput`, `send_client_content` for new messages), capability limits (no proactive audio, 15-min audio-only, 2-min audio+video), and the **NEVER gate mic on `_agent_speaking`** rule. Before editing Gemini code: invoke `Skill: gemini-live-api-dev` + call Context7 for `google-genai`.

## Demo stack

**Reference:** `.claude/rules/demo-stack.md` — autoloads when editing `sena-ai/demo_live_server.py` or `sena-ai/demo_client.html`. Standalone Gemini Live testbed at port 8082 (separate from production voice service).

## Deployment (EC2 — Docker)

**Reference:** `.claude/rules/deployment.md` — autoloads when editing `Dockerfile`, `docker-compose.deploy.yml`, or `.env.deploy*`. Full checklist: `sena-ai/DEPLOY_EC2_CHECKLIST.md`. Voice + onboarding deployed to EC2 (2026-05-14); case review shelved.

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

## Adding new project components

**Protocol:** `.claude/rules/add-component.md` — loads when user says "I am adding X." Mandates a documentation sweep across `CLAUDE.md` / `SESSION_START.md` / `TASKS.md` / `MEMORY.md` / `memory/project_<name>.md` BEFORE any code work begins.

## Paused Features

(none — see `.claude/tasks/TASKS.md` for the live work queue)

## Agent Routing Mandate (MANDATORY — added 2026-05-14)

<agent_routing priority="MANDATORY" type="cross-agent" enforcement="check-before-reply">

**BEFORE replying to ANY task in this repo, check if it maps to an agent in `.claude/agents/`. If yes, route via the Task tool — do NOT handle the work in the main thread.**

This rule fires when the request matches ANY of the rows below. The full pipeline order (planner → task-breaker → implementer → business-reviewer → security-reviewer → bug-fixer if FAIL → optimization-reviewer → cleaner → git-committer) lives in `.claude/rules/sena-rules.md` — follow it for non-trivial work.

| Trigger | Route to |
|---------|----------|
| Multi-file refactor / new feature spanning 3+ files / architecture decision | `@agent-sena-planner` (plan + DAG) then `@agent-sena-task-breaker` (atomic JSON tasks) |
| "Deep dive" / contract-first audit / multi-subsystem investigation / long debugging session | `@agent-sena-engineering-collaborator` |
| Greenfield Python coding (new file or full implementation from spec) | `@agent-sena-implementer` |
| Reviewer FAIL with hand-back contract (surgical patch needed) | `@agent-sena-bug-fixer` |
| NDIS / FormState / validator / advance_step / participant-facing code review | `@agent-sena-business-reviewer` |
| Tenant isolation / Redis key / Gemini-bridge / auth / webhook code review | `@agent-sena-security-reviewer` |
| Hot path (audio bridge, Redis loop, large JSON) optimisation | `@agent-sena-optimization-reviewer` |
| Final lint + artifact gate before commit | `@agent-sena-cleaner` |
| Conventional Commit generation (NEVER push) | `@agent-sena-git-committer` |
| Crash log / stack trace / pytest failure dump | `@agent-sena-log-analyzer` FIRST |
| Current third-party docs / library API / framework upgrade research | `@agent-sena-researcher` |
| Writing/updating CLAUDE.md / TASKS.md / SESSION_START.md / FLUTTER docs / README / handoff docs | `@agent-sena-doc-writer` |
| Ad-hoc external diff or non-SENA-path PR review (SHIP/FIX/BLOCK) | `@agent-sena-code-reviewer` |

**Exception:** trivial single-line edits, status questions, follow-ups on already-routed work, or direct-conversation requests may stay in the main thread.

**Failure mode (your action when the user corrects you):** If you reply in the main thread to a task that should have been routed, the user will say so. After ANY such correction, append a row to `.claude/memory/lessons.md` (format in that file) and tighten this table.

</agent_routing>

## Workflow Orchestration (MANDATORY — added 2026-05-14)

<orchestration priority="MANDATORY" type="cross-agent">

You operate as a Senior Orchestrator. Keep your main context window clean by delegating heavily.

### Plan-first default
- Enter plan mode for ANY task requiring 3+ steps or architectural decisions.
- Write detailed specs upfront in `.claude/tasks/TASKS.md` to reduce ambiguity.
- If execution goes sideways, STOP and re-plan immediately. Dynamic recalibration beats grinding through a bad plan.
- Use plan mode for verification steps too, not just building.

### Subagent delegation
- Spawn when: task needs 4+ file reads just for context; multiple independent searches can run in parallel; task produces large intermediate output you only need the conclusion of; task is 60%+ exploratory.
- Do NOT spawn: single edit or 2-step sequential change; context already loaded; spawning costs more than doing it directly.
- One focused task per sub-agent — never stuff multiple subtasks into one invocation.
- Specify output shape explicitly ("Return JSON list of {file, line, symbol}") — not "investigate and report back."
- Budget the agent: "Read at most 10 files. Report what you found if you can't answer in budget."
- Never let sub-agents modify the same file in parallel — edits serialize through you.
- After return: discard raw dumps, extract signal only. Never paste full sub-agent output — synthesize.

### Plan mode triggers
- Enter plan mode when: change touches 3+ files; architectural choice (new dep, schema change, public API); high blast radius (auth, migrations, deletions); ambiguous request with materially different paths.
- Skip for: typo fixes, single-line bugs, isolated test additions, formatting.
- Plan must include: Goal · Files to touch (create/edit/delete) · Files NOT to touch · Deps to add/remove + justification · Steps · Verification commands · Rollback plan.

### Dynamic recalibration
- Stop and replan when: step fails twice; plan was built on a wrong assumption; scope grew; about to touch a file not in the plan.
- Re-planning is not failure. Drifting silently from the plan IS failure.

### Root cause over symptom
- Understand WHY a test fails before changing anything.
- Never delete or `.skip()` a test to make it green.
- Never wrap failing calls in try/except to swallow the error.
- If the test is wrong, say so and fix it with justification.

### Elegance check (before finalizing any non-trivial change)
1. Is there an existing dep / utility that already does this?
2. Am I writing 40 lines where 8 would do?
3. Am I adding an abstraction with exactly one caller?
4. Would deleting code solve this better than adding code?

### Minimal blast radius
- Touch only what the task requires — no "while I'm here" refactors, no dep upgrades as side effects.
- Out-of-scope observations → `.claude/tasks/followups.md`, never the current diff.

### Verification gate
- Never mark a task complete without proving it works. Run tests, check logs, diff behaviours.
- Ask: "Would a Staff Engineer approve this?"
- Definition of Done lives in `.claude/rules/principal-engineer.md` — every checkbox must be true.

### Autonomous execution
- Bug report → point at logs / failing tests, find root cause, fix it. No permission-asking.
- Make every change as simple as possible — touch only what is absolutely necessary.

### Self-improvement loop
- After ANY user correction: append a pattern entry to `.claude/memory/lessons.md` (failure → user correction → explicit testable rule → scope).
- Read `.claude/memory/lessons.md` at session start to drop your mistake rate to zero.
- Same lesson 3× → promote from `lessons.md` into `CLAUDE.md` as a permanent rule.
- Lessons are about HOW Claude approaches work; technical bug recipes go to `.claude/issues-solved/INDEX.md` instead.

### Task management micro-loop
1. **Plan first** — write the plan to `.claude/tasks/TASKS.md` Active section with checkable items.
2. **Verify plan** — get user explicit approval before non-trivial implementation starts.
3. **Track progress** — mark items complete as you go.
4. **Explain changes** — high-level summary at each step.
5. **Document results** — add a review section to `TASKS.md` (or move the entry to `ARCHIVE.md` when the feature ships).
6. **Capture lessons** — update `lessons.md` after any user correction.

</orchestration>

## Principal Engineer Operating Mode (MANDATORY — added 2026-05-14)

<principal_engineer priority="MANDATORY" type="cross-agent">

All `.claude/agents/*.md` and the main session operate under the Principal Engineer rules. **Canonical file:** `.claude/rules/principal-engineer.md` (read it once; agents embed a `<principal_engineer_mode>` block that points back to it).

**Five pinned rules:**

1. **No reinvention.** Before writing custom code, `Grep` the repo + check installed deps (`pyproject.toml`, `services/<svc>/pyproject.toml`). Mature library beats hand-rolled — `pydantic`, `httpx`, `structlog`, `redis.asyncio`, `tenacity`, `pendulum`, `aiolimiter` are first-choice.
2. **No bloat.** Every new file requires a one-line justification (why an existing file can't hold this code). No unprompted `types.py` / `constants.py` / `utils.py` / barrel `__init__.py` re-exports.
3. **No stubs.** Working code or one sharp clarifying question — never TODOs, `pass`-bodies, or `raise NotImplementedError` outside abstract bases. (Exception: `# TODO(#123)` with a real ticket reference is fine.)
4. **Stay in scope.** Minimal diff. No opportunistic refactors of code unrelated to the task.
5. **Optimization is default.** `asyncio.gather` for parallel awaits, `redis.asyncio.pipeline` for batch ops, `set`/`dict` for O(1) lookups, guard clauses over nested `if`s.

**Instant-fail anti-patterns:** new file when an existing one would do; rebuilding what an installed dep provides; `Any` / `# type: ignore` / `# noqa` to silence tooling; refactoring "while you're there"; handing back a red build.

**One-line reminder:** *Search the repo. Check the deps. Use the library. Edit, don't write. Justify every file. Ship working code.*

</principal_engineer>

## Hard Limits (added 2026-05-11)

- Function length: aim ≤ 100 lines. Past 100 = refactor signal, not a hard error.
- Cyclomatic complexity: ≤ 8 per function (ruff `C901`).
- Line length: 100 chars (ruff enforced).
- Test file ratio: every new non-trivial function ships with a matching test in `services/<svc>/tests/`.
- No `print()`, `breakpoint()`, `import pdb` in committed code — structlog only.
- No `os.environ` direct reads — go through `core/settings.py`.
- No `time.sleep()` outside tests — async-first.
- No `Bash(rm -rf …)`, no `git push --force`, no push to `main` directly — enforced by `.claude/settings.json` deny list.

## Sena Agent System

- Read `.claude/rules/sena-rules.md` at session start for routing rules and constraints.
- Read `.claude/memory/sena-memory.md` to recall past decisions and outcomes.
- For non-trivial multi-file or multi-subsystem tasks, route through the Sena agents in `.claude/agents/`. Never handle work of that scope directly in the main session thread.
- Path-scoped rules in `.claude/rules/api.md` and `.claude/rules/database.md` load automatically when an edit touches a matching path — no manual invocation needed.
- After completing any significant task, append one line to `.claude/memory/sena-memory.md`:
  `[YYYY-MM-DD] [agent name or "main"] — [what was done] — [key outcome]`

<!-- Last auto-updated: 2026-04-16 00:23:07 by hook -->


## External tools (gstack + companion CLIs)

**Reference:** `.claude/rules/external-tools.md` — loads on demand when gstack / `/qa` / `/browse` / `/design-*` / `/investigate` / `/office-hours` / `agent-browser` / `specify` / `hivemind` are invoked. Key facts: gstack is user-global at `~/.claude/skills/gstack` (47 skills + native CLIs `browse`/`design`/`pdf`); SENA agents take precedence over gstack for tenant-isolation-critical code (don't use gstack `/review` or `/ship` for SENA paths); `hivemind install` is HELD pending NDIS APP 8/11 data-residency decision; `agent-browser` is Chromium-only (no Firefox).

## Auto-generated signatures
<!-- Updated by gen-context.js -->
# Code signatures

## deps
```
sena-ai\services\onboarding\src\onboarding\api\routes.py ← __future__, fastapi, pydantic, onboarding, structlog
sena-ai\services\onboarding\src\onboarding\models\schema_spec.py ← __future__, pydantic
sena-ai\services\onboarding\src\onboarding\services\prompt_builder.py ← __future__, onboarding, structlog
sena-ai\services\onboarding\src\onboarding\services\tools.py ← __future__, onboarding, structlog
sena-ai\services\onboarding\src\onboarding\services\validators\cross_field.py ← __future__, base
sena-ai\services\onboarding\src\onboarding\services\validators\field_rules.py ← __future__, base
sena-ai\services\onboarding\src\onboarding\services\validators\sequencing.py ← __future__, base, field_rules
sena-ai\services\onboarding\tests\test_prompt_builder.py ← __future__, unittest, onboarding, pytest
sena-ai\services\onboarding\tests\test_tools.py ← __future__, onboarding, pytest, pytest_asyncio
sena-ai\services\onboarding\tests\test_validators.py ← __future__, onboarding, pytest
```

## sena-ai

### sena-ai\ONBOARDING_WEBHOOK.md
```
h1 Onboarding Voice Session — Webhook Contract
h2 Trigger flow
h2 Webhook request
h3 Headers
h3 Signature verification
h2 Payload shape
h2 FormState — the data you need to save
h3 Scalar section (one set of fields)
h3 Repeatable section (list of rows, e.g. emergency contacts)
h3 FieldValue fields
h3 Completion stats
h2 Minimal persistence logic (pseudocode)
h2 Fallback: REST polling
h2 Flutter `step_completed` event (parallel notification)
h2 Environment variables to configure
h2 Step IDs → your onboarding step mapping
code-fence plain
code-fence ---
code-fence python
code-fence jsonc
code-fence json
```

### sena-ai\services\onboarding\FLUTTER_DEV_DELETE_REPEATABLE_ROW.md
```
h1 Flutter Dev Handoff — Repeatable-Row Deletion via Voice
h2 1. Trigger flow (server-side, for context)
h2 2. WebSocket event contracts
h3 `row_deleted` (delta event — primary trigger)
h3 `state` (full snapshot — reconciliation)
h2 3. Required Flutter handler
h2 4. Required UX behaviour
h2 5. Sequence with `field_updated` / re-numbering
h2 6. Manual test recipe
h2 7. Open work (track on your side)
h2 8. Server contract summary (one-line)
code-fence plain
code-fence jsonc
code-fence dart
```

### sena-ai\services\onboarding\src\onboarding\api\routes.py
```
class CreateSessionRequest(BaseModel) {participant_id*, step*, schema*}
class CreateSessionResponse(BaseModel) {session_id*, ws_url*, expires_at*}
class UpdateStateRequest(BaseModel) {values*}
class ClientValidationErrorRequest(BaseModel) {input_method*, ts*}
async def health_live() → dict
POST /v1/onboarding/session  →  create_session()
GET /v1/onboarding/session/{session_id}/state  →  get_state()
PUT /v1/onboarding/session/{session_id}/state  →  update_state()
POST /v1/onboarding/session/{session_id}/complete  →  complete_session()
GET /v1/onboarding/_diag/bucket  →  diag_bucket()
GET /health/live  →  health_live()
GET /health/ready  →  health_ready()
```

### sena-ai\services\onboarding\src\onboarding\models\schema_spec.py
```
class FieldType(str, Enum)
class FieldSpec(BaseModel) {id*, type*, label?, required?, options?, pattern?}
class RepeatableConfig(BaseModel) {min?, max?}
class SectionSpec(BaseModel) {id*, label*, fields?, item_fields?, repeatable?, copy_from_if_flagged?}
class StepSchema(BaseModel) {version?, step_id*, step_label*, progress_percent?, sections*, voice_coverage?}
```

### sena-ai\services\onboarding\src\onboarding\prompts\onboarding_system copy.md
```
h2 DIALOGUE STATE MACHINE — STRICT ENFORCEMENT
h3 STATES
h3 THE LOOP
h3 CONDITIONAL BRANCHING — DRIVEN BY THE SERVER
h3 THE FIELD-RENDER INVARIANT (HARD RULE)
h3 VALIDATION CONTRACT — YOU ARE BLIND, THE SERVER IS THE JUDGE
h2 REPEATABLE SECTIONS — CANONICAL USE OF add_repeatable_row
h3 When the user wants another row
h3 FORBIDDEN
h3 Parallel-field dictation (medication / allergy blocks)
h2 OPTIONAL FIELDS — DO NOT SKIP
h2 CONTEXT RECOVERY — WHEN THE STATE BLOCK LOOKS EMPTY
h2 ADDRESS THE PARTICIPANT
h1 Sena — Onboarding Voice Agent System Instruction
h2 ABSOLUTE STATE AUTHORITY — READ CAREFULLY
h3 JSON-as-Truth Protocol — MANDATORY pre-flight before every question
h2 SCHEMA AND TOOLS
h2 BEHAVIOURAL RULES (numbered to match the platform contract)
h3 Rule 1 — Strict Session Isolation
h3 Rule 2 — Multi-Page Handoff
h3 Rule 3 — Pre-Filled Data Handling
h3 Rule 4 — Exhaustive Entity Extraction (Multi-Value Capture)
h3 Rule 5 — Proactive Optional Prompting
h3 Rule 6 — Dynamic UI Updates
h3 Rule 7 — Advisory Validation Feedback
```

### sena-ai\services\onboarding\src\onboarding\prompts\onboarding_system.md
```
h1 Sena — Onboarding Voice Agent System Instruction
h2 1. ABSOLUTE STATE AUTHORITY
h3 JSON-as-Truth Protocol — pre-flight before every question
h3 Bootstrap mode behaviour
h3 Context recovery — empty state on a non-first step
h2 2. SCREEN IS THE SOURCE OF TRUTH
h2 3. SCHEMA AND TOOLS
h2 4. DIALOGUE STATE MACHINE — STRICT
h3 Conditional branching
h3 FIELD-RENDER INVARIANT — HARD
h3 Validation contract — server is the judge
h3 Tool honesty + Tool-BEFORE-talk — ABSOLUTE
h2 5. REPEATABLE SECTIONS
h3 Add a row (user says "another contact / goal / etc")
h3 FORBIDDEN
h3 Parallel-field dictation (single-breath row)
h2 6. ADDRESS THE PARTICIPANT
h3 Greeting cadence
h3 Name rules
h2 7. BEHAVIOURAL RULES (numbered to match the platform contract)
h3 Rule 1 — Strict Session Isolation
h3 Rule 2 — Multi-Page Handoff
h3 Rule 3 — Pre-Filled Data Handling
h3 Rule 4 — Multi-Value Capture
h3 Rule 5 — Proactive Optional Prompting
```

### sena-ai\services\onboarding\src\onboarding\services\prompt_builder.py
```
def build_system_prompt(schema: StepSchema, state: FormState, *, grounding_enabled: bool, screen_context_text: str | None, resume_context_text: str | None, bootstrap: SessionBootstrap | None, cross_screen_text: str | None, screen_field_status: dict[str, str] | None) → str
```

### sena-ai\services\onboarding\src\onboarding\services\tools.py
```
class PolicyBlockSignal(BaseException)
  def __init__(question: str) → None
class ToolDispatcher
  def set_turn_id(turn_id: int) → None
  async def dispatch(name: str, args: dict[str, Any]) → dict[str, Any]
```

### sena-ai\services\onboarding\src\onboarding\services\validators\cross_field.py
```
def check_emergency_email_unique_and_differs_from_client(state_values: dict[str, Any]) → list[ValidationRejection]
def check_emergency_phone_unique_and_differs_from_client(state_values: dict[str, Any]) → list[ValidationRejection]  # NDIS rule: emergency contact phone must not equal the partic
def check_plan_end_after_start(state_values: dict[str, Any]) → list[ValidationRejection]
def check_medical_history_all_or_none(state_values: dict[str, Any]) → list[ValidationRejection]
def check_time_slot_no_overlap(slots: list[dict[str, Any]]) → list[ValidationRejection]
def check_support_schedule_time_order(state_values: dict[str, Any]) → list[ValidationRejection]  # schedule_of_supports[*]: end_time MUST be strictly greater t
def validate_cross_fields(state_values: dict[str, Any]) → list[ValidationRejection]
```

### sena-ai\services\onboarding\src\onboarding\services\validators\field_rules.py
```
def validate_field(section_id: str, field_id: str, value: Any, *, repeatable_index: int | None, state: Any, field_spec: Any) → ValidationRejection | None  # Return None if valid, ValidationRejection if the rule fires
```

### sena-ai\services\onboarding\src\onboarding\services\validators\sequencing.py
```
def next_required_field(schema: StepSchema, state: FormState, *, screen_field_status: dict[str, str] | None) → dict | None
def next_optional_field(schema: StepSchema, state: FormState, *, screen_field_status: dict[str, str] | None) → dict | None
def section_min_unmet(section: SectionSpec, section_values: Any) → bool  # Return True when a repeatable section has fewer rows than it
def validate_step_complete(schema: StepSchema, state: FormState) → list[ValidationRejection]  # Aggregate gate for /complete — returns [] only if every requ
def validate_required_only(schema: StepSchema, state: FormState) → list[ValidationRejection]  # Per-field required/validation rejections only — cross-field 
```

### sena-ai\services\onboarding\SYSTEM_OVERVIEW.html
```
title: SENA Onboarding — System Overview
section#overview
section#architecture
marker#arrow
section#lifecycle
section#json
section#tools
section#events
section#webhook
section#fsm
section#validation
section#prompt
section#rules
section#bucket
section#silence
section#redis
section#errors
section#env
section#timeline
section#flutter
```

### sena-ai\services\onboarding\tests\test_prompt_builder.py
```
def test_participant_name_token_interpolated_when_present(monkeypatch) → None
def test_participant_name_token_falls_back_to_unknown_when_missing(monkeypatch) → None
def test_next_optional_field_token_interpolated(monkeypatch) → None
def test_next_optional_field_token_empty_when_none_remain(monkeypatch) → None
def test_routine_sections_are_optional_with_zero_rows() → None  # morning_routine and evening_routine both have min=0 — empty 
def test_routine_sections_optional_one_row_still_ok() → None  # Adding one morning_routine row is fine; the optional evening
def test_routine_sections_optional_both_filled() → None  # Both routines populated — still no required gap
def test_render_pending_errors_includes_allowed_values() → None  # allowed_values line appears when the error entry carries the
def test_render_pending_errors_no_allowed_values_for_non_enum() → None  # No allowed_values line when the key is absent (non-enum erro
def test_build_system_prompt_contains_rule_13_and_14() → None  # Rules 13 and 14 must appear in the rendered system prompt
def test_visible_if_hidden_fields_removed_from_prompt_schema() → None  # When plan_management
def test_visible_if_fields_present_when_condition_satisfied() → None  # Inverse: when plan_management == 'Plan Managed', the conditi
def test_screen_field_status_is_authoritative_over_schema() → None
def test_next_optional_field_respects_screen_field_status() → None  # next_optional_field MUST NOT surface a field whose path isn'
def test_no_literal_field_names_in_prompt_template() → None  # The prompt template MUST NOT carry literal field names for f
def test_rule_21a_screen_source_of_truth_in_prompt() → None  # Rule 21a (SCREEN is source of truth) is the explicit prompt 
```

### sena-ai\services\onboarding\tests\test_tools.py
```
def personal_schema() → StepSchema
async def seeded_repo(fake_redis, personal_schema)  # Repo with a fresh FormState + schema saved for session_id='s
def emitted() → list[dict]  # Captures every event the dispatcher would send over the WS
async def dispatcher(seeded_repo, personal_schema, emitted)
def test_function_decls_cover_all_handlers() → None
async def test_update_field_happy_path(dispatcher, seeded_repo, emitted) → None
async def test_update_field_coerces_boolean(dispatcher, seeded_repo) → None
async def test_update_field_unknown_section(dispatcher) → None
async def test_update_field_unknown_field(dispatcher) → None
async def test_update_field_repeatable_with_index(dispatcher, seeded_repo) → None
async def test_update_field_repeatable_exceeds_max(dispatcher) → None
async def test_get_session_context_reports_progress(dispatcher) → None
async def test_advance_step_rejects_when_incomplete(dispatcher) → None
async def test_advance_step_rejects_empty_confirmation_transcript(dispatcher) → None
async def test_advance_step_rejects_short_confirmation_transcript(dispatcher) → None
async def test_advance_step_cross_field_gate_blocks_on_rejection(dispatcher, seeded_repo, personal_schema, emitted, monkeypatch) → None
async def test_advance_step_emits_validation_rejection_for_cross_field_violation(dispatcher, seeded_repo, personal_schema, emitted, monkeypatch) → None
async def test_advance_step_fires_webhook_when_complete(dispatcher, seeded_repo, personal_schema, emitted, monkeypatch) → None
async def test_escalate_incident_appends_and_emits(dispatcher, seeded_repo, emitted) → None
async def test_add_repeatable_row_pins_focus_to_new_index(dispatcher, seeded_repo) → None
async def test_add_repeatable_row_emits_repeatable_section_entered(dispatcher, emitted) → None
async def test_dispatch_unknown_tool(dispatcher) → None
async def test_service_address_auto_copies_when_flag_default_true(dispatcher, seeded_repo, emitted) → None  # service_same_as_home defaults to true in the schema; filling
async def test_service_address_no_copy_when_flag_explicit_false(dispatcher, seeded_repo, emitted) → None  # When the user explicitly says 'service address differs from 
async def test_service_address_copies_after_flag_flip_to_true(dispatcher, seeded_repo) → None  # Flag explicitly set to True after home_address is already po
```

### sena-ai\services\onboarding\tests\test_validators.py
```
class TestCrossFields
  def test_empty_values_no_rejections()
  def test_plan_end_after_start_passes()
  def test_plan_end_before_start_fails()
  def test_plan_end_same_as_start_fails()
  def test_emergency_email_matches_client_fails()
  def test_emergency_email_different_from_client_passes()
  def test_emergency_email_duplicate_across_rows_fails()
  def test_emergency_email_unique_across_rows_passes()
class TestNextRequiredField
  def test_empty_state_returns_dict()
  def test_empty_state_first_section_is_basics()
  def test_filling_basics_moves_past_basics()
  def test_ndis_schema_empty_returns_plan_info_field()
  def test_result_is_none_or_dict()
class TestValidateStepComplete
  def test_empty_state_has_rejections()
  def test_empty_state_contains_required_field_missing()
  def test_invalid_phone_produces_field_rejection()
  def test_all_rejections_have_human_reason()
  def test_ndis_empty_state_produces_rejections()
  def test_medical_empty_state_produces_rejections()
class _FakeFieldSpec
  def __init__(field_type: str, options: list[str]) → None
class TestValidateFieldEnumOptions
```

### sena-ai\services\onboarding\WEBHOOK_INTEGRATION.md
```
h1 SENA Onboarding — Webhook Integration Guide
h2 When the webhook fires
h2 Configuration (server-side env vars)
h2 HTTP request
h2 Payload shape
h3 `state` — full FormState snapshot
h3 `transcript` — conversation turns
h2 Signature verification
h2 Your endpoint contract
h2 What NOT to do
h2 Testing locally
h2 Environment variable quick-reference
code-fence plain
code-fence json
code-fence ---
code-fence python
code-fence typescript
code-fence env
```
