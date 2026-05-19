---
description: Direct invocation of @agent-sena-doc-writer — writes/updates CLAUDE.md / TASKS.md / SESSION_START.md / flutterhandoffdev.md / README / handoff docs. Reads code to ground every claim.
allowed-tools: Agent
---

Route the doc-update request to `sena-doc-writer` (Agent tool, subagent_type: sena-doc-writer). Grounds every claim in a Read'd file:line — never invents API surfaces, env var names, or module structures. Markdown only; respects existing tone per file (CLAUDE.md terse, flutterhandoffdev.md contract-precise, TASKS.md status-update-style).

User's args (what to document): $ARGUMENTS
