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

## code-review-graph (blast-radius analysis)

MCP server providing precise call-graph impact analysis via Tree-sitter AST. Complementary to graphify: graphify = community structure + architecture; code-review-graph = precise callers/dependents/affected tests for a specific symbol or file.

**MCP server:** `code-review-graph` (wired in `.claude/settings.json`) — auto-watches for file changes.
**Graph DB:** `.code-review-graph/graph.db` (auto-built, gitignored).

**Use before any non-trivial edit:**
- `get_callers(symbol)` — who calls this function?
- `get_dependents(file)` — what imports/uses this module?
- `get_affected_tests(file_or_symbol)` — which tests exercise this code?
- `detect_changes(file)` — what downstream nodes are affected by a change here?

**Rule:** Before editing any file touched by 3+ other modules (check `get_dependents`), run blast-radius analysis first. If affected test count > 5 or callers span multiple services, flag to user before proceeding.

**Rebuild manually if graph is stale:**
```powershell
& "C:\Users\Admin\Downloads\SENA\.venv\Scripts\code-review-graph.exe" build --repo "C:\Users\Admin\Downloads\sena-mobile\sena-mobile\SENA_AI"
```

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
  - **Flag locations:** `.claude/hooks-state/skills-gemini.flag` and `.claude/hooks-state/ctx7-gemini.flag` (cleared by SessionStart hook on every new session — must be re-earned). (`.claude/state/` was removed 2026-05-25 — it was a dead duplicate path, never written to by live hooks.)
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
| Stuck / exploring options / starting a new feature — needs 3 clarifying questions + 2-3 paths (NO code) | `@agent-sena-brainstorm` |
| Comparing 2-3 options (libraries / patterns / models) — steelman + table + recommendation | `@agent-sena-tradeoffs` |
| Bug / error / mysterious behaviour BEFORE you have a stack trace — Socratic root-cause walk | `@agent-sena-debug` (use `@agent-sena-log-analyzer` FIRST if you have a trace) |
| Incident retrospective — blameless 5-Whys + three-tier prevent/detect/recover with owners and ETAs | `@agent-sena-postmortem` |
| Sign-off gate before commit / `/sena-feature-ship` / staging — DENIED/CONDITIONAL/APPROVED verdict from `sena-lints.md` | `@agent-sena-approve` |
| Deep verified explanation of a concept / library / pattern (Context7-verified, 7-section structure) | `@agent-sena-explain` |

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

## Pre-flight for Python edits (MANDATORY — added 2026-05-25)

<preflight priority="MANDATORY" type="hook-gate-bypass-prevention">

**Before the first Python (`.py`) Write/Edit in any new session — orchestrator OR sub-agent — run this checklist. Hooks are a fallback, not your primary blocker.**

### The checklist (orchestrator's main session, BEFORE any `.py` edit and BEFORE spawning Python implementers)

| Step | Action | Sets flag |
|------|--------|-----------|
| 1 | Call `mcp__plugin_context7_context7__resolve-library-id` once for any library you will use (`google-genai`, `pydantic-settings`, `fastapi`, etc.). | `.claude/hooks-state/ctx7-session.flag` |
| 2 | Only if the task plausibly touches `gemini*` / `demo_live*` files: invoke `Skill: gemini-live-api-dev`. | `.claude/hooks-state/skills-gemini.flag` |
| 3 | Only if (2): also call `Context7 query-docs` for `google-genai`. | `.claude/hooks-state/ctx7-gemini.flag` |
| 4 | Verify the relevant flag file exists with `ls .claude/hooks-state/` BEFORE spawning the first sub-agent. | — |

### Hard rules (instant-fail if violated)

