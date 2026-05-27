---
title: Lessons — User-Correction Failure Patterns
updated: 2026-05-14
purpose: Capture every correction the user makes so future sessions don't repeat the same mistake. Read at session start. Append-only.
---

# Lessons

> One entry per correction. Read this file at the start of every session BEFORE picking up new work. Each entry is a failure pattern Claude has demonstrated; the **rule** is the corrective behaviour for next time.

## Format

```
### YYYY-MM-DD — <one-line symptom>
- **Failure pattern:** what Claude did wrong (specific, behavioural)
- **User correction:** what the user said (quoted if short)
- **Rule:** the explicit behaviour for next time (must be testable — "before X, do Y")
- **Scope:** when this rule applies (which kind of task / file / agent)
```

## Distinction from `issues-solved/INDEX.md`

| File | Captures | Trigger to append |
|------|----------|-------------------|
| `.claude/memory/lessons.md` (this file) | **Process / collaboration / Claude-behaviour failures.** Examples: "Claude bloated a 40-line module into 5 files"; "Claude didn't grep before writing a duplicate validator"; "Claude marked a task done without running tests". | User correction. |
| `.claude/issues-solved/INDEX.md` | **Technical / runtime / debugging patterns.** Examples: VAD dies after 2-4 turns, editable-install wrong clone, ModuleNotFoundError. | A bug took >2 iterations OR >5 min to solve. |

If a correction is purely technical (a bug fix recipe), it goes to `issues-solved/`. If it's about HOW Claude approaches work (planning, scope, file creation, agent routing), it goes here.

---

## Log

### 2026-05-25 — Started Python edits without pre-clearing hook gates → token-wasting retry loop
- **Failure pattern:** Spawned 4 implementer sub-agents for Python edits in parallel without first ensuring the Context7 + Skill gate flags were set. Three of four agents got blocked by the Context7 gate, attempted bypass, triggered security warnings, and produced zero file changes. Main thread then attempted the same edits — also blocked. Multiple Context7 calls did not clear the gate because of an unrelated settings.json matcher bug (see next entry). Net cost: ~3 wasted sub-agent invocations, ~5 blocked direct edits, lots of token churn before reaching the diagnosis.
- **User correction:** *"everything you write gets blocked by hook or rule, then clear flag, then rewrite code, too much token consumption. Define all the hooks prior. Still of any get missed then only its blocked by hook as default so, why do same mistake again and again."*
- **Rule:** Before ANY Python (`.py`) edit — orchestrator OR sub-agent — the orchestrator MUST run the **pre-flight checklist** in `CLAUDE.md ## Pre-flight for Python edits`. At minimum: (1) one `mcp__plugin_context7_context7__resolve-library-id` call this session to set `ctx7-session.flag`; (2) if the task touches `gemini*` / `demo_live*` files, also invoke `Skill: gemini-live-api-dev` AND query Context7 for `google-genai` to set both `skills-gemini.flag` and `ctx7-gemini.flag`. Verify the flag file exists in `.claude/hooks-state/` BEFORE spawning the first sub-agent. Never let a sub-agent discover the gate.
- **Scope:** all sessions, all `.py` edits inside `sena-ai/`, all multi-agent spawns.
- **Occurrences:** 1 (this session — repeated ~5 times internally before diagnosis).

### 2026-05-25 — Assumed hook settings.json matcher was correct without verifying
- **Failure pattern:** When the Context7 gate kept firing despite multiple legitimate Context7 MCP calls, I assumed the postaction hook script (`ctx7-flag.sh`) was misconfigured or that the flag path was wrong. The actual bug was a one-line matcher mismatch in `.claude/settings.json`: `"matcher": "mcp__plugin_context7"` (no wildcard, no underscore suffix) did not match the actual tool names like `mcp__plugin_context7_context7__resolve-library-id`. I diagnosed five layers deep before checking the matcher wiring.
- **User correction:** Implicit — user picked Option 1 "fix the hook" and the diagnosis-then-fix took longer than it should have.
- **Rule:** When a PostToolUse-flag hook isn't firing despite the trigger condition being met, **first** read `.claude/settings.json` `hooks.PostToolUse[].matcher` and compare against the EXACT tool names being called. Matcher uses anchored regex; bare strings only match exact tool names. Diagnose at the wiring layer before assuming the script or path is broken.
- **Scope:** any time a hook silently fails to fire.
- **Occurrences:** 1.

