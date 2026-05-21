# plans/

Empty by design. Plans are feature-scoped and ship with the feature.

## Lifecycle

1. **During a feature:** plan file lives here as `plans/<feature-slug>.md` (e.g. `plans/voice-onboarding.md`).
2. **When the feature ships:** the harness-upgrade skill (`sena-harness-upgrade`) moves the plan reference into `.claude/tasks/ARCHIVE.md` under the feature's closed entry and deletes the plan file from this folder.
3. **Between features:** this folder is empty — that's the steady state.

A non-empty `plans/` between features = in-flight work. An empty `plans/` = clean slate.

## When to add a plan here

- New feature touching 3+ files (mirror the `sena-planner` agent's output).
- Cross-service refactor.
- Any work where the executor (sena-implementer / sena-bug-fixer) needs a DAG to follow.

## When NOT to add a plan

- Single-line bug fixes.
- Typo / formatting.
- Status updates / triage (those go in `TASKS.md`).
