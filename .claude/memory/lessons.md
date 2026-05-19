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

*(no entries yet — populate on first user correction)*
