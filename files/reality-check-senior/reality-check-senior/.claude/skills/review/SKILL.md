---
name: review
description: Reality-check code review with AI/ML-specific lints. Use for any code review, PR triage, "look at this", "what do you think of this approach", or when the user shares code/diffs/architecture for evaluation. Auto-trigger on phrases like "review", "look at", "thoughts on", "is this good", or when a PR URL is shared.
argument-hint: [files or PR URL or "current diff"]
allowed-tools: Read, Grep, Glob, Bash(git diff:*), Bash(git log:*), Bash(gh pr:*), Bash(gh pr diff:*)
---

# /review — Reality-Check Code Review

## Phase 1 — Ground truth (silent, do not narrate)

1. **Resolve target.**
   - If `$ARGUMENTS` looks like a PR URL or `#N` → `gh pr diff $ARGUMENTS`.
   - If `$ARGUMENTS` is "current diff" or empty → `git diff HEAD` then `git diff --cached`.
   - If `$ARGUMENTS` is a file path → `Read` the file; also `git log -p -3 -- $ARGUMENTS` for recent context.

2. **Verify external API claims before judging.** For every library imported in the diff (torch, transformers, jax, sklearn, langchain, vllm, accelerate, peft, etc.):
   - Call `mcp__context7__resolve-library-id` with the library name.
   - Call `mcp__context7__get-library-docs` for the specific API used.
   - If the user's code uses a deprecated or non-existent API → that's a 🔴 BLOCKER and you have the doc URL to cite.
   - Do **not** rely on training memory for API correctness.

3. **For research claims** (paper citations, "X paper says Y") → use `mcp__playwright__browser_navigate` on the arxiv link and quote the actual line.

4. **Skip Phase 1 narration in the output.** This is internal.

## Phase 2 — Apply lints

Load and walk through every relevant section of `@.claude/skills/_shared/lints.md`. This is the canonical checklist; do not duplicate or paraphrase its rules — apply them.

Walk the diff section by section:
- For each finding, record: `file:line`, severity, mechanism, fix.
- For each library API in the diff: cite the Context7 doc URL.

## Phase 3 — Chain-of-Verification (silent)

Before emitting the verdict, run through:
- **Edge cases:** empty tensors, batch=1, single-class batches, NaN inputs, OOM at max seq len, unicode in text data.
- **Race conditions:** DDP rank ordering, async data loading, checkpoint save/load overlap.
- **Failure modes:** what happens if the dataloader crashes mid-epoch? If a node dies? If the optimizer state file is corrupt?
- **Scale:** what breaks at 10× current dataset / batch size / sequence length?
- **Ops:** how is this monitored, rolled back, debugged at 3 AM?

If any silent check surfaces a 🔴 not already in findings — add it.

## Phase 4 — Output

Use the **Reality-Check Senior** output style (three-block format):

**Verdict:** `SHIP` / `FIX FIRST` / `RETHINK` / `NEEDS DATA` — one line of why.

**Findings:** ordered by severity (🔴 → 🟠 → 🟡 → 🔵). Each:
- `file:line` — what's wrong — *mechanism* of failure — concrete fix (code snippet if non-trivial).
- For library-API findings: link the Context7 doc URL you verified against.

**Follow-ups:** 1–3 Socratic questions ("Why GroupKFold over StratifiedGroupKFold here?", "What's the p95 latency budget?", "Have you checked retrieval hit-rate separately?"). Or `NONE` if the work is clean.

## Hard rules

- **Never write the full fix yourself** unless the user explicitly asks. Show a diff snippet or describe the change.
- **No platitudes.** No "great work overall." If the work is good, say specifically *what* and *why*. Vague praise teaches nothing.
- **No vague critique.** "This might have issues at scale" is useless. "At batch_size=512 on A100-40GB, activations alone will OOM — see `transformers` gradient checkpointing docs" is useful.
- **One quote per source maximum** if citing external docs/papers; paraphrase the rest.
