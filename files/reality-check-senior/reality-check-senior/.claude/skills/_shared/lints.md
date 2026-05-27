# AI/ML Lint Checklist

This is the canonical checklist. `/review` and `/roast` both load this. **Never duplicate this list elsewhere.**

Apply every section that's relevant to the diff. Skip silently if a section doesn't apply.

---

## 🔴 Data (leakage = career-ending; treat every miss as BLOCKER)

- [ ] **Splits respect entity boundaries.** Per-user data → `GroupKFold(groups=user_id)`. Temporal data → `TimeSeriesSplit`. Random `KFold` on either is a defect.
- [ ] **Preprocessing fit on train only.** Scalers, encoders, vocab, IDF, target-encoding — all fit on train fold, transformed onto val/test. Use sklearn `Pipeline` inside the CV loop.
- [ ] **No target leakage.** Look hard for: features derived after the event, aggregates that span the split boundary, "future" information, labels-in-features.
- [ ] **Resampling inside the loop.** SMOTE/oversampling on the full dataset before splitting → leakage. Must happen per fold.
- [ ] **Test set is sacred.** No augmentation on val/test. No tuning on test. No looking at test set metrics until final report.
- [ ] **Data version pinned.** DVC hash or equivalent referenced in the experiment log. If not — RETHINK; results are not reproducible.

## 🟠 Modeling

- [ ] **Baseline exists.** Majority class / mean predictor / last-value / linear model. If no baseline — STOP, demand one. Without it, "X% accuracy" is meaningless.
- [ ] **Loss matches metric.** Or there's a documented reason (BCE-with-logits vs BCE, focal loss for imbalance, label smoothing for calibration).
- [ ] **Hyperparameter search done right.** Nested CV or a held-out tune set. Never `GridSearchCV` then report scores on the same data.
- [ ] **LLM fine-tuning eval discipline.** Eval set is disjoint from instruct/SFT data. Contamination check on eval prompts vs. training corpus.
- [ ] **Calibration considered.** If downstream uses probabilities (thresholds, rankings, risk scores) and the model isn't calibrated — flag it.

## 🟠 Training

- [ ] **AMP idioms current.** `torch.amp.autocast(device_type='cuda', dtype=torch.bfloat16)` on A100/H100 — not the deprecated `torch.cuda.amp.autocast`. fp16 + GradScaler is legacy unless on V100/T4. **Verify the user's PyTorch version via context7 before recommending.**
- [ ] **DDP correctness:** `sampler.set_epoch(epoch)` every epoch; checkpoint save on rank 0 only; `find_unused_parameters=False` unless required; `dist.barrier()` before saving.
- [ ] **Gradient accumulation:** loss scaled by `1/accum_steps`; `optimizer.step()` and `zero_grad()` only every N steps; `no_sync()` on intermediate microbatches under DDP.
- [ ] **Mixed-precision gotchas:** loss in fp32; logits in fp32 before softmax for stability; no `.half()` on anything except activations.
- [ ] **Determinism if claimed:** seed numpy/torch/python/cuda; `torch.use_deterministic_algorithms(True)`; `CUBLAS_WORKSPACE_CONFIG=:4096:8`.
- [ ] **Checkpointing:** atomic writes (write-then-rename), optimizer + scheduler + RNG state included, not just weights.
- [ ] **OOM safety:** gradient checkpointing considered for >7B; activation offload; tensor-parallel/FSDP appropriate to scale.

## 🟠 LLM / RAG / Agents

- [ ] **Application-specific eval set exists.** Not "we use HELM" / "we ask GPT-4 if it's good." Real test cases from real failures.
- [ ] **LLM-as-judge is validated.** TP/TN rates against human labels documented. Otherwise the judge is decoration.
- [ ] **Retrieval evaluated separately from generation.** Hit rate, MRR, NDCG before blaming the LLM. Most "bad RAG" is bad retrieval.
- [ ] **Prompt injection surface considered.** Any retrieved doc, tool output, or user-controlled text can carry hostile instructions. Quote, don't concatenate.
- [ ] **Tool calls allow-listed.** Destructive tools require confirmation. No `bash` tool to an unsandboxed shell.
- [ ] **Cost + p95 latency measured.** Per request. Budget assertion in CI.
- [ ] **Caching layer for repeat prompts.** Semantic or exact-match. Otherwise costs scale linearly with traffic.
- [ ] **Streaming vs. batched chosen deliberately.** Not "we stream because it's cool."

## 🟠 MLOps / Reproducibility

- [ ] **Experiment tracking wired.** W&B / MLflow / Neptune. No "I'll add it later."
- [ ] **Run logs:** git SHA, data version, full config, hardware, wall-clock, peak memory.
- [ ] **Model registry on promotion.** Links back to commit + dataset hash + eval report.
- [ ] **CI runs the smoke train + smoke eval.** A 30-second run that catches breakage.
- [ ] **Drift monitoring planned** if this is going to production: input distribution, output distribution, performance on a holdout slice.

## 🟡 Code quality (ML-flavored)

- [ ] **Configs externalized.** Hydra or equivalent. No hardcoded paths, lr, batch size.
- [ ] **`if __name__ == '__main__':` guard** on training scripts (DDP-safe).
- [ ] **Device handling:** no `.cuda()` calls; use `.to(device)` with a single source of truth.
- [ ] **Type hints on public functions.** Tensors get shape annotations in docstrings or `jaxtyping`.
- [ ] **Notebooks are not source code.** Anything reused goes in `src/`.

## 🔵 Style / Nits

- [ ] f-strings over `.format()` over `%`.
- [ ] `pathlib.Path` over `os.path`.
- [ ] `logging` over `print` in non-trivial scripts.

---

## How to apply this

1. Walk every section that touches the diff.
2. Cite file:line for each finding.
3. Order findings by severity in the output.
4. If a 🔴 fires → verdict is `FIX FIRST` minimum.
5. If 3+ items across categories fire → verdict is `RETHINK`.
6. If everything passes and the design is sound → verdict is `SHIP`, but still leave 1 follow-up question.
