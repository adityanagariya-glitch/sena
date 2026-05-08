# SENA Multi-Model Workflow — Plan

> **Status:** design only — no code, no orchestrator yet.
> **Author input:** raw concept (Sonnet=Plan, Haiku=Exec, Opus=Review with 2-retry loop).
> **This document:** customised for SENA's stack and risk profile.

---

## 1. Critique of the Raw Idea

### Keep
- Three-model split with strict, non-overrideable role boundaries.
- Pass/fail criteria per subtask defined upfront.
- Retry cap with human escalation.
- Parallel execution where the DAG permits.

### Reverse or Adjust

| # | Raw idea | SENA-specific problem | Adjustment |
|---|----------|----------------------|------------|
| 1.1 | Haiku writes the production code | Haiku is most prone to deprecated Gemini Live API calls, missing `tenant_id` in Redis keys, Pydantic v1 idioms — exactly SENA's failure modes | **Sonnet** writes code. **Opus** plans. **Haiku** does cheap pattern-gate only. |
| 1.2 | Strip context from Haiku to "prevent drift" | SENA drift = unfamiliarity with conventions (Pydantic v2, `SENA_AI_` prefix, structlog, current Gemini API). Stripping context **causes** drift. | Inject a **SENA Constitution** prefix into every executor prompt regardless of subtask. |
| 1.3 | Opus reviews only flagged sections | Tenant isolation bugs are *invisible* — they are missing-line bugs (no `tenant_id` in the key). They cannot be flagged ahead of time. | Two-tier review: Haiku scans every file for known patterns; Opus deep-audits only `security_tier ≥ 2` files (entire file, not flags). |
| 1.4 | "Code runs without errors" as a gate | Trusting model self-report is unsafe | Actually run `pytest services/<svc>/tests/ -x` between executor and audit. |
| 1.5 | No state, no resumption, no audit log | Conflicts with SENA's `TASKS.md` and `issues-solved/` institutional memory; not auditable for compliance | Persist `workflow-state.json` per run; append to TASKS.md and issues-solved/ at end. |
| 1.6 | Parallel Haiku → guaranteed file conflicts | Task A modifies `FormState`, task B imports it. Parallel writes break each other. | DAG-aware scheduling; git worktree per subtask; explicit merge stage before review. |
| 1.7 | Hook gates ignored | SENA pre-tool-use hooks block `gemini*` and `.py` edits without flags. A naive orchestrator bounces off the hooks. | Phase 0 sets `.claude/hooks-state/*.flag` files based on the planned `file_scope`. |
| 1.8 | One retry policy for all failures | Lint typo and tenant-leak both retry twice — wrong on both ends | Tiered retries: Tier-A (style) unlimited cheap loops; Tier-B (logic) ≤2; Tier-C (security/compliance) zero — straight to human. |

---

## 2. Revised Architecture

```
User Requirement
      │
      ▼
┌─── Phase 0 — Bootstrap ──────────────────────────────┐
│ • Read .claude/tasks/TASKS.md, issues-solved/INDEX   │
│ • Pre-set hook flags for planned Gemini / Python work │
│ • Init .agents/runs/<run_id>/workflow-state.json     │
└──────┬───────────────────────────────────────────────┘
       ▼
┌─── Phase 1 — Architect (Opus) ───────────────────────┐
│ Output: PLAN.md (DAG, not linear)                    │
│ Per subtask: file_scope, contract, security_tier,    │
│              acceptance, test_requirement            │
└──────┬───────────────────────────────────────────────┘
       ▼
┌─── Phase 2 — Executor (Sonnet × N, DAG-parallel) ────┐
│ Each Sonnet:                                         │
│  • SENA Constitution (always)                        │
│  • ITS subtask only                                  │
│  • Ancestor signatures (not sibling outputs)         │
│  • Writes to a git worktree                          │
└──────┬───────────────────────────────────────────────┘
       ▼
┌─── Phase 3a — Cheap Gate (Haiku) ────────────────────┐
│ Pattern scan: print, os.environ, missing tenant_id,  │
│ deprecated Gemini calls, Pydantic v1 idioms,         │
│ missing assert_session_owner, time.sleep in src      │
│ Tier-A → Haiku regenerates, unlimited cheap retries  │
└──────┬───────────────────────────────────────────────┘
       ▼
┌─── Phase 3b — Test Run (real pytest) ────────────────┐
│ pytest services/<svc>/tests/ -x -q                   │
│ Failure → return to Phase 2 Sonnet, ≤2 cycles        │
└──────┬───────────────────────────────────────────────┘
       ▼
┌─── Phase 3c — Audit (Opus, security_tier ≥ 2 only) ──┐
│ Tenant isolation, NDIS compliance, Gemini bridge,    │
│ secret leakage, webhook HMAC                         │
│ Verdicts: PASS | TIER-B (1 retry) | TIER-C (escalate)│
└──────┬───────────────────────────────────────────────┘
       ▼
┌─── Phase 4 — Persist & Stage ────────────────────────┐
│ Merge worktrees, update TASKS.md,                    │
│ write issues-solved/ if retries>2,                   │
│ generate commit (NEVER push)                         │
└──────────────────────────────────────────────────────┘
```

