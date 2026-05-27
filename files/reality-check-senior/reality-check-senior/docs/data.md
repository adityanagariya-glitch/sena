# Data Conventions (loaded on demand)

This is loaded when the agent reviews `src/data/` or anything mentioning splits, leakage, or labels. Keep CLAUDE.md lean — depth lives here.

## Split strategy by data type

| Data shape | Split | Why |
|---|---|---|
| Per-user, per-session, per-entity | `GroupKFold(groups=user_id)` or `StratifiedGroupKFold` | Same user in train+val → val accuracy is fiction |
| Temporal / timeseries | `TimeSeriesSplit` with gap | Random split → future leaks into past |
| Hierarchical (user→session→event) | Group at the outermost level | Otherwise you leak through aggregates |
| Geographic | Hold out by region | Models memorize region-specific patterns |
| Multi-label classification | `MultilabelStratifiedKFold` (iterstrat) | Naive stratify breaks on multi-label |

## Leakage patterns we've actually shipped (and how we caught them)

1. **Target encoding before split** — fit on all data, leaked target into features. Caught by W&B regression on val curve.
2. **Time-window features computed globally** — "user's avg purchase in last 30 days" computed before splitting → future leak.
3. **Test set in training corpus for LLM** — public benchmark in pretraining data. Caught by canary detection.
4. **SMOTE before split** — synthetic samples generated from full dataset, including val. Caught by suspiciously good val metrics.
5. **Embeddings trained on val data** — sentence transformer trained on the whole corpus, then used as features. Caught by a leakage audit.

## Labels

- Provenance documented in `data/labels/README.md` — who labeled, when, with what guidelines.
- Inter-annotator agreement (κ) computed for any human-labeled set. Below 0.6 → labels are noise, not signal.
- Label drift monitored: if today's labels distribute differently from training labels, model performance is misleading.

## DVC

- `dvc.lock` is the source of truth. Reproducing a run means `dvc checkout` to that lock.
- Never `dvc remove` without an `--outs` flag. Blocked by hook.
- Pull before train: `make data-pull`.
