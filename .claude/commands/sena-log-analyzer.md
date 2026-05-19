---
description: Direct invocation of @agent-sena-log-analyzer — isolates the root frame from a Python traceback, pytest failure dump, or uvicorn/FastAPI error. Does NOT fix.
allowed-tools: Agent
---

Route the crash log / stack trace / pytest output to `sena-log-analyzer` (Agent tool, subagent_type: sena-log-analyzer). Returns: root file:line + exception + failure category + one-line reproduction. **Does not fix** — the next step is `/sena-bug-fixer` with this output as the hand-back contract.

SENA-specific signature lookup: deprecated Gemini patterns, missing `tenant_id`, `cross_section_blocked`, WS lock violations, `assert_session_owner` raises, Redis key mismatches.

User's args (paste log/trace): $ARGUMENTS
