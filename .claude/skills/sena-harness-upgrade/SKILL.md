---
name: sena-harness-upgrade
description: Runs the SENA .claude/ harness upgrade and hygiene routine end-to-end — archive completed-feature task history into ARCHIVE.md, reset TASKS.md Active section, sweep stale references across CLAUDE.md / SESSION_START.md / CLAUDE.local.md / output-styles / rules / skills, audit Principal Engineer Mode coverage across all 14 sena-* agents, verify Orchestration Protocols wiring (principal-engineer.md §Orchestration Protocols section, CLAUDE.md <orchestration> block completeness, SESSION_START.md reload section), verify Agent Routing Mandate is current, ensure agent-namespace consistency (every agent file uses sena-* prefix in name frontmatter), update lessons.md + decisions.md + sena-memory.md milestone entries. Use when a SENA feature has shipped, when principal-engineer rules are upgraded, when starting a new feature needing a clean slate, or as a periodic .claude/ audit. Triggers on phrases "feature shipped", "archive this feature", "clean up .claude", "reset task queue", "audit agents", "harness upgrade", "orchestration check", "principal engineer update", "consistency check", "post-ship cleanup", "do the hygiene routine", "things went sideways — reset", "next feature — clean slate".
---

# SENA .claude/ Harness Upgrade Cycle

End-to-end maintenance + upgrade routine for `.claude/` after a feature ships, after principal-engineer rules are upgraded, before starting a new feature, or as a periodic audit. Codifies the work from the 2026-05-14 cleanup + agent-system overhaul and the 2026-05-15 orchestration protocols upgrade.

## Skip conditions (check first)

Do NOT run if any of these are true — report "declined to run" and exit:

- Latest `.claude/memory/decisions.md` entry referencing `sena-harness-upgrade` is within the last 14 days (avoid churn)
- `TASKS.md` Active section has 1+ entry with `status: in_progress` AND `git status` shows uncommitted work touching that feature (mid-feature build)
- `git status` is clean AND `TASKS.md` Active is empty (state is already clean — nothing to do)

## Quick start

When invoked, **ask TWO questions first** (use `AskUserQuestion`):

1. **Mode?** — `feature-ship` (archive + reset + audit) or `audit-only` (sweep + verify, no archive).
2. **If feature-ship: which feature is being archived?** — name + which task IDs in `TASKS.md` move to `ARCHIVE.md`.

Then run the phases below in order. Use plan mode for any phase that touches >3 files.

## Workflow

### Phase 0 — Inventory + ask-before-delete
- [ ] `git status --short` + `Get-ChildItem` to surface candidate stale files (deleted handoff docs, completed plan files, dev HTML harnesses, log dumps, accidentally-created `nul` files).
- [ ] **`.claude/` root non-standard files** — list every file/folder at `.claude/` root that is NOT in the expected set: `agents/`, `commands/`, `hooks/`, `hooks-state/`, `issues-solved/`, `memory/`, `output-styles/`, `plans/`, `plugins/`, `rules/`, `skills/`, `statusline`, `tasks/`, `SESSION_START.md`, `settings.json`, `settings.local.json`, `*.flag`. Anything else (e.g. stray `.md` files, dead `audits/`-style folders) → bundle into the AskUserQuestion below. Known dead patterns to auto-flag: `client_onboarding_validations.md`, `gsd-instructions.md`, `audits/`, single-file dated audit folders.
- [ ] **Code files** (`.py`, `.html`, `.dart`, `.ts`, …) — NEVER include in delete questions. Append to `CODE_FILES_TO_REVIEW.md` at repo root (template in `REFERENCE.md` §10) and wait for user sign-off.
- [ ] **Docs / plan / log files** — bundle into ONE `AskUserQuestion` call (max 4 questions, options: "delete now / keep / tell me where used"). Never delete an ambiguous file without explicit user confirmation.
- [ ] Honour user "keep" decisions across cycles — record in `decisions.md` so the next cycle doesn't re-ask.

### Phase 1 — Feature archive (skip in audit-only mode)
- [ ] Read `.claude/tasks/TASKS.md`. Identify entries matching the named feature.
- [ ] Append those entries VERBATIM to `.claude/tasks/ARCHIVE.md` under a new `## Feature <X> — <NAME> (CLOSED YYYY-MM-DD)` heading.
- [ ] Rewrite `TASKS.md` with empty `Active` section + backlog of deferred/blocked items only.
- [ ] Update header note: `> Last session end-state (YYYY-MM-DD): <one-line summary>`.

