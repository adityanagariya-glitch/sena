---
description: Direct invocation of @agent-sena-bug-fixer — surgical one-for-one patches from business/security reviewer FAIL findings. No refactors.
allowed-tools: Agent
---

Route reviewer FAIL output (hand-back contract: file/line + finding + suggested fix) to `sena-bug-fixer` (Agent tool, subagent_type: sena-bug-fixer). Applies the smallest possible patch. **Never adds features, never refactors unrelated code, never "cleans up while there."** Re-runs the same review after the patch to confirm resolution.

User's args (hand-back contract): $ARGUMENTS
