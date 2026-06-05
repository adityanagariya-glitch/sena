---
description: Route the user's requirement to @agent-sena-planner for architectural plan + subtask DAG + NDIS/tenant-isolation analysis. Use for any non-trivial multi-file work BEFORE coding.
allowed-tools: Agent
---

Route the user's requirement to the `sena-planner` agent via the Agent tool (subagent_type: `sena-planner`).

The planner does NOT write code. It returns:
1. **Existing code to extend / Libraries to use** — Grep results showing what's already in the repo or in installed deps (Rule 1: no reinvention).
2. **New files to create** — each with one-line justification.
3. **Architectural plan** — file-by-file delta with `create`/`edit`/`delete` tag.
4. **Subtask DAG** — dependencies between subtasks.
5. **NDIS compliance + tenant-isolation implications** — flag any cross-tenant data risk or NDIS APP 8/11 concerns.
6. **Rollback plan** — for risky changes.

After the agent returns:
- Surface the plan in compact form.
- Ask the user whether to proceed to `@agent-sena-task-breaker` (which converts the plan to atomic JSON tasks for the implementer).

User's requirement: $ARGUMENTS