### Phase 2 — Stale-reference sweep
- [ ] `Grep` for any reference to deleted files (handoff docs, old plan files, removed services). Use the canonical pattern set in `REFERENCE.md` §2.
- [ ] `Grep` for `.agents/` references in live files — `.agents/` was deleted 2026-05-11. Live files = CLAUDE.md, SESSION_START.md, CLAUDE.local.md, rules/*, commands/*, skills/*/SKILL.md, skills/*/REFERENCE.md. Memory/ is historical and LEFT alone.
- [ ] `Grep` for old (pre-sena-prefix) agent names: `@agent-code-reviewer`, `@agent-doc-writer`, `@agent-log-analyzer`, `@agent-researcher`, `@agent-disciplined-engineering-collaborator`. Plus any `@agent-` that isn't `@agent-sena-*` and isn't a non-SENA gstack/external agent.
- [ ] `Grep` for known-deleted file refs: `client_onboarding_validations`, `gsd-instructions`, `xml-restructure-`, `AGENTS.md` (root), `FLUTTER_DEV_HANDOFF`, `FLUTTER_CROSS_SCREEN`, `test_harness.html`, `AI_logs.txt`, `no-graceful-muffin`, `v3-v4-enum-routines`.
- [ ] `Grep` for deprecated Gemini patterns: `session.send(input=`, `LiveClientRealtimeInput`, `send_client_content`, `gemini-2.5-flash-native-audio`, `gemini-live-2.5-flash`, `gemini-2.0-flash-live-001`. Surface to user — NEVER auto-rewrite Gemini code.
- [ ] Update every match in: `CLAUDE.md`, `.claude/SESSION_START.md`, `CLAUDE.local.md`, `.claude/output-styles/*.md`, `.claude/rules/*.md`, `.claude/skills/*/SKILL.md`, `.claude/skills/*/REFERENCE.md`, `.claude/commands/*.md`.
- [ ] **`SESSION_START.md` cleanup:** remove every `## ✅ DONE: <feature> (YYYY-MM-DD)` block for features now in `ARCHIVE.md`. Update the header note: `**State as of YYYY-MM-DD:** <feature> closed; next feature not started.` Keep read-order tables, services list, run commands, Gemini Live rules.
- [ ] Fix duplicate sections or stale rows in `.claude/issues-solved/INDEX.md`.
- [ ] Historical log entries in `memory/sena-memory.md` and `memory/decisions.md` are LEFT untouched (they accurately describe past state).

### Phase 3 — Agent namespace audit
- [ ] List `.claude/agents/*.md`. Every filename MUST start with `sena-` prefix.
- [ ] For each agent file, verify `name:` frontmatter matches the filename's stem (e.g. file `sena-implementer.md` → `name: sena-implementer`).
- [ ] If any agent lacks the prefix or has mismatch, run the rename sub-routine in `REFERENCE.md` §3.

### Phase 4 — Principal Engineer Mode coverage
- [ ] For each agent, verify a `<principal_engineer_mode>` block exists right after `</role>` (or `</identity>` for sena-engineering-collaborator).
- [ ] Verify the `**For <agent-name>:**` line inside that block matches the current agent name.
- [ ] Verify the block references `.claude/rules/principal-engineer.md`.
- [ ] If a new agent was added without the block, inject one using the template in `REFERENCE.md` §4.
- [ ] Verify `.claude/rules/principal-engineer.md` has the `## 🎯 ORCHESTRATION PROTOCOLS` section (added 2026-05-15). If missing, re-run the harness upgrade from `REFERENCE.md` §4b.
- [ ] Grep `principal-engineer.md` for ALL 6 orchestration sub-headers: `Sub-Agent Delegation`, `Plan Mode Triggers`, `Dynamic Recalibration`, `Root Cause Over Symptom`, `Elegance Check`, `Minimal Blast Radius`. Any missing → re-add from `REFERENCE.md` §4b.
- [ ] Verify anti-patterns 11-13 present in `principal-engineer.md`: "Paste a sub-agent's full output", "Drift from the plan", "Repeat a mistake already captured". Missing → add.
- [ ] Verify the DoD followups.md line present: `Out-of-scope observations moved to .claude/tasks/followups.md, not left in the diff.` Missing → add.

### Phase 4.5 — Autoload rules + supporting files

**Trigger-phrase autoload rules (load on demand via keyword match):**
- [ ] Verify `.claude/rules/external-tools.md` exists (gstack + companion CLIs reference). Missing → recreate from `REFERENCE.md` §12.
- [ ] Verify `.claude/rules/add-component.md` exists ("I am adding X" protocol). Missing → recreate from `REFERENCE.md` §13.

**Path-scoped autoload rules (load when matching file is edited):**
- [ ] Verify `.claude/rules/service-onboarding.md` exists (autoload: `sena-ai/services/onboarding/**`). Missing → recreate from `REFERENCE.md` §17.
- [ ] Verify `.claude/rules/service-voice.md` exists (autoload: `sena-ai/services/voice/**`). Missing → recreate from `REFERENCE.md` §18.
- [ ] Verify `.claude/rules/service-case-review.md` exists (autoload: `sena-ai/services/case_review/**`). Missing → recreate from `REFERENCE.md` §19.
- [ ] Verify `.claude/rules/gemini.md` exists (autoload: `**/gemini*.py`, `**/demo_live*`). Missing → recreate from `REFERENCE.md` §20. NOTE: writing this file is hook-gated — invoke `Skill: gemini-live-api-dev` first.
- [ ] Verify `.claude/rules/build-and-run.md` exists (autoload: `pyproject.toml`, `docker-compose*.yml`, `Makefile`, `Dockerfile`). Missing → recreate from `REFERENCE.md` §21.
- [ ] Verify `.claude/rules/deployment.md` exists (autoload: `Dockerfile`, `docker-compose.deploy.yml`, `.env.deploy*`). Missing → recreate from `REFERENCE.md` §22.
- [ ] Verify `.claude/rules/demo-stack.md` exists (autoload: `demo_live*`). Missing → recreate from `REFERENCE.md` §23.

**CLAUDE.md must use pointers, not duplicate content:**
- [ ] Verify `CLAUDE.md` does NOT contain full gstack/Companion CLIs content (should be pointer to `rules/external-tools.md`).
- [ ] Verify `CLAUDE.md` does NOT contain full Adding-New-Components protocol (should be pointer to `rules/add-component.md`).
- [ ] Verify `CLAUDE.md` does NOT contain per-service deep-dives (layer tables, route lists, env var lists for onboarding/voice/case_review). It SHOULD have only: LLM split table + autoload-pointer table.
- [ ] Verify `CLAUDE.md` does NOT contain full Build & Run command listings (should be pointer to `rules/build-and-run.md` + a 1-line quickstart).
- [ ] Verify `CLAUDE.md` does NOT contain the full Gemini API rules (6 numbered rules block). Should be a 2-3 sentence summary + pointer to `rules/gemini.md`.
- [ ] Verify `CLAUDE.md` does NOT contain full Demo Stack details (should be pointer to `rules/demo-stack.md`).
- [ ] Verify `CLAUDE.md` does NOT contain full Deployment EC2 details (should be pointer to `rules/deployment.md`).

**Supporting files:**
- [ ] Verify `.claude/tasks/followups.md` exists with header-only template. Missing → create from `REFERENCE.md` §14.
- [ ] Verify `.claude/plans/README.md` exists (empty-by-design lifecycle doc). Missing → create from `REFERENCE.md` §15.

**Size check:**
- [ ] Report `CLAUDE.md` line count. Target: human-edited section ≤ 400 lines (excluding the gen-context.js auto-generated signatures section which starts at `## Auto-generated signatures`). Total ≤ 800 lines acceptable. If human-edited section >500 lines, surface specific candidate sections to user — don't auto-split.

