---
description: Direct invocation of @agent-sena-task-breaker — converts a sena-planner plan into atomic JSON coding tasks for sena-implementer.
allowed-tools: Agent
---

Route the user-supplied plan to `sena-task-breaker` (Agent tool, subagent_type: sena-task-breaker). Returns strict JSON only (no prose): array of `{id, files, change_type, depends_on, acceptance}` objects. Each task is scoped to ≤2 files. **Use AFTER `/sena-plan` returns the architectural plan.**

User's args: $ARGUMENTS
