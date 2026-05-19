# Sena Rules

## Constraints

1. All agents operate strictly under their Sena persona as written in their `.md` file. Never override the persona, identity, or operating principles defined in the agent file.
2. Executor agents receive only one scoped subtask at a time. Do not stuff multiple subtasks into a single executor invocation.
3. Max 2 retry loops per subtask before escalating to human review. After two failed attempts on the same subtask, stop and surface the blocker.
4. Reviewer agents check final output and flagged sections only — not line-by-line — to control cost.

## Agent Routing Table

Built from `.claude/agents/*.md` — last audited 2026-05-15. One row per Claude Code subagent (14 total, all `sena-*` prefixed).

| Task type | Agent |
|-----------|-------|
| Non-trivial multi-file engineering work; multi-subsystem investigations; long-running debugging sessions; tasks requiring institutional-memory updates; contract-first audits at system boundaries | `@agent-sena-engineering-collaborator` |
| Architectural plan + subtask DAG for any non-trivial feature/refactor (NDIS compliance + tenant boundary analysis included) | `@agent-sena-planner` |
| Convert a plan into atomic JSON coding tasks for executors | `@agent-sena-task-breaker` |
| Greenfield Python coding (new feature, new file, full implementation from spec) | `@agent-sena-implementer` |
| Domain/business-logic review of implemented code (NDIS rules, FormState contracts, tool return shapes) — FLAGS ONLY | `@agent-sena-business-reviewer` |
| Security audit (tenant isolation, secrets, OWASP, Gemini-bridge correctness) — FLAGS ONLY | `@agent-sena-security-reviewer` |
| Surgical patch of a finding from business or security reviewer (one-for-one fixes, no refactors) | `@agent-sena-bug-fixer` |
| Async / Redis / memory optimisation refactor — FIXES inline | `@agent-sena-optimization-reviewer` |
| Final lint + artifact gate before commit (ruff/mypy, dead code, debug prints) — FIXES inline | `@agent-sena-cleaner` |
| Generate Conventional Commit + git add command (NEVER push) | `@agent-sena-git-committer` |
| Crash log / stack trace / pytest failure dump — isolate root frame before bug-fixer | `@agent-sena-log-analyzer` |
| Current third-party library/API/framework documentation research (when Context7 misses) | `@agent-sena-researcher` |
| Writing or updating CLAUDE.md / TASKS.md / SESSION_START.md / FLUTTER docs / README / handoff docs | `@agent-sena-doc-writer` |
| Ad-hoc external diff or non-SENA-path PR review (SHIP/FIX/BLOCK) | `@agent-sena-code-reviewer` |

### Pipeline order (review → fix → re-review)

```
sena-planner ──> sena-task-breaker ──> sena-implementer
                                            │
                                            ▼
                                   sena-business-reviewer ──┐
                                            │              │ FAIL
                                            │ PASS         ▼
                                            ▼          sena-bug-fixer
                                   sena-security-reviewer ──┤
                                            │              │ FAIL
                                            │ PASS         │
                                            ▼              ▼
                                  sena-optimization-reviewer (fixes inline)
                                            │
                                            ▼
                                       sena-cleaner (fixes inline)
                                            │
                                            ▼
                                    sena-git-committer
```

Reviewers (`business`, `security`) only **flag** — they hand back to `sena-bug-fixer`, which applies surgical patches and re-verifies. `optimization-reviewer` and `cleaner` fix inline because their changes are scoped and low-risk.

## Quality Gate

A task is only complete when:

1. It runs without errors (lint clean; tests green via `pytest services/<svc>/tests/ -x`).
2. It matches the original spec (acceptance criteria from the planning artifact, not a paraphrase).
3. No conflicts with other agents' outputs (no shared-file regressions; FUNCTION_DECLS coverage intact; system prompt rules still numbered correctly).
4. Confirmed aligned with Sena's overarching goals (multi-tenant isolation preserved; NDIS compliance preserved; human-in-the-loop preserved; current Gemini Live API only — no deprecated patterns).

## Notes

- The retry-cap rule above ("max 2 loops") is the simple default. If an external multi-model orchestrator is wired in the future, a tiered policy applies: Tier-A unlimited cheap loops, Tier-B ≤2 loops, Tier-C zero (straight to human). For in-session subagent work the simple "max 2" default applies.
- Hook gates (`pre-tool-use.sh`, Rule 3 — Gemini Live Config Gate) are enforced by the runtime regardless of these rules. Agents must respect those gates.
- The `.agents/` folder no longer exists (deleted 2026-05-11). All agent definitions live in `.claude/agents/`. Historical references in `memory/` describe past state and are intentionally left untouched.

## Current Inventory (as of 2026-05-15)

| Area | Count | Path |
|------|-------|------|
| Agents | 14 (all `sena-*` prefixed) | `.claude/agents/` |
| Skills (project-local) | 1 — `sena-harness-upgrade` | `.claude/skills/sena-harness-upgrade/` |
| Slash commands (project-local) | 20 — 5 workflow (`sena-harness-upgrade`, `sena-plan`, `sena-feature-ship`, `sena-audit`, `sena-status`) + 14 direct-agent shortcuts (one per agent: `sena-planner`, `sena-task-breaker`, `sena-implementer`, `sena-business-reviewer`, `sena-security-reviewer`, `sena-bug-fixer`, `sena-optimization-reviewer`, `sena-cleaner`, `sena-git-committer`, `sena-log-analyzer`, `sena-researcher`, `sena-doc-writer`, `sena-code-reviewer`, `sena-engineering-collaborator`) + 1 generic (`solve`) | `.claude/commands/` |
| Rules — path-scoped autoload | 9 — `api.md` (FastAPI routes), `database.md` (Postgres/Redis), `service-onboarding.md`, `service-voice.md`, `service-case-review.md`, `gemini.md` (hook-gated), `build-and-run.md`, `deployment.md`, `demo-stack.md` | `.claude/rules/` |
| Rules — trigger-phrase autoload | 2 — `add-component.md` ("I am adding X"), `external-tools.md` (gstack / browser / specify / hivemind) | `.claude/rules/` |
| Rules — canonical always-referenced | 2 — `principal-engineer.md` (the 5 non-negotiables + 10 orchestration sections), `sena-rules.md` (this file) | `.claude/rules/` |
| Memory — append-only logs | 3 — `sena-memory.md` (activity), `decisions.md` (rationale), `lessons.md` (user-correction patterns) | `.claude/memory/` |
| Tasks files | 3 — `TASKS.md` (active queue), `ARCHIVE.md` (closed features), `followups.md` (out-of-scope observations) | `.claude/tasks/` |
| Plans | empty by design between features — see `.claude/plans/README.md` | `.claude/plans/` |

**Hook state flags** live in `.claude/` root (`ctx7-session.flag`, `ctx7-gemini.flag`, `skills-gemini.flag`). Cleared on every session start; re-earn by invoking the relevant Skill or Context7 MCP.

**The `audits/`, `client_onboarding_validations.md`, and `gsd-instructions.md` files were removed 2026-05-15.** If you see references in code/docs, they're stale — sweep them.
