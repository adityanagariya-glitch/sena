---
description: Direct invocation of @agent-sena-security-reviewer — security audit (tenant isolation, secrets, OWASP, Gemini-bridge). FLAGS ONLY — does not fix.
allowed-tools: Agent
---

Route implemented code or diff to `sena-security-reviewer` (Agent tool, subagent_type: sena-security-reviewer). Returns PASS / FAIL with severity-tagged findings. **Critical findings HALT workflow** — escalate to human, do not route to bug-fixer. Lower severity → hands off to `@agent-sena-bug-fixer`.

Auto-block signatures: custom crypto, custom JWT, custom Redis key builder, missing `assert_session_owner`, missing `tenant_id` on DB rows, `Any` types in security boundaries, `os.environ` direct reads.

User's args (code/diff): $ARGUMENTS
