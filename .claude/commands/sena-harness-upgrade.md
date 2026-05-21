---
description: Run the SENA .claude/ harness upgrade and hygiene routine end-to-end. Invokes the sena-harness-upgrade skill (archive completed features, sweep stale references, audit all 14 agents, verify orchestration protocols, record milestone).
allowed-tools: Skill, Read, Edit, Write, Bash, PowerShell, Glob, Grep, mcp__plugin_context-mode_context-mode__ctx_batch_execute
---

Invoke the `sena-harness-upgrade` skill via the Skill tool.

If `$ARGUMENTS` contains "audit" or "audit-only" → pass `audit-only` mode to skip Phase 1 (archive).
If `$ARGUMENTS` contains a feature name (`voice`, `onboarding`, `case-review`) → default to feature-ship mode for that feature.
Otherwise, the skill will ask the user which mode + feature.

The skill walks 7 phases:
0. Inventory + ask-before-delete (code files → `CODE_FILES_TO_REVIEW.md`, never auto-deleted)
1. Feature archive (skipped in audit-only)
2. Stale-reference sweep
3. Agent namespace audit (every agent prefixed `sena-`)
4. Principal Engineer Mode coverage (+ Orchestration Protocols section check)
5. Agent Routing Mandate coverage (13-row trigger table vs 14 agents)
6. Orchestration + lessons (10 sections in CLAUDE.md `<orchestration>`, SESSION_START reload note, lessons.md)
7. Record + commit-prep — shows `git status` + diff, asks user before staging. NEVER auto-commits.

User's args: $ARGUMENTS