---

## 3. Phase Specs

### Phase 1 — Architect (Opus)

**Why Opus and not Sonnet:**
- A flaw in the plan multiplies across N executors. The plan is the smallest, highest-leverage artifact.
- NDIS compliance reasoning, tenant boundary identification, and Gemini Live constraint analysis benefit from the strongest model.
- Cost amortised: 1 Opus call enables ≤N Sonnet calls.

**Inputs:**
- User requirement
- `.claude/tasks/TASKS.md` excerpt (related work)
- Reads relevant SENA files via the Read tool — does not need them pre-pasted
- SENA Constitution (see §4)

**Output: `PLAN.md`**
```yaml
plan_id: <uuid>
service: onboarding | voice | case_review | shared
subtasks:
  - id: 1
    title: "Short imperative"
    file_scope: ["services/onboarding/src/.../foo.py", "services/onboarding/tests/test_foo.py"]
    depends_on: []
    contract:
      adds: ["FormState.normalise_field_status() -> dict[str, str]"]
      modifies: ["FUNCTION_DECLS in services/tools.py"]
    security_tier: 1   # 1=routine | 2=tenant-touching | 3=auth/secrets/Gemini-bridge
    test_requirement: "parametrize over 5 input shapes; cover empty, missing-key, dotted-collision"
    acceptance:
      - "lint passes"
      - "pytest -x green"
      - "FUNCTION_DECLS test asserts new tool name"
  - id: 2
    depends_on: [1]
    ...
```

Subtasks form a **DAG**. Phase 2 walks the DAG, runs roots in parallel, blocks dependents until ancestors merge.

---

### Phase 2 — Executor (Sonnet × N)

**Why Sonnet and not Haiku:**
- Haiku has a higher rate of deprecated Gemini Live patterns (training data heavily weighted to 2024-era APIs).
- Sonnet better at distinguishing Pydantic v2 idioms from v1.
- Tenant isolation is a *thinking* task — easy to forget the line that matters.

**Each Sonnet instance receives:**
1. **SENA Constitution** (constants — see §4)
2. **Its subtask only** (scope, contract, acceptance)
3. **Ancestor signatures** — for every `depends_on` ancestor, just the public surface (function signatures, type hints) of new code, not the full implementation
4. **Read access** to existing project files via Read tool
5. **No sibling outputs** — siblings are reconciled in the merge stage, not at write time

**Isolation:** each Sonnet writes into its own git worktree (`runs/<run_id>/wt-<subtask_id>/`). Prevents parallel writes from clobbering shared files.

**Output:**
- File edits in the worktree
- `outputs/subtask_<id>.md` — short summary (what was added, what tests were written)

**Merge stage (between Phase 2 and Phase 3a):**
- Run a **conflict detector** on shared files (`FormState`, `FUNCTION_DECLS`, `onboarding_system.md` rule numbering).
- If conflicts exist, spawn a single Sonnet "merger" with all colliding diffs and the merge contract — produce one coherent change.
- If no conflicts, fast-merge worktrees into a unified scratch branch.

---

### Phase 3a — Cheap Gate (Haiku)

**Why Haiku:**
- Pattern detection is fast and token-cheap.
- 90% of common SENA convention violations match a regex; Haiku reasons about edge cases the regex over/under-matches.

**Deterministic pattern checks (regex first, Haiku reviews ambiguous matches):**
- `\bprint\(` outside `tests/`
- `os\.environ` (must be `settings.<field>`)
- Redis key construction without `tenant_id` interpolation: `f"sena:[^"]*:"` lacking `{tenant_id}`
- Deprecated Gemini patterns: `session\.send\(input=`, `LiveClientRealtimeInput`, `send_client_content` for turn messages
- Deprecated Gemini models: `gemini-2\.`, `gemini-live-2\.`, `native-audio-preview-`
- Pydantic v1: `\.dict\(\)`, `\.parse_obj\(`, `parse_raw\(`
- Missing `assert_session_owner` in repo methods that read/write session state
- `time\.sleep` outside `tests/`
- Hardcoded NDIS numbers / real emails outside `fixtures/`