### Phase 5 — Agent Routing Mandate coverage
- [ ] Read `CLAUDE.md`. Verify `<agent_routing priority="MANDATORY" enforcement="check-before-reply">` block exists with its trigger table.
- [ ] Cross-reference the trigger table rows against `.claude/agents/*.md`. Every agent must appear in at least one row.
- [ ] If new agents were added since the last cycle, add new rows. Template in `REFERENCE.md` §5.

### Phase 5.5 — Slash commands inventory
- [ ] List `.claude/commands/*.md`. Two required sets:
  - **Workflow commands (6):** `sena-harness-upgrade.md`, `sena-plan.md`, `sena-feature-ship.md`, `sena-audit.md`, `sena-status.md`, `sena-learn.md` (session reflection — captures Claude's mistakes to lessons.md).
  - **Direct-agent shortcuts (14, one per agent):** `sena-planner.md`, `sena-task-breaker.md`, `sena-implementer.md`, `sena-business-reviewer.md`, `sena-security-reviewer.md`, `sena-bug-fixer.md`, `sena-optimization-reviewer.md`, `sena-cleaner.md`, `sena-git-committer.md`, `sena-log-analyzer.md`, `sena-researcher.md`, `sena-doc-writer.md`, `sena-code-reviewer.md`, `sena-engineering-collaborator.md`.
  - **Pre-existing (preserve, do not auto-recreate):** `solve.md`.
- [ ] Total expected: 21 files (6 workflow + 14 direct-agent + 1 generic `solve`). Missing any → recreate from `REFERENCE.md` §16.
- [ ] For each command file, verify frontmatter has `description:` field. Verify `allowed-tools:` is scoped (`Agent` for direct shortcuts; `Skill, Read, Edit, Write, ...` for workflow commands).
- [ ] Verify each direct-agent shortcut routes to its matching `subagent_type: sena-<agent>` via the Agent tool.
- [ ] Verify each command references current agent names (`@agent-sena-*`, NOT pre-prefix names).

### Phase 6 — Orchestration + lessons
- [ ] Verify `CLAUDE.md` `<orchestration>` block has ALL required sections: plan-first default, sub-agent delegation (with spawn triggers + output-shape + budget rules), plan mode triggers, dynamic recalibration, root cause over symptom, elegance check, minimal blast radius, verification gate, autonomous execution, self-improvement loop (with 3× promotion rule), task-management micro-loop. Any missing section → add from `REFERENCE.md` §6b.
- [ ] Verify `SESSION_START.md` "Rules you MUST reload every session" contains the orchestration protocols bullet (added 2026-05-15). If missing → add it.
- [ ] Verify `.claude/memory/lessons.md` exists; if missing, create from the template in `REFERENCE.md` §6.
- [ ] Skim recent transcripts for user-correction patterns not yet in `lessons.md`. Append any that are missing.

### Phase 7 — Record + commit-prep
- [ ] Append a milestone entry to `.claude/memory/sena-memory.md` describing what changed this cycle.
- [ ] Append decision entries to `.claude/memory/decisions.md` for any new rule/structure introduced.
- [ ] Update the "Current Inventory" table at the bottom of `.claude/rules/sena-rules.md` if any counts changed (agents/skills/commands/rules/memory files/tasks files). Bump the audit date line in the routing-table header to today.
- [ ] Confirm `.claude/SESSION_START.md` DO-NOT-READ list still includes `ARCHIVE.md`.
- [ ] Show user `git status` + `git diff --stat`. ASK before staging. Never auto-commit.

### Phase 8 — Self-improvement (lessons capture, ALWAYS RUNS LAST)
- [ ] Invoke `/sena-learn` (or run the Skill directly if no slash-command available). This is the reflection step — Claude reviews THIS session for its own mistakes, dedupes against `lessons.md`, and promotes 3×-recurring lessons to CLAUDE.md as permanent rules.
- [ ] Use `mcp__plugin_context-mode_context-mode__ctx_search(queries: [<correction patterns>], source: "session-events")` to scan the session efficiently — see full pattern list in `commands/sena-learn.md` Step 1.
- [ ] For each correction found, draft a structured entry (Failure pattern / User correction / Rule / Scope / Occurrences) — see template in `commands/sena-learn.md` Step 2 and `REFERENCE.md` §6.
- [ ] De-duplicate against `lessons.md` `## Log` section. Same `Rule:` (semantic match) → increment `Occurrences:`. Different `Rule:` → new entry.
- [ ] Append new entries to `lessons.md` `## Log`. Increment counts on existing matches.
- [ ] Promotion check: any lesson at `Occurrences: 3+` graduates to CLAUDE.md. Route by scope:
  - Project-wide → append to `## Hard Limits`
  - Scope-specific → append to matching `rules/<scope>.md`
  - Mark the lessons.md entry with `[PROMOTED to <target>] YYYY-MM-DD` (do NOT delete — audit trail).
- [ ] Report: N corrections found / M lessons added / P incremented / K promoted. List the K promoted explicitly.
- [ ] If 0 corrections found this session: write a single line "No user corrections detected this session — clean cycle" to the report. Do NOT touch lessons.md.

**Why this is the LAST phase:** earlier phases may themselves produce corrections (e.g. user says "no, don't trim that section"). Phase 8 captures those too, including any from the current harness run.

## What this skill will NOT do

- Commit or push. End with diff + explicit ask.
- Touch `archive/`, `.venv/`, `.vscode/`, or `ndis_markdown_docs/`.
- Touch `flutterhandoffdev.md` (Flutter team's contract — read-only).
- Add new code, features, or services.
- Rename agents back to bare names — SENA namespace is `sena-*` for all agents.
- Delete code files without listing them in `CODE_FILES_TO_REVIEW.md` first and waiting for user sign-off (see `REFERENCE.md` §10).
- Delete any file flagged "keep" in a prior cycle (check `decisions.md` for retention decisions before re-asking).

## Advanced

See [REFERENCE.md](REFERENCE.md) for: exact PowerShell + Grep commands per phase, the 14-agent Principal Engineer Mode mappings, the 13-row Agent Routing trigger table, lessons.md entry format, and milestone-entry templates.
