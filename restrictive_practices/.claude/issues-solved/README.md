# Issues-Solved Knowledge Base

## Purpose
Zero re-solved bugs. If it took >2 iterations or >5 minutes to fix, it lives here forever.

## Protocol

### Before debugging ANY issue
```bash
grep -i "<symptom keyword>" .claude/issues-solved/INDEX.md
```
If match → read the linked file → apply the fix directly. Do NOT re-derive.

### After solving a new issue
1. Copy `TEMPLATE.md` to `NNNN-kebab-symptom.md` (next number from INDEX)
2. Fill in all sections
3. Append one row to `INDEX.md` (newest at top)

### Naming convention
- File: `NNNN-kebab-symptom.md` (e.g. `0004-gemini-response-parsed-none.md`)
- Number: 4-digit zero-padded, sequential
- Slug: 2-5 words describing the symptom, not the fix

## When to add an entry
- Issue took >2 debugging iterations, OR
- Issue took >5 minutes to resolve, OR
- Required external research / trial-and-error

One file per issue. Never merge two unrelated issues into one file.
