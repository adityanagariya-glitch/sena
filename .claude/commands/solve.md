---
description: Grep issues-solved/ for a symptom and apply known fix if found
argument-hint: <symptom keywords>
---

# /solve — lookup known fix for a symptom

User symptom: **$ARGUMENTS**

## Your job

1. **Grep the index** — run:
   ```
   Grep pattern="$ARGUMENTS" path=".claude/issues-solved/INDEX.md" -i=true output_mode=content
   ```
   Also search the detail files for deeper matches:
   ```
   Grep pattern="$ARGUMENTS" path=".claude/issues-solved/" -i=true output_mode=content -n=true
   ```
   Include aliases — search frontmatter `aliases:` fields too.

2. **If you find a matching entry:**
   - Read the matched detail file in full
   - Report to user in this format:
     ```
     ★ Match: NNNN — <title>
     Root cause: <one line>
     Fix: <one line>
     Failed attempts (don't retry): <list>
     Full detail: .claude/issues-solved/NNNN-*.md
     ```
   - Ask: "Apply this fix, or does the context differ?"
   - Do NOT start debugging from scratch.

3. **If NO match:**
   - Report: "No match in issues-solved. Debugging from scratch."
   - Proceed to normal debugging.
   - After solving, REMIND yourself to add a new entry via the TEMPLATE.

4. **If multiple matches:**
   - List all matches (ID + symptom) in a short table
   - Ask user which is closest
   - Then proceed with step 2

## Rules

- Do NOT skip the grep. Token cost of grep << token cost of re-debugging.
- Do NOT paraphrase the fix. Read the actual file. Prior-solved fixes are exact for a reason.
- Do NOT apply the fix blindly if the symptom is only superficially similar — confirm root cause matches context.
- If fix looks obsolete (files moved, API changed), flag to user and consider updating the entry.
