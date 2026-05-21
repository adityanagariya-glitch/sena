---
description: Finalize a shipped SENA feature. Runs sena-harness-upgrade in feature-ship mode — archives task history to ARCHIVE.md, resets TASKS.md, sweeps stale refs, records milestone.
allowed-tools: Skill, Read, Edit, Write, Bash, PowerShell, Glob, Grep
---

The user is shipping a feature. Invoke the `sena-harness-upgrade` skill in **feature-ship mode**.

Required arg: feature name. Examples: `voice`, `onboarding`, `case-review`.

If `$ARGUMENTS` is empty → ask the user which feature is shipping, then invoke the skill with that feature name.

The skill will:
1. Move all task entries matching the feature to `.claude/tasks/ARCHIVE.md` under `## Feature <X> — <NAME> (CLOSED YYYY-MM-DD)`.
2. Reset `TASKS.md` Active section to empty (backlog kept).
3. Sweep stale references to deleted feature artifacts across CLAUDE.md / SESSION_START.md / rules / skills / commands.
4. Audit all 14 agents + orchestration protocols.
5. Show git diff. Ask before staging. NEVER auto-commits.

User's args: $ARGUMENTS
