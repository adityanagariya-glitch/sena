---
name: commit-push-pr
description: "Stage final code and create a commit (and optionally a PR) following SENA's Conventional Commits + no-push-to-main rules. Delegates the actual commit message to sena-git-committer. Use ONLY when the user explicitly asks to commit and the pipeline has produced clean code (sena-cleaner returned CLEAN)."
argument-hint: "[pr-title]"
allowed-tools: Bash(git status), Bash(git diff:*), Bash(git log:*), Bash(git add:*), Bash(git commit:*), Bash(gh pr:*)
---

# commit-push-pr

## 1. Pre-flight (run from monorepo root)

Detect which SENA services were touched, then test only those — running every service's tests on every commit wastes minutes.

```powershell
$changed = git diff --name-only HEAD
$services = @()
if ($changed -match 'sena-ai/services/onboarding/')   { $services += 'onboarding' }
if ($changed -match 'sena-ai/services/voice/')        { $services += 'voice' }
if ($changed -match 'sena-ai/services/case_review/')  { $services += 'case_review' }
foreach ($svc in $services) {
  python -m pytest "sena-ai/services/$svc/tests/" -x -q
  ruff check "sena-ai/services/$svc/src/"
  ruff format --check "sena-ai/services/$svc/src/"
}
```

Abort the commit if ANY of:
- pytest red on any touched service
- ruff check finds any issue
- ruff format --check shows unformatted files (auto-fix first: `ruff format <path>`)
- `sena-cleaner` STATUS: CLEAN was not produced this session

Also confirm the Gemini hook gate is satisfied if any `gemini*` or `demo_live*` file is in the diff (the `pre-tool-use.sh` hook should have blocked the edit otherwise — but double-check).

## 2. Inspect diff for SENA-forbidden content

Before staging, scan `git diff --staged` for these strings — abort if any match a non-fixture path:

| Pattern | Why blocked |
|---------|-------------|
| `.env`, `.env.local`, `*.pem`, `*.key`, `id_rsa`, `id_ed25519` | Secret-file leak |
| `gemini-2.5-flash-native-audio`, `gemini-live-2.5-flash`, `gemini-2.0-flash-live` | Deprecated Gemini model id |
| `LiveClientRealtimeInput(media_chunks` | Deprecated Gemini API |
| `session.send(input=` | Deprecated Gemini API |
| Hardcoded NDIS number (9-digit) outside `fixtures/` | PII risk |
| Real participant email outside `fixtures/` | PII risk |

Then stage with explicit paths only — NEVER `git add .` or `git add -A`.

## 3. Stage + commit

Route the commit message to **`@agent-sena-git-committer`** — it knows the SENA-specific body rules:
- Rule numbers from `onboarding_system.md` if that file changed
- Tool names added/removed if `FUNCTION_DECLS` changed
- "Flutter: handle new event type '<type>'" if a new WS event was added
- TASKS.md task IDs and status transitions
- Co-Authored-By footer

Commit type cheat sheet:
- `feat(onboarding):` new tool / new WS event / new prompt Rule
- `feat(voice):` new dictation endpoint / new Bedrock prompt
- `feat(case_review):` new endpoint / new pgvector flow
- `fix(<svc>):` bug repair
- `security(<svc>):` tenant-isolation fix, secret leak, auth fix
- `docs:` `FLUTTER_DEV_HANDOFF.md`, `CLAUDE.md`, `TASKS.md`, prompts/*.md
- `test(<svc>):` tests-only
- `chore:` deps, configs, lint, CI, hooks
- `refactor(<svc>):` internal restructure, no behaviour change
- `perf(<svc>):` performance only

NEVER `--amend` a published commit. NEVER `--no-verify`. NEVER bypass hooks. NEVER `-c commit.gpgsign=false`.

## 4. Push + PR (only if user explicitly says "open PR")

- Target branch is `dev`. PRs against `main` happen by human review only — this skill never opens one.
- `git push -u origin HEAD` — NEVER `--force` or `--force-with-lease` unless the user explicitly authorises in writing this session.
- `gh pr create --base dev --title "<title>" --body "<auto-built from commit body>"`
- `gh pr checks --watch`

If the diff touches Flutter-facing contracts (new WS event, payload key change, new validation code), the PR body MUST link to the `FLUTTER_DEV_HANDOFF.md` Issue # that documents the contract — otherwise the Flutter team won't know.

## 5. Verify
- `git log -1 --stat` — confirm the commit recorded what was intended.
- If a `FUNCTION_DECLS` change: confirm `test_function_decls_cover_all_handlers` passes (`python -m pytest sena-ai/services/onboarding/tests/test_tools.py::test_function_decls_cover_all_handlers`).
- If PR was created, print the PR URL.

## What this skill will NOT do
- Push to `main`.
- Force-push.
- Skip hooks (`--no-verify`, `--no-gpg-sign`).
- Bypass `sena-cleaner`'s CLEAN gate.
- Stage `.env`, secrets, or hooks-state flag files even if the user asks.
- Open a PR against `main` (PRs target `dev` only).
