---
description: Direct invocation of @agent-sena-implementer — writes production-ready async Python code for ONE scoped subtask. Pydantic v2, structlog, async-first, ruff-strict.
allowed-tools: Agent
---

Route ONE scoped subtask to `sena-implementer` (Agent tool, subagent_type: sena-implementer). Accepts one task at a time — never bundle multiple subtasks. Implementer writes complete code; does NOT review, optimize, or commit.

**Pipeline position:** runs after `/sena-task-breaker` produces atomic JSON tasks. Next step: route output through `@agent-sena-business-reviewer` and `@agent-sena-security-reviewer`.

User's args (one subtask): $ARGUMENTS
