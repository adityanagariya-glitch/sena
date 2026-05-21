---
description: Direct invocation of @agent-sena-code-reviewer — ad-hoc external diff or non-SENA-path PR review. SHIP / FIX / BLOCK verdict.
allowed-tools: Agent
---

Route the diff/PR to `sena-code-reviewer` (Agent tool, subagent_type: sena-code-reviewer). Returns single verdict: SHIP (merge as-is) / FIX (specific punch list) / BLOCK (cannot merge — reason).

**Do NOT use on SENA-touching diffs.** SENA paths route through the canonical pipeline: `@agent-sena-business-reviewer` + `@agent-sena-security-reviewer` → `@agent-sena-bug-fixer` (if FAIL) → `@agent-sena-cleaner` → `@agent-sena-git-committer`.

User's args (diff or PR ref): $ARGUMENTS