1. **Sub-agents CANNOT clear gates for themselves.** Gate-clearing is the orchestrator's job in the main session. Sub-agents inherit via filesystem flag files; they cannot reliably invoke MCP tools to set their own session's flags. Never include "if blocked, call Context7 yourself" instructions in a sub-agent brief.
2. **Never `touch` a flag file directly.** That trips the Auto-Mode-Bypass classifier. The only legitimate way to set a flag is to invoke the prerequisite tool that the PostToolUse hook listens for.
3. **Verify flag file existence, not just "I called Context7."** If `ctx7-session.flag` is missing from `.claude/hooks-state/`, the gate WILL fire. If your MCP call doesn't trigger the postaction hook, you have a `settings.json` matcher bug — see hard rule 4.
4. **When a flag isn't landing despite the trigger condition, FIRST diagnose `.claude/settings.json` `hooks.PostToolUse[].matcher`.** The matcher uses anchored regex; bare strings only match exact tool names. For Context7: `"matcher": "mcp__plugin_context7_context7__.*"` is correct; `"matcher": "mcp__plugin_context7"` will silently never fire.
5. **For parallel sub-agent spawns:** the gate is session-singleton. One Context7 call in the orchestrator clears it for all parallel sub-agents that follow. Don't make four agents each try to clear it themselves.

### Why this exists

Five separate instances in one session (2026-05-25): agents blocked, retries, security flags on attempted bypasses, settings.json matcher diagnosed late. Token cost was material. Captured as 5 entries in `.claude/memory/lessons.md` and promoted here on user authority. **The hook is not the enemy — it enforces real safety. The wasted cost comes from triggering it after the fact instead of satisfying it before.**

### Quick reference — the three gates in `pre-tool-use.sh`

| Rule | Trigger | Flag location |
|------|---------|---------------|
| Rule 1 (WRITE GUARD) | Write/Edit outside `SENA_AI/` | n/a — always enforced |
| Rule 2 (CONTEXT7) | First `.py` Write/Edit per session | `.claude/hooks-state/ctx7-session.flag` |
| Rule 3 (GEMINI) | Write/Edit on `gemini*` / `demo_live*` | `.claude/hooks-state/skills-gemini.flag` AND `.claude/hooks-state/ctx7-gemini.flag` (BOTH required) |

</preflight>

