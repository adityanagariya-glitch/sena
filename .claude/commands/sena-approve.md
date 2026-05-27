---
description: Direct invocation of @agent-sena-approve — sign-off gate defaulting to DENY. Walks .claude/rules/sena-lints.md silently then issues ONE verdict (DENIED / CONDITIONAL APPROVAL / APPROVED / NEEDS DATA). Use before /sena-feature-ship, before commit, or before staging deploy. Re-runs do fresh Phase 1 — no caching.
allowed-tools: Agent
---

Route the diff to `sena-approve` (Agent tool, subagent_type: sena-approve).

The agent will:
1. Read `.claude/rules/sena-lints.md` silently.
2. Walk every severity tier against the diff: tenant isolation, Gemini API surface, async correctness, Pydantic v2, test coverage, lint+typecheck, NDIS audit-log, asymmetric trust, pre-flight gates, hard limits.
3. Output ONE verdict block — nothing else. Default DENY.
4. Verdicts route: 🔴/🟠 → DENIED → `@agent-sena-bug-fixer`. 🟡/🔵 only → CONDITIONAL APPROVAL → user ack. Clean → APPROVED → `@agent-sena-git-committer`. Missing data → NEEDS DATA.

User's args (optional file/diff scope; defaults to staged + unstaged): $ARGUMENTS
