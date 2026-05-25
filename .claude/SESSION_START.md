---
title: Session Start Guide
updated: 2026-05-25
purpose: Single entry-point doc. Future-Claude reads this FIRST in a new session to land in same state.
---

# Read-order for resuming SENA work

Read these files IN ORDER at the start of any new session. Stop when you have enough context for the user's current request.

## §0 — Pre-flight for Python edits (CHECK FIRST if user's request touches `.py`)

If the request will lead to any `.py` Write/Edit, run the pre-flight checklist in `CLAUDE.md ## Pre-flight for Python edits` BEFORE diving in. One Context7 call clears the generic gate; touching Gemini code requires the Skill + Gemini-specific Context7 query too.

**Skipping this step costs ~5 wasted iterations** (multiple sub-agents blocked + retries + diagnosis). Captured as five lessons in `.claude/memory/lessons.md` (2026-05-25). The hooks aren't your enemy — they're the safety floor. Satisfy them upfront, not after they fire.

> **State as of 2026-05-14:** Voice assistance feature is **closed and deployed** (EC2,
> `docker-compose.deploy.yml`); Case Review service is **shelved at Phase C**. Both feature
> histories live in `.claude/tasks/ARCHIVE.md`. The next feature has not started — `TASKS.md`
> shows an empty Active section. Do NOT carry voice/case-review planning context into a new
> feature unless the work directly extends shipped infrastructure.

## 1. MUST-READ (always)

| # | File | Why |
|---|------|-----|
| 1 | `CLAUDE.md` (project root) | Hard rules, architecture, Gemini API rules, cleanup rule |
| 2 | `.claude/SESSION_START.md` (this file) | Tells you what to read next |
| 3 | `.claude/tasks/TASKS.md` | Current task state (active queue, backlog). Empty Active = awaiting new-feature direction |
| 4 | `.claude/issues-solved/INDEX.md` | Grep-first symptom→fix table. Check BEFORE debugging anything. |
| 5 | `~/.claude/projects/C--Users-Admin-Downloads-SENA/memory/MEMORY.md` | Memory index — points to all user/project/feedback memories |

## 2. READ-IF-RELEVANT (task-dependent)

| Task area | Read |
|-----------|------|
| Investigating shipped voice code | `.claude/tasks/ARCHIVE.md` Feature A → then specific service paths under `sena-ai/services/onboarding/` |
| Investigating shipped case-review code | `.claude/tasks/ARCHIVE.md` Feature B → `.planning/CASE_NOTE_REVIEW_PLAN.md` |
| Gemini Live bugs (any service still using Live API) | `memory/feedback_gemini_live_patterns.md`, `memory/project_voice_demo_working.md` |
| Onboarding validation contract (Flutter still pending) | `SENA_AI/flutterhandoffdev.md` — canonical Step-1 handoff |
| Architecture / code structure overview | `graphify-out/GRAPH_REPORT.md` |
| Blast-radius before editing a heavily-imported file | MCP `code-review-graph` — `get_dependents(file)`, `get_callers(symbol)`, `get_affected_tests(file)`. Rebuild: `& "C:\Users\Admin\Downloads\SENA\.venv\Scripts\code-review-graph.exe" build --repo .` |
| NDIS domain / compliance | specific files in `ndis_markdown_docs/` (never the whole folder) |
| Agent pipeline + routing (planner → implementer → reviewer chain) | `.claude/rules/sena-rules.md` |
| API / WS event canonical list (path-scoped, auto-loads) | `.claude/rules/api.md` (loads when editing `*/api/*.py`) |
| Redis key inventory (path-scoped, auto-loads) | `.claude/rules/database.md` (loads when editing `*/repositories/*.py`) |
| Historical decisions log | `.claude/memory/decisions.md` |
| Session memory (per-task log entries) | `.claude/memory/sena-memory.md` |

## 3. DO-NOT-READ

- `/archive/`, `.venv/`, `.vscode/` — token waste, ignored per CLAUDE.md
- `ndis_markdown_docs/` (whole folder) — massive token cost. Read only a specific file when an NDIS compliance question requires it.
- `.claude/tasks/ARCHIVE.md` — read only if explicitly investigating prior work. Do NOT skim it for "what's next."

---

## Shipped infrastructure (still authoritative for the codebase)

These are the durable artefacts the voice/case-review features left behind. They remain in force regardless of which feature is active next.

**Active services:**
- `sena-ai/services/onboarding/` — port 8083, Redis-only state. **Deployed to EC2** via `docker-compose.deploy.yml`. Flutter contract still pending implementation in `sena-mobile` repo per `flutterhandoffdev.md`.
- `sena-ai/services/case_review/` — port 8084, ai-db (pgvector); 4 tables with RLS on tenant_id. Phase A-C shipped; Phase D-G shelved.
- `sena-ai/services/voice/` — port 8082, Flow B dictation (LiveKit + Bedrock). Pre-existing service; no recent activity.
- `sena-ai/services/ocr/` — skeleton only, not wired.