---

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
sena-ai\scripts\mongo_usage_diagnose.py ← __future__
sena-ai\services\case_review\src\case_review\models\db.py ← __future__, sqlalchemy
sena-ai\services\case_review\src\case_review\services\classify_service.py ← __future__, case_review, structlog
sena-ai\services\case_review\src\case_review\services\context_service.py ← __future__, case_review, structlog
sena-ai\services\case_review\src\case_review\services\llm\classifier.py ← __future__, google, pydantic, case_review, structlog
sena-ai\services\case_review\src\case_review\services\llm\summarizer.py ← __future__, google, pydantic, case_review, structlog
sena-ai\services\onboarding\src\onboarding\api\routes.py ← __future__, fastapi, pydantic, onboarding, structlog
sena-ai\services\onboarding\src\onboarding\models\turn_payload.py ← __future__, pydantic
sena-ai\services\onboarding\src\onboarding\services\gemini_live.py ← __future__, fastapi, google, onboarding, structlog
sena-ai\services\onboarding\src\onboarding\services\mobile_bridge.py ← __future__, structlog
sena-ai\services\onboarding\src\onboarding\services\prompt_builder.py ← __future__, onboarding
sena-ai\services\onboarding\src\onboarding\services\tools.py ← __future__, structlog
sena-ai\services\onboarding\tests\test_prompt_builder.py ← __future__, onboarding
sena-ai\services\voice\src\voice\services\bedrock_service.py ← __future__, botocore, fastapi, voice, boto3
sena-ai\services\voice\src\voice\services\dictation_service.py ← __future__, fastapi, sqlalchemy, voice
sena-ai\shared\src\sena_common\mongo_usage_logger.py ← __future__, structlog
sena-ai\shared\src\sena_common\usage_logger.py ← __future__, structlog
sena-ai\shared\tests\test_mongo_usage_logger.py ← __future__, sena_common
sena-ai\shared\tests\test_usage_logger.py ← __future__, sena_common
```

## sena-ai

### sena-ai\scripts\mongo_usage_diagnose.py
```
def main() → int
```

### sena-ai\services\case_review\src\case_review\models\db.py
```
class Base(DeclarativeBase)
class RollingSummary(Base)
class ReviewSession(Base)
class IncidentDraft(Base)
class ReviewAuditLog(Base)
```

### sena-ai\services\case_review\src\case_review\services\classify_service.py
```
async def classify_paragraph(*, repo: ReviewRepo, tenant_id: uuid.UUID, user_id: uuid.UUID, req: ClassifyRequest) → ClassifyResponse
```

### sena-ai\services\case_review\src\case_review\services\context_service.py
```
async def get_context(*, repo: ReviewRepo, client: CaseNoteClient, tenant_id: uuid.UUID, staff_id: uuid.UUID, client_id: uuid.UUID, limit: int) → ContextResponse  # Fetch + summarise case notes for a staff-client pair
```

### sena-ai\services\case_review\src\case_review\services\llm\classifier.py
```
class _FieldClassification(BaseModel) {field_id*, value?, confidence?}
class _ReaskPromptOutput(BaseModel) {field_id*, label*, reason*, suggested_question*}
class _GeminiClassifyOutput(BaseModel) {field_classifications*, missing_required*, reask_prompts*}
class ClassifyResult(BaseModel) {classified_fields*, confidence*, missing_required*, reask_prompts*}
async def classify(raw_paragraph: str, *, api_key: str, model_id: str, tenant_id: str, user_id: str | None, session_id: str | None) → ClassifyResult  # Classify raw_paragraph into structured case note fields
```

### sena-ai\services\case_review\src\case_review\services\llm\summarizer.py
```
class SummaryResult(BaseModel) {summary_text*, metadata*}
class SummaryMetadata(BaseModel) {note_count*, last_dates*, incident_count*, risk_flags*}
class _GeminiSummaryOutput(BaseModel) {summary_text*, metadata*}
async def summarise(past_summary: str, new_notes: list[CaseNoteDTO], *, api_key: str, model_id: str, tenant_id: str, user_id: str | None, session_id: str | None, feature: UsageFeature) → SummaryResult  # Compress past_summary + new_notes into an updated rolling su
```

### sena-ai\services\onboarding\FLUTTER_HANDOFF_CONSENT_FIX.md
```
h1 Flutter Handoff — Consent Screen Voice Sync Fix (Step 6)
h2 1. The symptom (what the participant experiences)
h2 2. Root cause — a read/write namespace mismatch
h3 The data flow
h3 Why it's a "mismatch"
h2 3. A prompt-only workaround was attempted and REVERTED — here's why it can't work
h2 4. Fix 1 — make the resolver accept the `consent.` namespace (REQUIRED, ~7 lines)
h2 5. Fix 2 — per-role access detail (`access_control.<ROLE>.*`)
h3 Current state: SCREEN-ONLY (and the prompt now treats it that way)
h3 Optional: make per-role voice-fillable
h2 6. Fix 3 — written-consent checkbox (`has_given_written_consent`)
h3 Current state: SCREEN-ONLY (correct)
h2 6a. Fix 4 — voice `submit_step` must ADVANCE to review, NOT final-submit (REQUIRED — fixes the deadlock)
h3 Symptom
h3 Root cause (Flutter)
h3 Fix
h2 7. Bonus check — the boolean default-false issue
h2 8. Acceptance criteria
h2 9. How the server workaround and Fix 1 interact (no conflict)
h2 10. File reference summary
code-fence dart
code-fence plain
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

### sena-ai\services\onboarding\src\onboarding\models\turn_payload.py
```
class Participant(BaseModel)
class StepInfo(BaseModel) {id*, label*, number*}
class VisibleField(BaseModel) {path*, label*, type*, required*, readonly*}
class NextTarget(BaseModel) {path*, label*, reason*}
class LastRejection(BaseModel) {path*, reason*}
class PendingConfirmation(BaseModel) {path*, heard_value*}
class TurnPayload(BaseModel) {participant*, step*, bootstrap_mode*, visible_fields*}
```

