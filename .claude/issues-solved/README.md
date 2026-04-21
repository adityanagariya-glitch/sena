---
title: Issues-Solved Knowledge Base
updated: 2026-04-21
purpose: Stop re-solving the same problem. Grep symptoms, get fix. Token-cheap.
---

# Issues-Solved — how it works

Append-only log of concrete bugs and their fixes. Not domain knowledge (that's `wiki/`). Not preferences (that's `memory/`). **Just: "I saw X, the fix was Y, here's why."**

## When Claude uses this

**BEFORE debugging any issue:**
1. Grep `INDEX.md` for symptom keywords
2. If match found → read the linked detail file → apply fix
3. If no match → solve, then ADD a new entry

**BEFORE asking the user the same thing twice:**
1. Check if similar problem was solved before
2. If yes, reference the fix and confirm context matches

## When Claude adds a new entry

Trigger: issue was non-trivial to solve (>2 debugging iterations OR >5 min OR required external research).

1. Copy `TEMPLATE.md` → new file named `NNNN-kebab-symptom.md` (next sequential number)
2. Fill frontmatter: symptom, root_cause, fix, files, tags, date
3. Add row to `INDEX.md` table
4. Keep it short — one screen max

## What goes in an entry

| Field | What |
|-------|------|
| Symptom | What the user saw. Use their words if possible. |
| Root cause | Why it happened. One sentence. |
| Fix | What change solved it. Commands/diff if useful. |
| Files | Paths touched (for future grep). |
| Tags | Searchable: `gemini-live`, `vad`, `audio`, `ws`, etc. |
| Verified | Date + how confirmed (test, manual, user report). |

## What does NOT go here

- Feature work (that's tasks)
- Architecture decisions (that's wiki)
- User preferences (that's memory)
- Things resolved in <2 iterations (no payoff for indexing)

## Format rules

- File name: `NNNN-kebab-symptom.md` — number + dash + 3-6 word symptom
- INDEX row: `\| NNNN \| tag \| symptom \| one-line fix \| file-link \|`
- Keep details terse. If explanation >150 words, link to wiki page instead.
