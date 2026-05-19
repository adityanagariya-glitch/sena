---
description: Compact SENA project status — active tasks, recent commits, hook flag state, followups count, lessons count, CLAUDE.md size.
allowed-tools: Read, Bash, PowerShell, Glob, Grep
---

Print a 7-line status snapshot. No prose. No preamble.

Format:
```
SENA status — YYYY-MM-DD HH:MM
─────────────────────────────────────────
Active tasks:    <count> pending / <count> in_progress  (from .claude/tasks/TASKS.md Active section)
Recent commits:  <last commit hash> "<message>"  (head -1 of git log --oneline)
Hook flags:      <comma-list of flags set in .claude/>  (e.g. ctx7-session, ctx7-gemini, skills-gemini)
Agents:          <count>/14  (from .claude/agents/sena-*.md)
Followups open:  <count>  (from .claude/tasks/followups.md "Open" section)
Lessons logged:  <count>  (from .claude/memory/lessons.md "Log" section)
CLAUDE.md size:  <line count> lines  (wc -l SENA_AI/CLAUDE.md)
```

If any value is missing or the file doesn't exist, print `—` (em-dash) for that field. Do NOT explain why.

After the snapshot, output one of:
- `OK` — if all 14 agents present, both required hook flags set, no blocker followups.
- `Warning: <one-line summary>` — if anything looks off (missing agents, stale flags, growing followups backlog).

User's args (optional filter): $ARGUMENTS
