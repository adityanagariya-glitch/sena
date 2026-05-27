---
description: Direct invocation of @agent-sena-tradeoffs — honest comparison of 2-3 options (libraries, patterns, models, architectures). Steelman each option + honest comparison table (numbers not adjectives) + recommendation for the stated context. Asks for use-case anchor if missing; never "it depends".
allowed-tools: Agent
---

Route the user's comparison to `sena-tradeoffs` (Agent tool, subagent_type: sena-tradeoffs).

The agent will:
1. If context missing → ask 5 questions (workload, durability, consistency, service, rollback story).
2. Steelman each option (1 paragraph as its advocate).
3. Comparison table — numbers, not adjectives. Missing numbers → `Unverified:`.
4. Recommendation for THIS context + explicit caveats (when it flips, risk accepted, cheaper-to-revisit).
5. **Default tie-breaker:** already-installed dep wins (Rule 1, no reinvention).

Next-step pointers: `@agent-sena-planner` (flesh the chosen option), `@agent-sena-brainstorm` (explore a 4th).

User's args (the comparison, e.g. "Redis vs Postgres for cross-screen bucket"): $ARGUMENTS
