---
name: review-pr
description: "Review a pending diff or a GitHub PR for a SHIP / FIX / BLOCK verdict. Routes SENA-touching diffs through the SENA-specific reviewers (sena-business-reviewer, sena-security-reviewer); routes non-SENA diffs through the generic code-reviewer. Use when the user says 'review the PR' or 'what would a reviewer say'."
argument-hint: "[pr-number | 'staged']"
allowed-tools: Bash(git diff:*), Bash(gh pr view:*), Bash(gh pr diff:*), Read, Grep, Glob
---

# review-pr

## 1. Fetch the diff
- If `$1` is a PR number: `gh pr view $1 --json files --jq '.files[].path'` + `gh pr diff $1`.
- Else (`staged` or empty): `git diff --staged`.

## 2. Read full context
- Read every changed file in full (not just hunks).
- For every modified function or class, run `Grep` for its call sites to verify nothing downstream broke.

## 3. Route to the right reviewer(s) — SENA path → reviewer map

Multiple rows can apply to one diff. Run all applicable reviewers in parallel.

| Path touched | Reviewer | Reason |
|--------------|----------|--------|
| `services/onboarding/src/onboarding/services/tools.py` | `@agent-sena-business-reviewer` + `@agent-sena-security-reviewer` | FUNCTION_DECLS contract + tool argument validation + tenant scoping in handlers |
| `services/onboarding/src/onboarding/models/form_state.py` or `models/schema_spec.py` or `models/session_bootstrap.py` | `@agent-sena-business-reviewer` | FormState contract, recompute_completion, validators wiring |
| `services/onboarding/src/onboarding/prompts/onboarding_system.md` | `@agent-sena-business-reviewer` | Rule numbering, `__PLACEHOLDER__` integrity, NDIS rule expression |
| `services/onboarding/src/onboarding/services/validators/` | `@agent-sena-business-reviewer` | NDIS rule correctness (NDIS#, plan dates, BSB, ABN, contact uniqueness) |
| `services/onboarding/src/onboarding/services/gemini_live.py` or any `gemini*` file | `@agent-sena-security-reviewer` | **Critical** — deprecated API patterns, _agent_speaking gate, screen_state injection, audio size limits |
| `services/onboarding/src/onboarding/api/ws_routes.py` | `@agent-sena-security-reviewer` | WS auth before upgrade, frame size limits, tenant claim validation |
| `repositories/state_repo.py` or `user_context_repo.py` or any new `repositories/*.py` | `@agent-sena-security-reviewer` | `assert_session_owner`, tenant_id in Redis keys, TTL discipline |
| `services/onboarding/src/onboarding/services/webhook.py` or any webhook-emitting code | `@agent-sena-security-reviewer` | HMAC signature, secret-not-logged |
| `services/case_review/migrations/**` or `sena-ai/migrations/**` | `@agent-sena-security-reviewer` + `@agent-sena-business-reviewer` | RLS policy on every tenant table, tenant_id column, FK + tenant composite |
| `services/voice/src/voice/services/*.py` (Bedrock, LiveKit, SNS) | `@agent-sena-security-reviewer` | AWS credential handling, signed URLs, IAM scope |
| `services/case_review/src/case_review/**` | `@agent-sena-business-reviewer` + `@agent-sena-security-reviewer` | Human-in-the-loop preserved, AI flag acknowledgement, RLS on every read |
| Anything that adds a new Gemini tool (`FUNCTION_DECLS`) | `@agent-sena-business-reviewer` + `@agent-sena-security-reviewer` | Tool argument schema, tenant scoping, return contract `{"ok": bool, ...}` |
| Anything that adds a new Redis key | `@agent-sena-security-reviewer` | tenant_id in key, TTL explicit, key-construction test exists |
| Anything that adds a new WebSocket emit type | `@agent-sena-business-reviewer` (Flutter contract) | FLUTTER_DEV_HANDOFF.md Issue # added, payload shape documented |
| Files with measurable hot-path implications (Redis loops, audio bridge, large JSON serialisation) | `@agent-sena-optimization-reviewer` (in addition to others) | Async correctness, Redis pipelining, memory bounds |
| Any other file in the SENA monorepo not matched above | `@agent-code-reviewer` | Generic SHIP/FIX/BLOCK |
| External / non-SENA code (e.g. reviewing an open-source PR pasted in) | `@agent-code-reviewer` only | SENA reviewers would over-flag |

If the diff touches any `services/onboarding/src/onboarding/prompts/onboarding_system.md` Rule number that is cross-referenced elsewhere (`FLUTTER_DEV_HANDOFF.md`, `CLAUDE.md`, other prompts) — block the review and flag the renumbering as a contract-break.

## 4. Aggregate verdicts
- If any reviewer returns BLOCK → overall verdict is BLOCK.
- If any reviewer returns FIX → overall verdict is FIX, hand findings to `@agent-sena-bug-fixer`.
- If all reviewers return PASS/SHIP → overall verdict is SHIP.

## 5. Output
A single verdict block:

```
Verdict: SHIP | FIX | BLOCK
Reviewers consulted: <list>
Hand-off: <agent or "ready to commit">
```

Followed by the punch list from each reviewer (verbatim).

## What this skill will NOT do
- Apply patches. Reviewers flag; bug-fixers fix.
- Skip the security reviewer when the diff touches tenant-scoped code.
- Aggregate a PASS verdict that ignores a BLOCK from any reviewer.
- Pass a diff that renumbers `onboarding_system.md` Rules without checking cross-references in `FLUTTER_DEV_HANDOFF.md`.
- Pass a diff that adds a new WebSocket emit type without a matching entry in `FLUTTER_DEV_HANDOFF.md`.
- Pass a diff that constructs a Redis key without `tenant_id` in it — that is automatic BLOCK by all reviewers.