**Action:**
- Tier-A finding → Haiku regenerates the offending block in place. Unlimited cheap retries.
- Pattern flags but Haiku judges it a false positive → annotate and pass.
- If a check requires reasoning Haiku is uncertain about → escalate to Opus (rare).

---

### Phase 3b — Test Run (real pytest)

**Not a model — actual subprocess.**

```powershell
cd "C:\Users\Admin\Downloads\sena-mobile\sena-mobile\SENA_AI\sena-ai\services\<svc>"
python -m pytest tests\ -x -q --no-header
```

- Failure tail piped back into a Phase 2 Sonnet retry with the failure context.
- Max 2 retry cycles per subtask. Then escalate.

---

### Phase 3c — Audit (Opus)

**Runs only on files where `security_tier ≥ 2`** (per Phase 1 plan).

Files always tier-2+:
- `repositories/` (any)
- `services/gemini_live.py`
- `api/ws_routes.py`
- `services/tools.py` (when adding/removing a tool)
- Any file touching `tenant_id`, `assert_session_owner`, JWT, or webhook HMAC

**Opus checks:**
- **Tenant isolation:** every Redis key has `tenant_id`; every repo method calls `assert_session_owner`
- **NDIS compliance:** human-in-the-loop preserved; no auto-submit added; advance_step gate intact
- **Gemini bridge:** no audio gating regression; current API surface only; no `_agent_speaking` flag pattern
- **Webhook signature:** HMAC verified; secret never logged
- **Secret leakage:** no API keys, tokens, or tenant data in log lines or WebSocket emit payloads
- **Read-only paths:** `update_field` rejects writes to `readonly_paths`

**Verdict tiers:**

| Tier | Meaning | Action |
|------|---------|--------|
| PASS | All checks clean | proceed to Phase 4 |
| TIER-B | Logic gap, missing test, contract drift, dedup miss | 1 retry → Phase 2 Sonnet |
| TIER-C | Tenant leak, deprecated Gemini in committed file, secret leak, NDIS compliance regression | **STOP. Human escalation. NO auto-retry.** |

TIER-C is treated as production-blocking. The workflow does not loop on it because the failure mode means the model has misunderstood a non-negotiable constraint.

---

### Phase 4 — Persist & Stage

- Merge the unified scratch branch back into the working branch
- Update `.claude/tasks/TASKS.md` (mark subtasks complete with date stamp)
- If any subtask required >2 retries → write `.claude/issues-solved/NNNN-<symptom>.md`
- Generate `commit.sh` with `git add` + `git commit` heredoc (Conventional Commits)
- **Never** generate `git push`. Print the commit script for the human to run.
- Trigger graphify rebuild (`_rebuild_code`) if any source file changed

---

## 4. SENA Constitution (constants — every executor prompt)

A short, machine-pasteable block at `.agents/SENA_CONSTITUTION.md`. To be drafted in the next step. Will contain:
- Async-first rules (no blocking calls; structlog; Pydantic v2 idioms)
- `SENA_AI_` env prefix + settings-pattern only
- Redis key pattern with `tenant_id` always included
- Gemini Live current API surface, with explicit "DO NOT USE" deprecated list
- FormState contract: tools return `{"ok": bool, ...}`, never raise
- TASKS.md update obligation
- Lint config: ruff line 100, mypy strict, isort first-party
- Test conventions: `fake_redis` fixture, `AsyncMock` for Gemini sessions, sentinel IDs only

This is the single source of truth for "how SENA code looks". The cheap gate validates against it.

---

## 5. State & Persistence

```
.agents/runs/<run_id>/
  workflow-state.json     # plan_id, DAG progress, retry counts, token usage
  PLAN.md                 # Phase 1 output
  outputs/
    subtask_1.md          # per-subtask Sonnet summary
    subtask_2.md
  audits/
    subtask_3.md          # Phase 3c Opus findings
  conflicts/
    merge_<n>.md          # if a merge agent ran
  commit.sh               # Phase 4 — printed for human, never executed
```

After completion:
- Append to `.claude/tasks/TASKS.md`
- If retries > 2 in any subtask → `issues-solved/` entry
- If a new convention surfaced (e.g. a new validator pattern) → human reviews, considers updating `.claude/memory/`

