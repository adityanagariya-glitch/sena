---
description: Direct invocation of @agent-sena-researcher — current third-party library/API/framework docs research when Context7 misses. Does NOT modify code.
allowed-tools: Agent
---

Route the docs question to `sena-researcher` (Agent tool, subagent_type: sena-researcher). Returns: synthesis with linked sources, ranked stdlib > installed-lib > new-install > custom-code. Use this BEFORE `@agent-sena-implementer` writes code against a library not yet verified this session.

Preferred: invoke `mcp__plugin_context7_context7__resolve-library-id` + `query-docs` FIRST. Route to researcher only when Context7 misses or topic is non-library (NDIS regulatory updates, RFC drafts, vendor changelogs).

User's args (research question): $ARGUMENTS
