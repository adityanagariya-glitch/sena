---
description: Read-only audit of .claude/ — verifies agent namespace, Principal Engineer Mode coverage, Orchestration Protocols, routing table, lessons. No archive, no reset.
allowed-tools: Skill, Read, Glob, Grep, mcp__plugin_context-mode_context-mode__ctx_batch_execute
---

Invoke `sena-harness-upgrade` in **audit-only mode**. Skip Phase 1 (archive). Walk Phases 0, 2, 3, 4, 5, 6, 7 to verify the `.claude/` system is in good shape.

**Pass criteria (all must be true):**
- All 14 agents prefixed `sena-`; `name:` frontmatter matches filename
- Every agent has `<principal_engineer_mode>` block referencing `.claude/rules/principal-engineer.md`
- `principal-engineer.md` contains the `## 🎯 ORCHESTRATION PROTOCOLS` section
- `CLAUDE.md` `<orchestration>` block has all 10 required sections (plan-first, subagent delegation, plan mode triggers, dynamic recalibration, root cause, elegance check, minimal blast radius, verification gate, autonomous execution, self-improvement)
- `SESSION_START.md` "Rules you MUST reload" mentions orchestration protocols
- `<agent_routing>` trigger table in CLAUDE.md covers all 14 agents
- `tasks/followups.md` exists
- `memory/lessons.md` exists

**Output format:**
- ✅ for each passed check (one line each)
- ⚠️  for each fixable issue → fix inline if low-risk (cleaner/optimization-style only)
- ❌ for each blocker → surface to user, no auto-fix

Final line: `N/N checks passed | M fixed inline | K blockers surfaced.`

User's args: $ARGUMENTS
