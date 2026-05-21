---
description: Direct invocation of @agent-sena-business-reviewer — domain/business-logic review (NDIS rules, FormState contracts, tool return shapes). FLAGS ONLY — does not fix.
allowed-tools: Agent
---

Route implemented code or diff to `sena-business-reviewer` (Agent tool, subagent_type: sena-business-reviewer). Returns PASS / FAIL with findings list. FAIL hands off to `@agent-sena-bug-fixer` for surgical patches. **Does not fix inline.**

Check focus: NDIS plan validations, FormState schema contracts, advance_step gates, validator return shapes, participant-facing copy.

User's args (code/diff): $ARGUMENTS
