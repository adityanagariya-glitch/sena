# Evals Conventions (loaded on demand)

## Golden eval set construction

1. **Source from real failures**, not from imagination. Sample 200–500 real production inputs (or representative inputs for new systems).
2. **Stratify** by: input type, difficulty, failure mode if known, user segment.
3. **Human-label a calibration set** of 50–100 — this is the ground truth your LLM-judge gets validated against.
4. **Lock the set.** Hash it, version it, never edit after locking. If you find new failure modes, *add* a new set, don't mutate the old one.

## LLM-as-judge validation

Before trusting a judge:
1. Human-label 100 outputs (good/bad or graded).
2. Run the judge on the same 100.
3. Compute: agreement rate, false-positive rate (judge says good but human says bad — DANGEROUS), false-negative rate (judge says bad but human says good — annoying but safer).
4. **FP rate > 10% → judge is unfit.** It will rubber-stamp bad outputs.
5. Re-validate quarterly or after any prompt change to the judge.

## Per-experiment eval report (what `make eval` produces)

```
evals/reports/<run_id>/
├── summary.json     # headline metrics
├── per_case.csv     # one row per eval case, with prediction + judgment
├── failures.md      # top 20 failures with notes
├── slice_metrics.json  # metrics broken down by segment
└── delta_vs_baseline.md  # this run vs. previous main
```

## Slice metrics — never trust the aggregate

Always break out by:
- Input difficulty
- User segment / cohort
- Time period (if there's any temporal aspect)
- Failure-mode category

A 95% aggregate that's 99% on easy and 60% on hard is a different model than a flat 95%. The aggregate hides this.