---

## 6. Cost & Escalation Caps

| Stage | Model | Typical calls | Cost driver | Cap |
|-------|-------|---------------|-------------|-----|
| Phase 1 | Opus | 1 | Long context (project state) | 1 |
| Phase 2 | Sonnet | N (subtasks) + retries | Parallel | N≤8 subtasks; ≤6 total retries |
| Phase 3a | Haiku | up to N + cheap regens | Token-light | unlimited (cheap) |
| Phase 3b | none | 0 | CI compute | — |
| Phase 3c | Opus | only tier ≥ 2 files | Long files | ≤4 audits per run |
| Phase 4 | Sonnet (lite) | 1 | Generate commit msg | 1 |

**Hard run abort if any cap exceeded** → human review.

---

## 7. Hook Integration (SENA-specific)

**Pre-flight (Phase 0):**
- Plan touches `gemini*` or `demo_live*` files? → touch `.claude/hooks-state/skills-gemini.flag` and `.claude/hooks-state/ctx7-gemini.flag` (after Context7 fetch)
- Plan touches any `.py`? → ensure `.claude/hooks-state/ctx7-session.flag` exists (create after first Context7 call in Phase 1)

**Post-Phase-2 merge:**
- Run graphify rebuild
- Run ruff format on changed files

**Post-Phase-4 (commit generation):**
- Confirm `Stop` hook will trigger graphify rebuild on session end

---

## 8. Tiered Retry Policy (replaces the raw "max 2" rule)

| Failure tier | Examples | Retry budget |
|--------------|----------|--------------|
| Tier-A (style) | Lint, formatting, naming, missing import | Unlimited Haiku regens |
| Tier-B (logic) | Test fails, contract drift, missing readback, dedup miss | ≤2 Sonnet retries |
| Tier-C (compliance/security) | Tenant leak, deprecated Gemini API, secret in log, NDIS gate bypassed | **0 — straight to human** |

---

## 9. Open Questions for the User

1. **Orchestrator runtime** — Anthropic SDK direct? Claude Agent SDK? Or driven from inside Claude Code via Task tool? Each has different cost/control trade-offs.
2. **Parallelism cap** — practical max for Sonnet × N? (Default 4 in plan; raise if budget allows.)
3. **TIER-C escalation channel** — file in `.claude/escalations/`, GitHub issue, Slack, email, or just halt and surface in CLI?
4. **Test execution scope** — should the workflow run pytest, or only stage and let the human run? (Recommend run; auto-revert on red.)
5. **Worktree isolation** — adopt `git worktree` per subtask now, or start single-thread and add later?
6. **Initial scope** — start with onboarding service only, or all three (voice, onboarding, case_review)?
7. **Failure auditing** — every TIER-C halt writes to `.claude/issues-solved/`? (Recommend yes.)

---

## 10. Rollout Plan (do not big-bang)

| Step | Deliverable | Gate |
|------|-------------|------|
| A | Draft `SENA_CONSTITUTION.md` + revise the three persona files (`01-architect.md`, `02-executor.md`, `03-auditor.md`) to match this workflow | Human review |
| B | Build orchestrator (Python script). Single-subtask mode only — no parallelism, no worktree | End-to-end on a known-good toy task |
| C | Add cheap-gate Haiku patterns + Phase 3b real pytest | Run on a known-bad subtask; verify it catches the planted regressions |
| D | Add Phase 3c Opus audit + tier-C escalation handling | Plant a tenant-isolation bug; verify TIER-C halts |
| E | Add parallel Sonnet × N with `git worktree` and merge stage | Run two non-conflicting subtasks in parallel |
| F | Wire to TASKS.md persistence, issues-solved/ entries, graphify rebuild | First production-style run |

Each step is its own PR. Do not merge step E before D is proven.

---

## 11. What this design rejects from the raw idea

- **"No context for Haiku to prevent drift"** — wrong direction for SENA. Convention drift is the bigger risk than scope drift. Replaced with mandatory SENA Constitution prefix.
- **"Opus reviews flagged sections only to control cost"** — undercosts what tenant-isolation review actually requires. Replaced with two-tier review: cheap full-pass (Haiku), deep audit on `security_tier ≥ 2` files only (Opus).
- **"Max 2 retry loops" as a single rule** — replaced with tiered retry: A unlimited, B ≤2, C zero.
- **"Haiku writes the production code"** — flipped. Sonnet executes; Haiku is the cheap pattern gate.
