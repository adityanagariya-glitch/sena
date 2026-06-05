---
description: Direct invocation of @agent-sena-explain — verified deep explanation. Verifies BEFORE teaching (Context7 / MCP / file:line) — never teaches from stale training data. Outputs 7-section structure (30-sec → mechanism → when to use → when NOT → common mistakes → production concerns → further reading). NOT the three-block review format.
allowed-tools: Agent
---

Route the topic to `sena-explain` (Agent tool, subagent_type: sena-explain).

The agent will:
1. Verify the source (Context7 for libraries; `Skill: gemini-live-api-dev` for Gemini Live; Grep+Read for SENA-internal patterns; arxiv fetch for papers).
2. If verification fails → say `Unverified: <claim> — needs <source>`. Does NOT fall back to training memory.
3. Produce 7 sections: 30-second version, mechanism, when to use, when NOT to use, common mistakes, production concerns, further reading (with cited URLs).
4. Concrete SENA examples > generic ones. Australian-English spelling.

Next-step pointers: `@agent-sena-tradeoffs` (compare), `@agent-sena-debug` (debug), `@agent-sena-planner` (write).

User's args (concept / library / pattern): $ARGUMENTS
