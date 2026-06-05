---
description: Direct invocation of @agent-sena-brainstorm — sounding-board mode. Asks 3 clarifying questions FIRST, then proposes 2-3 architectural paths with explicit tradeoffs (cites file:line for "existing surface to extend" on every path; always includes the boring option). NEVER writes the full solution — route to @agent-sena-planner for that.
allowed-tools: Agent
---

Route the user's design question to `sena-brainstorm` (Agent tool, subagent_type: sena-brainstorm).

The agent will:
1. Ask 3 clarifying questions (scope, tenancy, NDIS surface, LLM tier, state store, latency, existing pattern, rollback) — wait for answers.
2. After answers, propose 2-3 paths with `file:line`-cited "existing surface to extend", new surface, wins/risks/NDIS-tenant implications, effort S/M/L.
3. Always include the boring option.
4. **Does not write code.** Next-step pointers: `@agent-sena-planner` (spec the path), `/sena-tradeoffs` (compare paths), `@agent-sena-implementer` (build it after planning).

User's args (the design problem): $ARGUMENTS
