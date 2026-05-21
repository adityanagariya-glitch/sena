---
description: Session reflection — scan this session for Claude's mistakes (user corrections, implicit reframes, self-induced errors), extract behavioural patterns, dedupe against .claude/memory/lessons.md, append new entries, increment recurrence counts on existing matches, flag promotion candidates at 3+ occurrences. Runs standalone OR as Phase 8 of /sena-harness-upgrade.
allowed-tools: Read, Edit, Write, Grep, Glob, Bash, mcp__plugin_context-mode_context-mode__ctx_search, mcp__plugin_context-mode_context-mode__ctx_batch_execute
---

# /sena-learn — Session reflection + lessons capture

Claude's self-improvement step. Turns THIS session's mistakes into rules so the next session doesn't repeat them. Activates the lessons.md loop defined in `.claude/rules/principal-engineer.md` (Self-Improvement Enforcement) and CLAUDE.md `<orchestration>` (Self-improvement loop).

## Step 1 — Scan transcript for correction signals

Use `mcp__plugin_context-mode_context-mode__ctx_search(queries: [<patterns>], source: "session-events")` for efficient scan. Categorise each signal:

**Explicit corrections (high-confidence — always log):**
- "no" / "no that's not what I meant" / "wrong" / "stop"
- "don't X" / "stop doing X" / "you keep doing X"
- "you missed X" / "you forgot X" / "you should have X"
- "actually..." (mid-sentence reframe)
- "I said X, not Y" / "I asked for X"
- Direct contradiction of Claude's prior output

**Implicit corrections (medium-confidence — verify before logging):**
- User re-asks the same thing differently → Claude misread it first time
- User gives an example/spec AFTER Claude's attempt → Claude went without it
- User adds a constraint mid-task → Claude should have asked first
- User reverts/undoes something Claude did → over-reach
- User says "ok but also..." after Claude declared done → missed scope
- User chose option B when Claude defaulted to option A without offering choice