### sena-ai\services\onboarding\src\onboarding\prompts\modes\fresh.md
```
h2 MODE: FRESH FORM — first-time data capture
h3 Open the conversation
h3 Collection loop (repeat for every empty required field)
h3 Repeatable sections
h3 When to submit
h3 Do NOT in fresh mode
```

### sena-ai\services\onboarding\src\onboarding\prompts\modes\update.md
```
h2 MODE: UPDATE FORM — participant is editing pre-filled data
h3 Open the conversation
h3 The only two flows
h3 Submitting
h3 HARD RULES (the prompt's biggest failure mode in update flows)
h3 Do NOT in update mode
```

### sena-ai\services\onboarding\src\onboarding\prompts\onboarding_system.md
```
h1 Sena — Onboarding Voice Agent
h2 1. Source of truth — the latest tool reply
h2 1a. Forbidden phrases without a matching tool reply
h2 1b. Staleness self-check
h2 2. CAPTURING A VALUE — CALL THE TOOL FIRST, ALWAYS
h3 Use ONLY the field names from `visible_fields[].path`
h3 Required sequence
h3 Forbidden phrases without a preceding tool call
h3 Value formats — YOU convert, the screen validates
h3 Worked example — date of birth change
h3 Worked example — new emergency contact name
h2 4. Repeatable rows
h2 5. Submitting & going back
h2 6. Seven tools
h2 7. Voice rules
h2 8. Bootstrap state — first turn only (DO NOT READ ALOUD)
```

### sena-ai\services\onboarding\src\onboarding\prompts\steps\consent.md
```
h2 Step-specific rules — Consent (final onboarding step)
h3 Section + field naming — split the path EXACTLY as shown
h3 VOICE-FILLABLE fields (call `update_field`; section is always `consent`)
h3 SCREEN-ONLY fields — DIRECT the participant, NEVER call `update_field`
h3 Consent booleans — `false` means NOT YET ANSWERED, not "answered no"
h3 Driving the screen
h3 Submitting — advance to the final review screen
```

### sena-ai\services\onboarding\src\onboarding\prompts\steps\documents.md
```
h2 Step-specific rules — Documents (Step 4)
h3 Document uploads — voice opens the picker, user picks the file
h3 Slot names — use the EXACT label from `visible_fields[].label`
h3 Section: `documents.{slot_id}` (per backend-defined slot)
h3 Section: `other_documents` (repeatable, min 0, max 5)
h3 Conditional visibility
h3 Submission and progression — sequential only
code-fence plain
```

### sena-ai\services\onboarding\src\onboarding\prompts\steps\ndis_plan_details.md
```
h2 Step-specific rules — NDIS Plan Details (Step 3)
h3 Section: `plan_info` — identification & dates
h3 Section: `plan_info` — plan management (enum)
h4 Conditional fields — visible ONLY when `plan_management == PLAN_MANAGED`
h3 Section: `ndis_goals` (repeatable, min 1, max 10)
h3 Section: `support_coordinator` (READONLY)
h3 Section: `fund_allocations` (all 4 optional)
h3 Section: `support_schedule` (repeatable, min 1, max 5)
h4 `preferred_schedule` — VOICE-MUTABLE (set days + times by voice)
h3 Walk-through order for a new support_schedule row
h3 Enum strictness — read the list verbatim
h3 Submission and progression — sequential only
h3 Cross-field rules to enforce
code-fence plain
```

### sena-ai\services\onboarding\src\onboarding\prompts\steps\personal_information.md
```
h2 Step-specific rules — Personal Details (Step 1)
h3 Section: `basics`
h3 Section: `home_address`
h3 Section: `service_address` (conditional group)
h3 Section: `emergency_contacts` (repeatable, min 1, max 5)
h3 Walk-through order for a new emergency contact row
h3 Enum strictness — read the list verbatim
h3 Submission and progression — sequential only
h3 Cross-field rules to enforce
```

### sena-ai\services\onboarding\src\onboarding\services\gemini_live.py
```
class GeminiLiveSession
  async def run() → None
```

