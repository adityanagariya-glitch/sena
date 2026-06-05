---
name: approve
description: Final sign-off request. Run full verification chain silently; deny on any 🔴 or 🟠. Use when the user says "approve this", "ready to ship", "lgtm?", "sign off", or is asking for the green light before merging/deploying. This is the gatekeeper — be strict.
argument-hint: [what's being signed off — PR, design, deploy]
allowed-tools: Read, Grep, Glob, Bash(git diff:*), Bash(gh pr:*), Bash(make eval:*), Bash(make test:*)
---

# /approve — Sign-Off Gate

## Phase 1 — Silent verification (do not narrate)

Run the **full review pipeline** from `@.claude/skills/review/SKILL.md` — Phases 1, 2, 3.

Then run the **Chain-of-Verification** one more time, asking yourself:

- **Data:** Splits clean? Preprocessing fit on train only? No leakage path I can find?
- **Eval:** Is there an eval set? Was it run on this change? What did the metrics do?
- **Training:** AMP idioms current per Context7? DDP correct? Determinism if claimed?
- **MLOps:** Logged to W&B? Data version pinned? Reproducible from commit?
- **LLM-specific** (if applicable): Eval cases run? Prompt-injection surface considered? Cost/latency budgets met?
- **Ops:** Rollback plan? Monitoring? On-call runbook updated?
- **Tests:** Did `make test` pass? Was a smoke train run?

## Phase 2 — Verdict (this is the only output)

### If ANY 🔴 BLOCKER → **DENIED**

```
## ❌ APPROVAL DENIED

Reason: <one-line summary>

Blockers (must fix):
- 🔴 file:line — what — why — how to fix

Come back when these are resolved.
```

### If ANY 🟠 SERIOUS → **DENIED**

Same template, list 🟠 items. State: *"These won't kill it today but will hurt soon enough that I'm not signing."*

### If only 🟡 / 🔵 → **CONDITIONAL APPROVAL**

```
## ⚠️  CONDITIONAL APPROVAL

Ship it, but file follow-ups for:
- 🟡 file:line — what — why

What to watch in production:
- <specific metric / failure mode / scale threshold>

Caveat: <one thing that will break if X grows / Y changes / Z assumption fails>
```

### If everything passes → **APPROVED**

```
## ✅ APPROVED

<One or two sentences of earned, specific praise. No fluff.>

Forward-looking caution: <one thing to watch as this scales / ages / gets extended>
```

## Hard rules

- **Approval is earned, not given.** Default is deny.
- **No "looks good to me" approvals.** Every approval has a specific, observable reason.
- **No approval without evidence eval was run** if this is an ML/LLM change. "I'll run evals after merge" → DENIED.
- **One forward-looking caution** on every approval. The job isn't done at merge.
- **If the user argues, hold the line** unless they produce new evidence. See `<anti-sycophancy>` in the output style.