**Self-induced mistakes (no user correction, but still mistakes):**
- Edit rejected by read-before-edit hook → didn't Read before editing
- Tool call blocked by Gemini / Context7 gate → didn't invoke prereq Skill / MCP first
- Wrong file path / wrong section number / wrong agent name in own output
- Factual error in chat (line count off, agent count wrong, file doesn't exist)
- Grep returned 0 when content actually existed (regex / emoji / escaping error)
- Repeated a mistake already in `lessons.md` (instant-fail — see Step 5)

**Positive confirmation (capture so Claude repeats next time):**
- "yes exactly" / "perfect" / "that was right" — confirms a non-obvious choice Claude made

**Anti-signals (do NOT log):**
- Follow-up questions on a different topic
- "good" / "perfect" / "thanks" / "ship it" without contradicting prior result
- User refines a request without contradicting Claude's prior output
- User changes their mind mid-design (a decision, not a Claude mistake)
- Infrastructure noise (MCP server disconnect, hook reminder, network timeout)

## Step 2 — For each detected correction, extract

```markdown
### YYYY-MM-DD — <one-line symptom>
- **Failure pattern:** what Claude did wrong (specific, behavioural — NOT "I forgot")
- **Trigger:** the input/context that made Claude pick the wrong path
- **User correction:** quoted if ≤ 1 sentence, paraphrased if longer
- **Rule going forward:** explicit testable instruction ("Before X, do Y" or "When you see Z, route to W")
- **Scope:** all sessions | this repo | this file type | this agent | this skill
- **Occurrences:** 1
```

Phrase the lesson around the **behavioural trigger that caused the mistake**, not around the specific bug. Good: "When user pastes ambiguous diff, ask which file before reading." Bad: "Don't paste wrong import in tools.py."

## Step 3 — Dedupe + recurrence count

For each candidate lesson:
1. Grep `.claude/memory/lessons.md` for similar entries (match on failure-pattern slug + scope, semantic match — not exact string).
2. If a similar entry exists → DO NOT append a duplicate. Instead, append a single `**Recurrence:**` line to the existing entry with today's date and bump `Occurrences:`.
3. If `Rule:` differs but symptom is similar, add as a new entry — different rules deserve separate tracking.

## Step 4 — Append to lessons.md

Read `.claude/memory/lessons.md` first. Append new entries to the bottom of the `## Log` section. Never reorder existing entries. Never delete.

If `lessons.md` is missing the `## Log` section (empty seed), add it at the bottom — template in `REFERENCE.md` §6.

## Step 5 — Repeated-mistake check (instant-fail)

For each correction this session, check if the same pattern already exists in `lessons.md`. If yes:
- This is an **instant-fail** per `principal-engineer.md` anti-pattern #13 ("Repeat a mistake already captured").
- Output a `⚠️ REPEATED` block: which lesson was repeated, what should have prevented it, why the prevention didn't fire.
- Append `**Recurrence:** <date>` + `**Why prevention failed:** <reason>` lines to the existing lesson.

## Step 6 — Promotion candidates (3×+ → CLAUDE.md)

For each pattern with `Occurrences: 3+`:
- Suggest target section: `## Hard Limits` (project-wide) OR a matching path-scoped rules file (e.g., `rules/gemini.md` if Gemini-specific).
- Draft a 1-2 line rule (terse, prescriptive — fits CLAUDE.md tone).
- **Ask user to confirm before editing CLAUDE.md.** Do NOT auto-promote.
- On confirmation: add the rule, mark the lessons.md entry with `[PROMOTED to <target>] YYYY-MM-DD` (do NOT delete — audit trail).

## Step 7 — Report

```
Session reflection — YYYY-MM-DD HH:MM
─────────────────────────────────────────
Corrections detected:   N  (E explicit / I implicit / S self-induced)
New lessons appended:   M
Recurrence increments:  K
Repeated mistakes:      R  (⚠️ instant-fail — listed above)
Promotion candidates:   P  (awaiting your decision)
```

If zero corrections detected, report `Corrections detected: 0 — clean session.` and exit without modifying any file.

## Pipeline position

- **Standalone:** user types `/sena-learn` at end of session, before context compaction.
- **Automatic:** runs as Phase 8 (LAST phase) of `/sena-harness-upgrade` — every harness cycle ends with reflection.
- **Optional auto-trigger:** if 3+ user corrections accumulate in a single session, `/sena-learn` is suggested proactively.

## Anti-patterns (do NOT do)

- ❌ Invent corrections that didn't happen. Clean session = clean report.
- ❌ Phrase lessons around the specific bug instead of the behavioural pattern.
- ❌ Auto-promote to CLAUDE.md without user confirmation.
- ❌ Touch `issues-solved/INDEX.md` — that's for technical bug recipes (>2 debug iterations). lessons.md is for behavioural/process patterns triggered by user correction or self-mistake.
- ❌ Append to `decisions.md` — decisions are deliberate choices; lessons are inadvertent mistakes.
- ❌ Skip the dedupe step. A growing pile of near-duplicates is noise that buries the actual patterns.
- ❌ Run this command in the middle of a task. It runs at session end (or as harness Phase 8) when the transcript is complete.
- ❌ Refactor or "fix" code based on lessons. Lessons capture HOW Claude approached work, not WHAT the code should be.

## Distinction from `issues-solved/INDEX.md`

| File | Captures | Triggered by |
|------|----------|--------------|
| `.claude/memory/lessons.md` | HOW Claude approached work — process / collaboration / behaviour failures | User correction event OR self-induced mistake |
| `.claude/issues-solved/INDEX.md` | WHAT the technical bug was — runtime errors, debugging recipes, fix steps | >2 debug iterations OR >5 min OR external research needed |

A user saying "don't create files in random places" → `lessons.md`.
A traceback showing `KeyError: 'tenant_id'` resolved by adding to FormState model → `issues-solved/`.

User's args (optional scope hint, e.g. "agents only", "skill changes only"): $ARGUMENTS
