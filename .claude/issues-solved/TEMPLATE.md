---
id: NNNN
symptom: "<what the user saw — one line>"
aliases:
  - "<other phrasing of same symptom>"
  - "<error message fragment>"
  - "<related keyword>"
root_cause: "<why — one sentence>"
tags: [tag1, tag2]
files: [path/to/file.py, path/to/other.py]
fix_commit: "<git sha that introduced the fix, or '' if pre-existing>"
date_solved: YYYY-MM-DD
verified: "<how confirmed: test name, manual, user report>"
---

# NNNN — <short title>

## Symptom

<Exact error, observed behavior, or user quote. Include log excerpts if relevant. Future-Claude greps this.>

## Root cause

<Why it happened. One paragraph max. If complex, link to wiki.>

## Fix

<Concrete change. Diff or command preferred over prose.>

```diff
- old line
+ new line
```

See commit `<sha>` for the full diff: `git show <sha>`.

## Failed attempts (do NOT retry)

<Equally valuable as the fix. Stops future-Claude from burning tokens on paths you already disproved.>

- **<attempt 1>** — why it failed
- **<attempt 2>** — why it failed

## Why this fix (not alternatives)

<1-3 sentences. Guards against future-Claude trying the same wrong alternatives.>

## Related

- Wiki: [[page-name]]
- Memory: `memory/file.md`
- Similar issue: `NNNN-other-issue.md`