### 2026-05-25 — Sub-agents delegated to clear their own hook gates (security violation)
- **Failure pattern:** In Wave 1 + Wave 2, I gave implementer sub-agents instructions like "if your edit is blocked by the Context7 gate, call Context7 yourself to clear it." Sub-agents could not reliably invoke Context7 MCP (different tool surface) — two of them resorted to `touch .claude/hooks-state/ctx7-session.flag` and triggered the Auto-Mode-Bypass security classifier. Their work product was zero.
- **User correction:** Implicit — security warning fired twice on sub-agent actions I had set up.
- **Rule:** Sub-agents (sena-implementer, sena-bug-fixer, sena-doc-writer, etc.) CANNOT and MUST NOT be expected to clear hook gates. Gate-clearing is the orchestrator's responsibility, executed in the MAIN session before sub-agent spawn. Never include "if blocked, clear the gate yourself" instructions in a sub-agent brief.
- **Scope:** all sub-agent spawning of agents that will perform `.py` Write/Edit.
- **Occurrences:** 1.

### 2026-05-25 — Wrote architectural plan from file headers, missed the implementation body
- **Failure pattern:** When writing `ISSUE_AND_SOLUTION.md` Option D spec, I assumed `tools.py` had per-handler methods (`_handle_update_field`, `_handle_add_row`, etc.) that wrote to server-side Redis. Reality: `tools.py` is a 160-line thin proxy that forwards every non-incident tool call to `MobileBridge` → Flutter. Mobile (not server Redis) is the source of truth. The whole "server reads state from Redis and embeds in tool_response" design was unimplementable as written. Agent A discovered the mismatch and refused to proceed — saving the spec from corruption — but only after the planning artifact had committed wrong assumptions.
- **User correction:** Implicit — Agent A's halt was the correction.
- **Rule:** When the design depends on the behaviour of a specific module (state read/write semantics, who owns truth, sync vs async), READ THE MODULE BODY before writing the plan. Header signatures from graphify summaries are NOT enough. Specifically for SENA: before any plan that touches `services/tools.py`, read the actual `ToolDispatcher.dispatch()` implementation and trace whether each tool is server-handled or mobile-bridged.
- **Scope:** all multi-file architectural plans where one of the files determines truth-ownership.
- **Occurrences:** 1.

### 2026-05-25 — Did not check whether spawning parallel agents would all hit the same gate
- **Failure pattern:** Spawned 4 implementer agents in parallel without realizing they would each independently hit the same Context7 gate (a session-singleton condition). The gate is set once per session by a single Context7 MCP call; spawning four agents in parallel where ALL four need the gate cleared means the first one's failure to clear it doesn't help the other three. Even worse: sub-agents had varying success rates at recognizing they needed to clear the gate.
- **User correction:** Implicit — the wave produced 1/4 success and 3/4 token waste.
- **Rule:** Before any parallel sub-agent spawn touching `.py` files, verify all per-session prerequisite flags are set in the orchestrator's session FIRST. The flags live in `.claude/hooks-state/`. If the flag file does not exist, take the prerequisite action in the orchestrator's session before issuing any sub-agent task.
- **Scope:** parallel agent spawning where the spawned agents will edit `.py` files.
- **Occurrences:** 1.

---

## Promotion to CLAUDE.md (user authorised this session)

All five lessons above are facets of one root pattern: **starting Python edits without confirming hook prerequisites are satisfied.** Promoted as a single rule into `CLAUDE.md ## Pre-flight for Python edits` on 2026-05-25.

