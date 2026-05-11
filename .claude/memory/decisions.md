# Sena Decisions Log

Format: `[YYYY-MM-DD] — [Decision] — [Why]`

2026-05-08 — `.agents/` (numbered pipeline templates) kept separate from `.claude/agents/` (Claude Code subagents) — Different runtimes: `.claude/agents/` files are loaded by the Task tool; `.agents/01-08*.md` are XML prompt templates for an external multi-model orchestrator (Opus plan → Sonnet exec → Haiku gate, per `.agents/WORKFLOW_PLAN.md`). Mixing them would cause Claude Code to attempt-load files without frontmatter and fail.

2026-05-08 — Default retry cap kept at "max 2" in `sena-rules.md` despite `WORKFLOW_PLAN.md` proposing a tiered policy (A unlimited / B ≤2 / C zero) — The tiered policy depends on the orchestrator being wired; for current in-session subagent work, the flat default is simpler and the rules file points to the richer policy as a forward reference.

2026-05-08 — SessionStart hook NOT replaced — The existing `.claude/hooks/session-start.sh` is integrated with the broader hook system (graphify rebuild, SESSION_START.md injection, ctx7/skills flag gating) and is referenced by other hooks. Replacing it with the script's minimal cat-rules-and-memory version would break that integration.

2026-05-11 — Generic `debugger / test-writer / refactorer / security-auditor` agents NOT added — Each would overlap with a stronger SENA-specific persona (sena-bug-fixer, sena-implementer, sena-optimization-reviewer, sena-security-reviewer respectively). Claude Code picks agents by description-match score; weaker generic descriptions would lose to SENA's "MUST BE USED" routing language, so adding them produces clutter without changing behaviour. Only added agents that fill genuine gaps: researcher (web), log-analyzer (crash parse), doc-writer (FLUTTER_DEV_HANDOFF style), code-reviewer (ad-hoc external diffs only — explicitly forbidden from reviewing SENA paths).

2026-05-11 — `rules/frontend.md` NOT added — The SENA AI repo is Python backend microservices only. The Flutter frontend lives in the parent `sena-mobile/` repo (separate project, separate `.claude/`). A `rules/frontend.md` here would either be empty or describe a codebase that does not exist in this tree.

2026-05-11 — `hooks/lint-on-save.sh` NOT added — The existing `post-tool-use.sh` already invokes pipreqs on Python file edits and the chain runs `bump-updated.sh` for frontmatter timestamps. Adding a second lint hook on Write|Edit would either double-run ruff or race with `post-tool-use.sh`. If Python lint-on-save is wanted explicitly, the cleaner pattern is to extend `post-tool-use.sh` rather than add a parallel hook.

2026-05-11 — `permissions.deny` added to project `settings.json` (not `settings.local.json`) — Deny rules are team-wide safety guardrails (rm -rf, force-push, secret-file reads). Putting them in shared `settings.json` means every dev on the team gets them. The existing `settings.local.json` has the personal allow-list; that split (deny=shared, allow=personal) follows the user's guidance.