**How to run locally:**
```bash
# Onboarding (Redis-only)
cd sena-ai/services/onboarding && pip install -e . && uvicorn src.onboarding.main:create_app --factory --reload --port 8083

# Case Review (requires ai-db running)
cd sena-ai/services/case_review && pip install -e . && uvicorn src.case_review.main:create_app --factory --reload --port 8084

# Voice (Flow B)
cd sena-ai/services/voice && pip install -e . && uvicorn src.voice.main:create_app --factory --reload --port 8082
```

**Authoritative contracts:**
- WS events (onboarding) — `.claude/rules/api.md`
- Redis key inventory — `.claude/rules/database.md`
- Voice-onboarding validation contract — `SENA_AI/flutterhandoffdev.md` (frontend pending)

---

## Hook-enforced maintenance (how these docs stay live)

Three hooks in `.claude/settings.json` keep this system deterministic:

| Hook | Script | What it does |
|------|--------|--------------|
| `SessionStart` | `.claude/hooks/session-start.sh` | Injects this read-order as additionalContext on every new session |
| `Stop` | `.claude/hooks/stop.sh` | Rebuilds graphify graph + emits reminder to verify `TASKS.md` at every session boundary (including /clear, /compact, resume) |
| `PostToolUse` (Write\|Edit) | `.claude/hooks/bump-updated.sh` | Auto-bumps `updated: YYYY-MM-DD` frontmatter on SESSION_START.md, TASKS.md, MEMORY.md, CLAUDE.md whenever Claude edits them |

**You never need to manually update `updated:` fields.** The hook does it. If a file lacks frontmatter, the hook no-ops safely.

If a hook seems broken: check `/hooks` menu, or run `bash .claude/hooks/<name>.sh` directly with a fake stdin payload to diagnose.

---

## Rules you MUST reload every session

From `.claude/rules/principal-engineer.md` (canonical — agents inherit automatically):
- **Orchestration Protocols** (new 2026-05-15): sub-agent delegation triggers, plan mode triggers (3+ files / arch / blast-radius), dynamic recalibration ("stop and replan when"), root-cause over symptom (never skip/delete tests), elegance check (4-question pause before finalizing), minimal blast radius → out-of-scope observations go to `.claude/tasks/followups.md` not the diff
- **Self-improvement**: same lesson 3× → promote from `lessons.md` to `CLAUDE.md` permanent rule; repeating a `lessons.md` entry = instant-fail

From `CLAUDE.md`:
- **code-review-graph (MCP):** before editing any file imported by 3+ modules, call `get_dependents` / `get_callers` / `get_affected_tests`. If affected tests > 5 or callers span multiple services → flag to user before proceeding. Graph DB: `.code-review-graph/graph.db` (auto-watched).
- Gemini code → invoke `Skill: gemini-live-api-dev` BEFORE editing
- Use `send_realtime_input(audio=Blob(...))` — NOT `session.send(LiveClientRealtimeInput(...))`
- Current model: `gemini-3.1-flash-live-preview`
- Do NOT delete "dead code" without grepping full codebase first
- NEVER read `/archive`, `.venv`, `.vscode`

From memory (`feedback_gemini_live_patterns.md`):
- `session.receive()` returns per-turn — wrap in `while True` with `continue`
- Multi-turn REQUIRES `realtime_input_config` with explicit VAD
- Use `await b2g`, not `asyncio.wait(FIRST_COMPLETED)`
- Single AudioContext on browser for mic+playback
- Manual 24kHz→native upsample before `createBuffer`
- **NEVER gate mic audio on `_agent_speaking` flag** — causes VAD to die after 2-4 turns
- Use `START_SENSITIVITY_LOW` — HIGH fires on ambient noise

---

## Starting a new feature

When the user introduces a new feature, follow this sequence:

1. **Route through `@agent-sena-planner`** for any non-trivial multi-file work. The planner produces the architectural plan + subtask DAG + NDIS-compliance + tenant-boundary analysis. (See `.claude/rules/sena-rules.md` for the full pipeline.)
2. **Add the new task to `TASKS.md` Active section** before writing any code.
3. **Do NOT reuse archived plans** (`.claude/plans/` is currently empty by design). Drop a new plan there if the new feature warrants one.
4. **Update `CLAUDE.md` "Adding New Project Components" protocol** if the feature adds a new service, directory, or external resource — that protocol mandates a sync sweep across CLAUDE.md / SESSION_START.md / TASKS.md / MEMORY.md / a new `project_<name>.md` memory file.
