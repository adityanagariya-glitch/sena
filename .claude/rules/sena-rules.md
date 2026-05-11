# Sena Rules

## Constraints

1. All agents operate strictly under their Sena persona as written in their `.md` file. Never override the persona, identity, or operating principles defined in the agent file.
2. Executor agents receive only one scoped subtask at a time. Do not stuff multiple subtasks into a single executor invocation.
3. Max 2 retry loops per subtask before escalating to human review. After two failed attempts on the same subtask, stop and surface the blocker.
4. Reviewer agents check final output and flagged sections only — not line-by-line — to control cost.

## Agent Routing Table

Built from `.claude/agents/*.md` on 2026-05-08. One row per Claude Code subagent.

| Task type | Agent |
|-----------|-------|
| Non-trivial multi-file engineering work; multi-subsystem investigations; long-running debugging sessions; tasks requiring institutional-memory updates; contract-first audits at system boundaries | `@agent-disciplined-engineering-collaborator` |
| Architectural plan + subtask DAG for any non-trivial feature/refactor (NDIS compliance + tenant boundary analysis included) | `@agent-sena-planner` |
| Convert a plan into atomic JSON coding tasks for executors | `@agent-sena-task-breaker` |
| Greenfield Python coding (new feature, new file, full implementation from spec) | `@agent-sena-implementer` |
| Domain/business-logic review of implemented code (NDIS rules, FormState contracts, tool return shapes) — FLAGS ONLY | `@agent-sena-business-reviewer` |
| Security audit (tenant isolation, secrets, OWASP, Gemini-bridge correctness) — FLAGS ONLY | `@agent-sena-security-reviewer` |
| Surgical patch of a finding from business or security reviewer (one-for-one fixes, no refactors) | `@agent-sena-bug-fixer` |
| Async / Redis / memory optimisation refactor — FIXES inline | `@agent-sena-optimization-reviewer` |
| Final lint + artifact gate before commit (ruff/mypy, dead code, debug prints) — FIXES inline | `@agent-sena-cleaner` |
| Generate Conventional Commit + git add command (NEVER push) | `@agent-sena-git-committer` |

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

- The retry-cap rule above ("max 2 loops") is the simple default. A more granular tiered retry policy is described in `.agents/WORKFLOW_PLAN.md` §8 (Tier-A unlimited cheap loops, Tier-B ≤2, Tier-C zero — straight to human). Adopt the tiered policy when the orchestrator is wired; for in-session subagent work, the simple "max 2" default applies.
- Hook gates (`pre-tool-use.sh`, Rule 3 — Gemini Live Config Gate) are enforced by the runtime regardless of these rules. Agents must respect those gates.