### sena-ai\services\onboarding\src\onboarding\services\mobile_bridge.py
```
class _WSLike(Protocol)
  async def send_text(data: str) → None
class MobileBridge
  def __init__(ws: _WSLike, *, timeout_sec: float) → None
  async def dispatch(tool: str, args: dict[str, Any]) → dict[str, Any]
  def resolve(request_id: str, result: dict[str, Any]) → None
```

### sena-ai\services\onboarding\src\onboarding\services\prompt_builder.py
```
def build_system_prompt(turn: TurnPayload, *, grounding_enabled: bool, voice_coverage: list[str] | None) → str
```

### sena-ai\services\onboarding\src\onboarding\services\tools.py
```
class _Bridge(Protocol)
  async def dispatch(tool: str, args: dict[str, Any]) → dict[str, Any]
class ToolDispatcher
  def set_turn_id(turn_id: int) → None
  async def dispatch(name: str, args: dict[str, Any]) → dict[str, Any]
```

### sena-ai\services\onboarding\tests\test_prompt_builder.py
```
def test_prompt_substitutes_first_name() → None
def test_prompt_substitutes_step_label() → None
def test_prompt_contains_turn_json_block() → None
def test_prompt_lists_all_six_tool_names() → None
def test_prompt_no_legacy_placeholders_remain() → None
def test_prompt_first_name_empty_still_renders() → None
def test_prompt_includes_grounding_section_when_enabled() → None  # personal_information
def test_prompt_includes_voice_coverage_block_when_provided() → None  # personal_information
def test_prompt_includes_per_step_fragment_when_present() → None  # personal_information
def test_prompt_omits_step_fragment_for_unknown_step() → None  # Unknown step
def test_prompt_step_rules_placeholder_consumed() → None  # Placeholder must never leak into the rendered prompt
def test_prompt_mode_rules_placeholder_consumed() → None  # __MODE_RULES__ must always be substituted, even with no mode
def test_prompt_fresh_mode_when_all_required_empty() → None  # All required fields null → fresh-mode rules load
def test_prompt_update_mode_when_required_field_filled() → None  # Any required non-readonly field with a value → update-mode r
def test_prompt_mode_ignores_readonly_filled_fields() → None  # A filled readonly field must NOT flip the form into update-m
```

### sena-ai\services\voice\src\voice\services\bedrock_service.py
```
class BedrockService
  def __init__()
```

### sena-ai\services\voice\src\voice\services\dictation_service.py
```
class DictationService
```

### sena-ai\shared\src\sena_common\mongo_usage_logger.py
```
def log_usage(screenname: str, input_token: int, output_token: int, error: str | None, *, user: str) → str | None  # Record token usage into the per-user document
```

### sena-ai\shared\src\sena_common\usage_logger.py
```
class UsageFeature(str, enum.Enum)
  VOICE_ONBOARDING="voice_onboarding"
  CASE_NOTE_DRAFTING="case_note_drafting"
  CASE_NOTE_SUMMARY="case_note_summary"
def emit_usage(*, tenant_id: str, user_id: str | None, feature: UsageFeature, model: str, session_id: str | None, prompt_tokens: int, response_tokens: int, cached_tokens: int, prompt_audio_tokens: int, response_audio_tokens: int, audio_seconds_in: float, audio_seconds_out: float, tool_call_count: int, latency_ms: int | None, success: bool, failure_reason: str | None, **extras: Any) → None
```

### sena-ai\shared\tests\test_mongo_usage_logger.py
```
class _Result
  def __init__(matched: int) → None
def test_log_usage_noop_when_disabled(monkeypatch) → None
def test_first_event_pushes_screen_entry_into_user_doc(monkeypatch) → None
def test_same_screen_increments_instead_of_duplicating(monkeypatch) → None
def test_log_usage_never_raises_on_failure(monkeypatch) → None
```

### sena-ai\shared\tests\test_usage_logger.py
```
def test_mapping_prefers_participant_and_step() → None
def test_mapping_falls_back_to_user_id_then_feature() → None
def test_emit_usage_forwards_full_record(monkeypatch: pytest.MonkeyPatch) → None
def test_kill_switch_prevents_pool_creation(monkeypatch: pytest.MonkeyPatch) → None
```
