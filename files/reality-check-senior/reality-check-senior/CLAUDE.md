# Project: <YOUR PROJECT NAME>

**WHAT:** <one-sentence problem statement>
**STACK:** PyTorch 2.x, transformers, W&B, DVC (data), MLflow (experiments), Hydra (configs).

---

## How to use this agent

This repo is configured with the **Reality-Check Senior** Claude Code agent.
Persona lives in `.claude/output-styles/reality-check.md`. Skills live in `.claude/skills/`.
Run `/help` for the command menu. Run `/output-style` and pick `Reality-Check Senior` if it isn't active.

**Default workflow:** start in Plan Mode (`Shift+Tab` twice) for any `/review`, `/tradeoffs`, or change touching `src/training/` or `src/data/`. Exit plan mode only when the user types `proceed`.

---

## Commands

```
make train        # single-GPU smoke run on tiny split
make train-ddp    # torchrun multi-GPU
make eval         # runs golden eval set + writes report to evals/reports/
make lint         # ruff + mypy
make test         # pytest -q
make data-pull    # dvc pull
```

---

## Layout

- `src/data/` — loaders + splits. **Read `docs/data.md` before reviewing changes here.**
- `src/models/` — `nn.Module` definitions.
- `src/training/` — loop, AMP, DDP, checkpointing. **Read `docs/training.md` for DDP rules.**
- `src/eval/` — metrics + error analysis notebooks.
- `src/llm/` — prompt templates, RAG, agents. **Read `docs/llm-stack.md` before reviewing.**
- `configs/` — Hydra configs, one file per experiment family.
- `evals/` — golden eval suite (test cases, judges, RAG retrieval checks).
- `data/` — DVC-tracked, never committed. `data/raw/` is read-only.

---

## Non-obvious conventions (the agent enforces these)

- **Splits:** Always `GroupKFold` by `user_id` on user-level data; `TimeSeriesSplit` on temporal. Random `KFold` on either is a defect.
- **Preprocessing:** Fit scalers/encoders on **train only**, transform val/test. Use sklearn `Pipeline` inside CV — never before.
- **Class imbalance:** Resampling (SMOTE, etc.) goes **inside** the CV loop, never before splitting.
- **Experiments:** Every run logs to W&B project `<x>` with tags `git rev-parse HEAD` + DVC data hash. No exceptions.
- **Determinism:** Any "reproducibility" claim requires seeded numpy/torch/python/CUDA + `torch.use_deterministic_algorithms(True)`.
- **LLM evals:** Application-specific test cases live in `evals/`. Generic "helpfulness" judges are not accepted as evidence.
- **Secrets:** `.env` only, never in configs. CI fails on any committed key.

---

## Progressive disclosure

When the agent needs deeper context, it loads:

- `@docs/data.md` — split strategy, leakage priors, label provenance
- `@docs/training.md` — DDP/AMP/grad-accum rules, checkpointing
- `@docs/llm-stack.md` — RAG, prompt injection surface, eval methodology
- `@docs/evals.md` — golden set construction, judge validation, error analysis

Do not inline these into responses; link out.

---

## Things the agent must never do (enforced by hooks, not prose)

- `rm -rf` anything in `data/` or `checkpoints/` → blocked by `.claude/hooks/block-data-rm.sh`
- Edit files without running `ruff` + `mypy` after → `PostToolUse` hook handles this
- Push to `main` directly → CI blocks; agent should refuse if asked
