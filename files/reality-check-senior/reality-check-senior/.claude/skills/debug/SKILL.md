---
name: debug
description: Guided debugging of an ML/training/inference issue. Use when the user reports a bug, error, training failure, NaN loss, OOM, wrong output, performance regression, or "something's broken". Guides toward root cause via questions; does not just hand over the fix.
argument-hint: [symptom or error message]
allowed-tools: Read, Grep, Glob, Bash(git log:*), Bash(git diff:*), Bash(tail:*), Bash(cat:*)
---

# /debug — Guided Root-Cause Analysis

## Step 1 — Gather, do not guess

Before proposing causes, the user must answer (ask in order, stop if any answer is missing):

1. **Symptom:** what is the exact behavior? What did you expect, what did you see? Error message + full traceback if any.
2. **Reproduction:** what's the smallest command that reproduces it? Is it deterministic or flaky?
3. **What changed:** since when did this break? `git log --oneline -10` — anything suspicious? Data update? Library upgrade? Hardware change?
4. **What you've tried:** what hypotheses have you already ruled out? Don't repeat the user's work.
5. **Your current hypothesis:** what do you *think* is happening? (Often the right answer; sometimes the blind spot.)

Format: numbered questions, nothing else. Wait for answers.

## Step 2 — Triage by symptom

Once you have answers, route by ML failure-class:

### NaN loss / exploding gradients
- Check: lr, grad clipping, mixed-precision (fp16 → try bf16), bad inputs (NaN in data, log(0), divide by 0), softmax over masked-all logits.
- Verify the current PyTorch AMP recommendations via **context7** — the `torch.cuda.amp` → `torch.amp` migration trips people up.

### Loss not decreasing
- Sanity check: can the model overfit 1 batch? If no → bug in model/loss/data. If yes → optimization/regularization issue.
- Check: data labels correct (shuffled labels test), loss matches metric, lr not too small, gradient flow (`grad is None`?).

### OOM
- Profile where: forward, backward, optimizer states, activations. `torch.cuda.memory_summary()`.
- Solutions tier list: lower batch → gradient accumulation → gradient checkpointing → mixed precision → CPU offload → FSDP/DeepSpeed.

### Train OK, val/test bad
- Distribution shift between splits? Different preprocessing? Leakage you didn't have in val? Overfitting?
- Run on training data — if also bad, it's not generalization, it's a code bug.

### Train OK in dev, broken in prod (training-serving skew)
- Different preprocessing path? Different feature order? Different tokenizer version? Different dtype?
- Compare a single example through both paths byte-for-byte.

### DDP / multi-GPU bugs
- Hang → `find_unused_parameters`, `dist.barrier()` mismatch, NCCL timeout.
- Different loss per rank → seed/data sharding issue, BN sync, dropout RNG.
- Deadlock at save → not saving rank-0-only.

### LLM-specific
- Wrong output → first check the prompt actually rendered (template bug, missing variable).
- Worse than baseline → eval set contamination? Generation params (temp/top-p)? Tokenizer mismatch?
- Hallucinations from RAG → it's almost always retrieval, not generation. Check hit rate first.

## Step 3 — Walk the user to it, don't hand it over

- Offer the **top 2 hypotheses** in order of likelihood, with a **diagnostic command** for each ("run this — if X you have hypothesis A, if Y hypothesis B").
- Let them run the diagnostic and report back.
- Iterate until root cause is found.
- Only at the end, summarize the fix. Then ask: *"What would have caught this earlier?"* (test, assertion, type-check, eval).

## Hard rules

- **No drive-by fixes.** "Add `.detach()`" without explaining why teaches nothing.
- **Hypothesis before solution.** State what you think is happening and why before suggesting changes.
- **Diagnostic before fix.** A test that distinguishes hypothesis A from B is worth more than the fix itself.
- **End with prevention.** Every debug session ends with "what would have caught this earlier" — a test, an assertion, a typed config, a CI check.
