# sena-harness-upgrade — Reference

Detailed sub-routines, templates, and exact commands for each phase of `SKILL.md`.

---

## §1 — Feature archive sub-routine

**Trigger:** Phase 1 of feature-ship mode.

### Heading format for ARCHIVE.md

```markdown
## Feature <X> — <NAME> (CLOSED YYYY-MM-DD)

### #<task-id> — <task title> (YYYY-MM-DD)
- **Status:** completed (YYYY-MM-DD)
- **Priority:** P0 | P1 | P2
- **What shipped:** <bullet list, copied verbatim from TASKS.md>
- **Tests:** <count progression, e.g. 192 → 198 (+6 regression)>
- **Plan artifact:** <path if any>
- **Anti-recurrence guard:** <one-line durable lesson>
```

### TASKS.md reset template (after archive)

```markdown
---
title: Persistent Task List
updated: YYYY-MM-DD
---

> **Clean slate — YYYY-MM-DD.** <Feature X> shipped to <env>; <Feature Y> shelved at <state>.
> Full history is in `.claude/tasks/ARCHIVE.md`. The next feature's tasks go below; do NOT
> carry <Feature X> context into a new feature's planning unless the work directly extends
> shipped infrastructure.
>
> **New session: read `.claude/SESSION_START.md` FIRST.**

# SENA Task List

**Status legend:** `pending` | `in_progress` | `completed` | `blocked`

## Active

*(none — awaiting next-feature direction from user)*

## Backlog (deferred / blocked / decisions pending)

<list each blocked/deferred item, one bullet per>

## Conventions
<keep section unchanged>
```

---

## §2 — Stale-reference sweep — exact Grep patterns

Run these patterns one at a time. For each match, update or remove.

```bash
# Deleted handoff docs (post-2026-05-14)
Grep "FLUTTER_DEV_HANDOFF\.md|FLUTTER_CROSS_SCREEN_CONTEXT_CONTRACT\.md|FLUTTER_VOICE_INTEGRATION_FIXES\.md"

# Deleted plan files
Grep "no-graceful-muffin|v3-v4-enum-routines|cozy-waddling-river"

# Deleted dev artefacts
Grep "test_harness\.html|AI_logs\.txt"

# Old agent names (pre-2026-05-14 sena-* rename)
Grep "@agent-code-reviewer|@agent-doc-writer|@agent-log-analyzer|@agent-researcher|@agent-disciplined-engineering-collaborator"

# Deprecated Gemini APIs (always check, regardless of cycle)
Grep "session\.send\(input=|LiveClientRealtimeInput|send_client_content"

# Deprecated Gemini models
Grep "gemini-2\.5-flash-native-audio|gemini-live-2\.5-flash|gemini-2\.0-flash-live-001"
```

**Search scope:** `*.md` files in repo root + `.claude/**/*.md`. Skip `archive/`, `.venv/`, `ndis_markdown_docs/`.

**Updating historical log entries:** Do NOT update entries in `memory/sena-memory.md` or `memory/decisions.md` that describe past state — they are append-only history. Only update live-pointer files (CLAUDE.md, SESSION_START.md, TASKS.md, rules/*, skills/*, commands/*, CLAUDE.local.md, output-styles/*).

---

## §3 — Agent rename sub-routine

**Trigger:** Phase 3 finds an agent lacking the `sena-` prefix.

### Step 1 — PowerShell file move

```powershell
Move-Item -Path .claude\agents\<old-name>.md -Destination .claude\agents\sena-<new-name>.md
# If a matching command file exists:
Move-Item -Path .claude\commands\<old-name>.md -Destination .claude\commands\sena-<new-name>.md
```

### Step 2 — Update frontmatter `name:`

```yaml
# Before:
name: <old-name>
# After:
name: sena-<new-name>
```

### Step 3 — Update internal `**For <agent>:**` label inside `<principal_engineer_mode>` block.

### Step 4 — Grep for external references

```bash
Grep "@agent-<old-name>|sena-<new-name>"
```

Update every match in: `.claude/rules/sena-rules.md` (routing table), `.claude/skills/*/SKILL.md`, `.claude/commands/*.md`, `CLAUDE.md`, `CLAUDE.local.md` (shortcuts), other agent files (cross-references like log-analyzer → engineering-collaborator).

### Step 5 — Verify

```powershell
Get-ChildItem .claude\agents\ | Select-Object Name
# Every name must start with sena-
```

---

## §4 — Principal Engineer Mode block template

Inject right after `</role>` (or `</identity>`) in each agent.

```markdown
<principal_engineer_mode>
You operate under the Principal Engineer rules in `.claude/rules/principal-engineer.md`. Pin these before every action:

1. **No reinvention.** Grep the repo + check installed deps before writing new code. Mature library beats hand-rolled.
2. **No bloat.** Edit existing files; new files must be justified in one line.
3. **No stubs.** Working code or one sharp clarifying question — never TODOs/placeholders.
4. **Stay in scope.** Minimal diff. No opportunistic refactors.
5. **Optimization is default.** `asyncio.gather` for parallel awaits, `redis.asyncio.pipeline` for batch, `set`/`dict` for O(1) lookups.

Instant-fail anti-patterns: new file when an existing one would do; rebuilding what an installed dep provides; `Any`/`# type: ignore`/`# noqa` to silence tooling; refactoring "while you're there"; handing back a red build.

**For <agent-name>:** <one-line agent-specific mapping — see table below>
</principal_engineer_mode>
```

### Agent-specific mappings (canonical set as of 2026-05-14)

| Agent | One-line mapping |
|-------|------------------|
| `sena-planner` | Plan MUST include "Existing code to extend / Libraries to use" section BEFORE "New files to create". |
| `sena-task-breaker` | Every task with `target_files` flags `existing` (extending) or `new` (creating + justification). |
| `sena-implementer` | Grep `services/<svc>/src/` + `shared/` BEFORE adding a helper. Extend, don't duplicate. |
| `sena-business-reviewer` | "Reinvented existing helper" = STATUS: FAIL. Hand back to bug-fixer with `duplicate of <file:line>`. |
| `sena-security-reviewer` | Custom crypto/JWT/Redis-key-builder = INSTANT Critical. HALT workflow, escalate to human. |
| `sena-bug-fixer` | Before adding a new helper, Grep for an existing one. Reuse beats new. |
| `sena-optimization-reviewer` | Optimization via Edit only — never rewrite a module. Prefer stdlib/lib primitives. |
| `sena-cleaner` | BLOCK the cleaner→committer transition when reinvention or bloat detected. |
| `sena-git-committer` | Verify diff is in-scope per planner's target_files; halt on scope creep. |
| `sena-code-reviewer` | "Reinvented wheel" added to auto-block signatures regardless of other lens cleanliness. |
| `sena-researcher` | Rank findings: stdlib > installed lib > new install > custom code. End with `pip install <name>`. |
| `sena-log-analyzer` | "Property to restore" references existing helper, not synthesized new code. |
| `sena-doc-writer` | Ground every claim in a Read'd file:line. Don't invent module structures or env vars. |
| `sena-engineering-collaborator` | Rule 1 is a hard prerequisite of the `additive_extension` principle. |

---

## §4b — Orchestration Protocols wiring verification

**Trigger:** Phase 4 check or Phase 6 finds orchestration coverage missing.

### Check 1 — principal-engineer.md has `## 🎯 ORCHESTRATION PROTOCOLS`

```bash
Grep "ORCHESTRATION PROTOCOLS" .claude/rules/principal-engineer.md
```

If missing → the section was never added or was accidentally removed. Re-add from the canonical session (2026-05-15).

### Check 2 — CLAUDE.md `<orchestration>` block has all 10 sections

Grep for each — all must match:

```bash
Grep "Plan mode triggers|Dynamic recalibration|Root cause over symptom|Elegance check|Minimal blast radius" CLAUDE.md
```

Required full set: `Plan-first default` · `Subagent delegation` · `Plan mode triggers` · `Dynamic recalibration` · `Root cause over symptom` · `Elegance check` · `Minimal blast radius` · `Verification gate` · `Autonomous execution` · `Self-improvement loop`.

Missing any → add the section(s) from the canonical `<orchestration>` block in `CLAUDE.md` (written 2026-05-15).

### Check 3 — SESSION_START.md "Rules you MUST reload" has orchestration note

```bash
Grep "Orchestration Protocols" .claude/SESSION_START.md
```

If missing → add this bullet under `## Rules you MUST reload every session`:

```
- **Orchestration Protocols** (new 2026-05-15): sub-agent delegation triggers, plan mode triggers (3+ files / arch / blast-radius), dynamic recalibration ("stop and replan when"), root-cause over symptom (never skip/delete tests), elegance check (4-question pause before finalizing), minimal blast radius → out-of-scope observations go to `.claude/tasks/followups.md` not the diff
- **Self-improvement**: same lesson 3× → promote from `lessons.md` to `CLAUDE.md` permanent rule; repeating a `lessons.md` entry = instant-fail
```

---

## §5 — Agent Routing Mandate — canonical 13-row trigger table

Copy this verbatim into the `<agent_routing>` block in `CLAUDE.md`.

| Trigger | Route to |
|---------|----------|
| Multi-file refactor / new feature spanning 3+ files / architecture decision | `@agent-sena-planner` (plan + DAG) then `@agent-sena-task-breaker` |
| "Deep dive" / contract-first audit / multi-subsystem investigation / long debugging session | `@agent-sena-engineering-collaborator` |
| Greenfield Python coding (new file or full implementation from spec) | `@agent-sena-implementer` |
| Reviewer FAIL with hand-back contract (surgical patch needed) | `@agent-sena-bug-fixer` |
| NDIS / FormState / validator / advance_step / participant-facing code review | `@agent-sena-business-reviewer` |
| Tenant isolation / Redis key / Gemini-bridge / auth / webhook code review | `@agent-sena-security-reviewer` |
| Hot path (audio bridge, Redis loop, large JSON) optimisation | `@agent-sena-optimization-reviewer` |
| Final lint + artifact gate before commit | `@agent-sena-cleaner` |
| Conventional Commit generation (NEVER push) | `@agent-sena-git-committer` |
| Crash log / stack trace / pytest failure dump | `@agent-sena-log-analyzer` FIRST |
| Current third-party docs / library API / framework upgrade research | `@agent-sena-researcher` |
| Writing/updating CLAUDE.md / TASKS.md / SESSION_START.md / FLUTTER docs / README | `@agent-sena-doc-writer` |
| Ad-hoc external diff or non-SENA-path PR review (SHIP/FIX/BLOCK) | `@agent-sena-code-reviewer` |

**Exception:** trivial single-line edits, status questions, or follow-ups on already-routed work may stay in the main thread.

---

## §6 — lessons.md — format + seed

If `.claude/memory/lessons.md` is missing, create from this template:

```markdown
---
title: Lessons — User-Correction Failure Patterns
updated: YYYY-MM-DD
purpose: Capture every correction the user makes so future sessions don't repeat the same mistake. Read at session start. Append-only.
---

# Lessons

## Format
\`\`\`
### YYYY-MM-DD — <one-line symptom>
- **Failure pattern:** what Claude did wrong (specific, behavioural)
- **User correction:** what the user said (quoted if short)
- **Rule:** explicit testable behaviour for next time ("before X, do Y")
- **Scope:** when this rule applies (which kind of task / file / agent)
\`\`\`

## Distinction from `issues-solved/INDEX.md`
- `lessons.md` → process / collaboration / Claude-behaviour failures (user correction trigger).
- `issues-solved/INDEX.md` → technical / runtime / debugging recipes (>2 iterations OR >5 min trigger).

## Log

*(no entries yet — populate on first user correction)*
```

---

## §7 — sena-memory.md milestone entry — sample

After a cleanup cycle, append a single line to `.claude/memory/sena-memory.md`:

```
YYYY-MM-DD main — sena-harness-upgrade ran in <feature-ship | audit-only> mode. Phase results:
  Phase 1 (archive): <feature name> moved <N> task entries to ARCHIVE.md, TASKS.md reset to empty Active.
  Phase 2 (stale refs): <N> matches updated across <file list>.
  Phase 3 (namespace audit): all 14 agents prefixed sena-*; no renames needed | renamed <list>.
  Phase 4 (PE mode): all agents have <principal_engineer_mode> block | injected into <list>. Orchestration Protocols section in principal-engineer.md: present | added.
  Phase 5 (routing): trigger table covers all 14 agents | added <N> new rows for <new agents>.
  Phase 6 (orchestration + lessons): all <N>/10 orchestration sections present | <N> missing → added; SESSION_START.md reload section: present | updated; lessons.md has <N> entries.
  Phase 7 (record): this entry + <N> decision entries appended. Awaiting user commit confirmation.
```

---

## §8 — Final user-facing report template

End every cleanup cycle with this report shape:

```
## Cycle complete — <feature-ship | audit-only> mode

**Phase 1 (archive):** <one line>
**Phase 2 (stale refs):** <count> matches fixed in <file list>
**Phase 3 (namespace):** all agents sena-* prefixed | renamed <list>
**Phase 4 (PE mode):** <14/14> agents covered
**Phase 5 (routing):** <13/13> rows | added <N> new rows
**Phase 6 (orchestration + lessons):** <N>/10 sections present | <N> missing → added; SESSION_START.md reload: present | updated; lessons.md has <N> entries
**Phase 7 (record):** sena-memory.md + decisions.md updated

## Pending your decision

git status shows: <N> deletions, <N> modifications, <N> new files.

Suggested commit message:
\`\`\`
chore(.claude): <cycle summary>
- <bullet per phase that had changes>
\`\`\`

Confirm to stage and commit?
```

---

## §10 — CODE_FILES_TO_REVIEW.md pattern

**Trigger:** Phase 0 inventory surfaces a code file (`.py`, `.html`, `.dart`, `.ts`, …) that looks stale/dev-only.

**Rule:** never delete code without explicit user sign-off. Append candidates to `CODE_FILES_TO_REVIEW.md` at repo root and let the user decide.

### File template

```markdown
# Code Files for Review

> Files that look stale / dev-only / unused but require user sign-off before removal.
> Append new entries with today's date; mark `User decision:` line when user replies.

## YYYY-MM-DD entries

### `path/to/file.py` (or `.html`, `.dart`, `.ts`)
- **Why it looks stale:** <one line — e.g. "served deleted test_harness.html; routes now return 404">
- **What references it:** <grep results — file:line callers>
- **Recommendation:** <delete | keep | refactor>
- **User decision:** [pending → delete | keep | refactor]
```

### When the user fills `User decision:`

- `delete` → remove the file, sweep references via Phase 2 pattern, commit-prep
- `keep` → record reason in `decisions.md` so next cycle doesn't re-ask
- `refactor` → file a TODO in `TASKS.md` Backlog with link to this entry

### Examples (from 2026-05-14 cycle)

```markdown
### `sena-ai/services/onboarding/src/onboarding/main.py:15,40-59`
- **Why it looks stale:** harness routes (`/harness`, `/harness/fixtures/{step_id}`) served deleted `test_harness.html`; now return 404
- **What references it:** none external; only the routes themselves
- **Recommendation:** delete
- **User decision:** [pending]

### `sena-ai/demo_live_server.py` + `sena-ai/demo_client.html`
- **Why it looks stale:** standalone Gemini Live demo; voice onboarding deployed to EC2 makes this dev-only
- **What references it:** CLAUDE.md "Demo Stack" section, SESSION_START.md "Active services"
- **Recommendation:** keep (Gemini Live regression debugging) — but de-reference from SESSION_START.md
- **User decision:** keep, hide from session start (2026-05-14)
```

---

## §11 — Phase 0 inventory commands + AskUserQuestion bundling

### PowerShell inventory

```powershell
# Repo-level state
git -C <SENA_AI> status --short

# Markdown files at repo root (handoff docs, README, dev-only docs)
Get-ChildItem <SENA_AI> -Filter "*.md" -File | Select-Object Name

# In-flight plan files (anything in here that's committed should be archived)
Get-ChildItem <SENA_AI>\.claude\plans -ErrorAction SilentlyContinue

# Dev HTML harnesses (frequently leftover from dev sessions)
Get-ChildItem <SENA_AI>\sena-ai -Filter "*.html" -Recurse | Select-Object FullName

# Log dumps + accidentally-created files
Get-ChildItem <SENA_AI> -Filter "*.txt" | Select-Object Name
Get-Item <SENA_AI>\nul -ErrorAction SilentlyContinue  # Windows accident
```

### AskUserQuestion bundling rule

For ambiguous DOC files (never code), bundle into a single `AskUserQuestion` call:

- Max 4 questions per call
- Each question: 3 options — `Delete now (Recommended)` | `Keep` | `Tell me where used`
- If user picks `Tell me where used` → spawn a Grep, report file:line callers, then re-ask in the next round
- If user picks `Keep` → log to `decisions.md` with rationale so next cycle skips re-asking

**Example AskUserQuestion shape** (do NOT include code files):

```
Q1: AGENTS.md at repo root — content duplicates CLAUDE.md + sena-rules.md; references stale "0/9 phases" — delete?
Q2: FLUTTER_DEV_HANDOFF.md — superseded by flutterhandoffdev.md (canonical post-YYYY-MM-DD) — delete?
Q3: .claude/plans/<plan-file>.md — fully executed + committed — delete?
Q4: sena-ai/services/onboarding/test_harness.html — dev-only browser harness — delete?
```

### Files that are NEVER candidates for deletion

- Anything inside `archive/`, `.venv/`, `.vscode/`, `ndis_markdown_docs/`
- SSH keys at repo root (`github`, `github.pub`, `*.pem`)
- `flutterhandoffdev.md` (Flutter team's contract)
- `CLAUDE.md`, `CLAUDE.local.md`, `SESSION_START.md`, `TASKS.md`, `ARCHIVE.md`
- Any `.env*` file
- `.gitignore`, `pyproject.toml`, `docker-compose*.yml`, `Dockerfile`

---

## §9 — Things that go sideways (and how to recover)

| Symptom | Cause | Recovery |
|---------|-------|----------|
| Agent file edit fails with "File has not been read" | The runtime tracks reads per-path; rename changed the path | Re-read at the new path, then retry the Edit |
| Routing table has rows pointing to non-existent agents | An agent was deleted but the table wasn't swept | Update Phase 5 — remove the row OR add the missing agent |
| Two agents have the same `name:` frontmatter | Botched copy/rename | Phase 3 catches this — rename one |
| `lessons.md` grows past 200 lines | Working as designed; long-term memory | Don't trim — just keep appending. Patterns must remain greppable. |
| CLAUDE.md exceeds 600 lines | Bloat creep; loaded every session = token-expensive | Audit each section for whether it's mandatory; move detail to `.claude/rules/*.md` and cross-link |
| Hooks-state flags missing mid-cycle | Session reset cleared them | Re-earn (invoke skill, call Context7) — see CLAUDE.local.md "Hook-state quick check" |

---

## §12 — `rules/external-tools.md` template

If missing, create at `.claude/rules/external-tools.md`. Trigger-phrase autoload — loads on demand when gstack / browser / specify / hivemind are invoked.

```markdown
---
description: gstack skill pack + companion CLIs (agent-browser, specify, hivemind) — load when user invokes /qa, /browse, /design-*, /investigate, /office-hours, /retro, /canary, /plan-ceo-review, or asks about browser automation / spec-kit / hivemind. NOT auto-loaded; main thread reads on demand.
trigger_phrases:
  - "gstack"
  - "agent-browser"
  - "/browse"
  - "/qa"
  - "/design-"
  - "/investigate"
  - "/office-hours"
  - "/retro"
  - "/canary"
  - "spec-kit"
  - "specify init"
  - "hivemind"
---

# External Tools (user-global)

## gstack
Installed at `~/.claude/skills/gstack`. 47 sub-skills + native CLIs (`browse`, `design`, `pdf`). SENA agents take precedence over gstack for tenant-isolation-critical code (don't use gstack `/review` or `/ship` for SENA paths).

## Companion CLIs
- `agent-browser` (npm global) — Chromium-only browser automation. No Firefox.
- `specify` (uv tool) — GitHub spec-kit CLI.
- `hivemind` (npm global) — Deeplake shared-brain. HELD pending NDIS APP 8/11 data-residency decision; do NOT run `hivemind install` without explicit user override.
```

---

## §13 — `rules/add-component.md` template

If missing, create at `.claude/rules/add-component.md`. Trigger-phrase autoload.

```markdown
---
description: MANDATORY protocol when user says "I am adding X" (new directory, service, file, or external resource). Triggers a documentation sweep BEFORE any code work begins.
trigger_phrases:
  - "I am adding"
  - "I'm adding"
  - "adding a new service"
  - "adding a new directory"
  - "new dependency"
  - "new external resource"
---

# Adding New Project Components (MANDATORY PROTOCOL)

When user says "I am adding X", update ALL before any code work:

| File | What to update |
|------|---------------|
| `CLAUDE.md` | Add to file tree + dedicated section |
| `.claude/SESSION_START.md` | Add to READ-IF-RELEVANT table |
| `.claude/tasks/TASKS.md` | Update blocked tasks now unblocked |
| `memory/MEMORY.md` | Add index entry |
| Create `memory/project_<name>.md` | Describe component + usage |

Do NOT start other work until the sweep is complete.
```

---

## §14 — `tasks/followups.md` template

If missing, create at `.claude/tasks/followups.md` with header only.

```markdown
---
title: Follow-ups — Out-of-Scope Observations
updated: YYYY-MM-DD
purpose: Catch-all for issues discovered while working on something else. Drop one-line observations here; the principal-engineer "minimal blast radius" rule routes them here instead of polluting the current diff. Triage on next planner run.
---

# Follow-ups

Format: `[YYYY-MM-DD] [discovered-during] — [observation] — [next action]`

## Open

*(none yet)*

## Triaged (moved to TASKS.md or ARCHIVE.md)

*(empty — triage moves entries to one of those files with the date)*
```

---

## §15 — `plans/README.md` template

If missing, create at `.claude/plans/README.md`. Documents the empty-by-design lifecycle.

```markdown
# plans/

Empty by design. Plans are feature-scoped and ship with the feature.

## Lifecycle

1. **During a feature:** `plans/<feature-slug>.md`
2. **When feature ships:** `sena-harness-upgrade` moves the plan reference into `tasks/ARCHIVE.md` under the feature's closed entry and deletes the plan file.
3. **Between features:** empty.

Non-empty plans/ between features = in-flight work. Empty = clean slate.

## When to add

- New feature touching 3+ files
- Cross-service refactor
- Work where the executor needs a DAG

## When NOT to add

- Single-line bug fixes
- Typo / formatting
- Status updates (those go in `TASKS.md`)
```

---

## §16 — Slash command templates

If any of these files are missing under `.claude/commands/`, recreate from below. All use `description:` + `allowed-tools:` frontmatter.

Commands split into two groups:
- **Workflow commands (5)** — chain multiple agents or run the harness skill. Templates immediately below.
- **Direct-agent shortcuts (14)** — one per agent, route via `Agent` tool. Generic template at §16b; per-agent purpose lines at §16c.

### §16a — Workflow command templates

### `sena-harness-upgrade.md`

```markdown
---
description: Run the SENA .claude/ harness upgrade and hygiene routine end-to-end. Invokes the sena-harness-upgrade skill.
allowed-tools: Skill, Read, Edit, Write, Bash, PowerShell, Glob, Grep, mcp__plugin_context-mode_context-mode__ctx_batch_execute
---

Invoke the `sena-harness-upgrade` skill via the Skill tool. Pass through `$ARGUMENTS` (e.g. "audit-only", feature name).
```

### `sena-plan.md`

```markdown
---
description: Route user's requirement to @agent-sena-planner for architectural plan + subtask DAG + NDIS/tenant analysis.
allowed-tools: Agent
---

Route to `sena-planner` agent (Agent tool, subagent_type: sena-planner). Planner does NOT write code — returns plan with files-to-touch, deps to add, NDIS/tenant implications, rollback plan. After return, ask user whether to proceed to `@agent-sena-task-breaker`.

User's requirement: $ARGUMENTS
```

### `sena-feature-ship.md`

```markdown
---
description: Finalize a shipped SENA feature. Runs sena-harness-upgrade in feature-ship mode.
allowed-tools: Skill, Read, Edit, Write, Bash, PowerShell, Glob, Grep
---

Invoke `sena-harness-upgrade` skill in feature-ship mode for the named feature ($ARGUMENTS).
If no feature name → ask user which feature is shipping.
```

### `sena-audit.md`

```markdown
---
description: Read-only audit of .claude/ — verifies agent namespace, PE Mode coverage, Orchestration Protocols, routing, lessons. No archive, no reset.
allowed-tools: Skill, Read, Glob, Grep, mcp__plugin_context-mode_context-mode__ctx_batch_execute
---

Invoke `sena-harness-upgrade` in audit-only mode. Walk Phases 0, 2, 3, 4, 4.5, 5, 5.5, 6, 7 (skip Phase 1 archive). Output: ✅/⚠️/❌ per check, fix inline only for cleaner/optimization-style issues, surface blockers.
```

### `sena-status.md`

```markdown
---
description: Compact SENA project status — active tasks, recent commits, hook flag state, followups, lessons, CLAUDE.md size.
allowed-tools: Read, Bash, PowerShell, Glob, Grep
---

Print 7-line snapshot: active tasks count, latest commit, hook flags set, agent count (target 14), open followups count, lessons count, CLAUDE.md line count. Final line: `OK` or `Warning: <one-liner>`.
```

### `sena-engineering-collaborator.md` and `solve.md`

These are pre-existing — do NOT auto-recreate. If missing, ask the user before regenerating (they may have intentional content).

### §16b — Direct-agent shortcut template (generic)

Every direct shortcut follows the same shape — `description:` + `allowed-tools: Agent` + a 1-2 paragraph body that routes via the Agent tool with `subagent_type: sena-<name>`. Copy this skeleton and fill in the per-agent details from §16c:

```markdown
---
description: Direct invocation of @agent-sena-<NAME> — <one-line purpose from §16c>. <Fix-mode marker if any: "FLAGS ONLY", "FIXES inline", "Does NOT modify code", "NEVER pushes".>
allowed-tools: Agent
---

Route <input description> to `sena-<NAME>` (Agent tool, subagent_type: sena-<NAME>). <2-3 sentences describing what the agent returns, what it does NOT do, and which agent runs next in the pipeline if applicable.>

<Optional: SENA-specific signals — auto-block patterns, auto-flags, allowed inputs.>

User's args: $ARGUMENTS
```

### §16c — Per-agent purpose lines (one-liners for the description field)

| File | Agent role | Fix mode |
|------|-----------|----------|
| `sena-planner.md` | architectural plan + subtask DAG + NDIS/tenant analysis | does NOT write code |
| `sena-task-breaker.md` | converts planner output into atomic JSON coding tasks | does NOT write code |
| `sena-implementer.md` | writes production-ready async Python for ONE scoped subtask | does NOT review or commit |
| `sena-business-reviewer.md` | NDIS / FormState / validator / advance_step domain review | FLAGS ONLY — hand-back to bug-fixer |
| `sena-security-reviewer.md` | tenant-isolation / secrets / OWASP / Gemini-bridge audit | FLAGS ONLY — Critical halts workflow |
| `sena-bug-fixer.md` | surgical one-for-one patches from reviewer FAIL findings | applies minimum-blast-radius patch |
| `sena-optimization-reviewer.md` | async / Redis pipelining / memory hot-path refactor | FIXES inline (scoped, behaviour-preserving) |
| `sena-cleaner.md` | final lint + dead-code + debug-print gate before commit | FIXES inline (ruff/mypy) |
| `sena-git-committer.md` | generates Conventional Commit + git add command | NEVER pushes |
| `sena-log-analyzer.md` | isolates root frame from crash log / stack trace / pytest failure | does NOT fix — hands to bug-fixer |
| `sena-researcher.md` | current third-party library/API/framework docs research | does NOT modify code |
| `sena-doc-writer.md` | writes/updates CLAUDE.md / TASKS.md / handoff docs grounded in file:line | does NOT modify source code |
| `sena-code-reviewer.md` | ad-hoc external diff or non-SENA-path PR review (SHIP/FIX/BLOCK) | does NOT use on SENA paths |
| `sena-engineering-collaborator.md` | non-trivial multi-file / multi-subsystem / contracts-first investigation | plans + verifies before writing |

**Important pipeline-position guidance** (preserve in each shim body):
- `sena-planner` → `sena-task-breaker` → `sena-implementer` → `sena-business-reviewer` + `sena-security-reviewer` → (FAIL? `sena-bug-fixer`) → `sena-optimization-reviewer` → `sena-cleaner` → `sena-git-committer`.
- `sena-log-analyzer` runs BEFORE `sena-bug-fixer` for any crash/trace.
- `sena-researcher` runs BEFORE `sena-implementer` when a new library is in play.

When recreating a shim, the body should reference the next agent in the pipeline so users discover the workflow without reading the full pipeline diagram in `sena-rules.md`.

---

## §17 — `rules/service-onboarding.md` template

Path-scoped autoload for `sena-ai/services/onboarding/**`. Contains: layer-by-layer table (API/Services/Repositories/Models), key routes, WS server→client event table (9 events), design decisions (one-WS-per-step, Redis-only state, app backend is DB of record), run command, env vars with `SENA_AI_` prefix.

Full content lives in `.claude/rules/service-onboarding.md`. If recreating, copy frontmatter:

```yaml
---
paths:
  - "sena-ai/services/onboarding/**/*.py"
  - "sena-ai/services/onboarding/**/*.md"
  - "sena-ai/services/onboarding/Dockerfile"
  - "sena-ai/services/onboarding/pyproject.toml"
---
```

Then the body covers: layer map (15 rows: API ws_routes, services/gemini_live, prompt_builder, tools, screen_context, grounding, resumption, webhook, cross_screen_context, coverage, field_apply, validators; repos state_repo + user_context_repo; models schema_spec + form_state + session_bootstrap + cross_screen_summary; fixtures schema_*.json), key routes (4), WS events table (9 events), design decisions (4 bullets), run command, env vars.

---

## §18 — `rules/service-voice.md` template

Path-scoped autoload for `sena-ai/services/voice/**`.

```yaml
---
paths:
  - "sena-ai/services/voice/**/*.py"
  - "sena-ai/services/voice/pyproject.toml"
  - "sena-ai/services/voice/Dockerfile"
---
```

Body covers: layer map (API/Services/Repositories/Models/Prompts/Config), key API routes (7), external deps (Bedrock + SNS + LiveKit + Redis + 2x Postgres), run command, env vars, LLM split awareness table (Flow B Bedrock vs personal-details Gemini Live).

---

## §19 — `rules/service-case-review.md` template

Path-scoped autoload for `sena-ai/services/case_review/**`.

```yaml
---
paths:
  - "sena-ai/services/case_review/**/*.py"
  - "sena-ai/services/case_review/pyproject.toml"
  - "sena-ai/services/case_review/migrations/**/*.py"
---
```

Body covers: layer map (API + 4 ORM tables RollingSummary/ReviewSession/IncidentDraft/ReviewAuditLog), 6 REST routes (all 501 Phase A), MANDATORY non-negotiables (tenant_id + RLS + audit log + GEMINI_REGION=australia-southeast1 data residency), run + alembic, env vars. Currently SHELVED at Phase C.

---

## §20 — `rules/gemini.md` template

Path-scoped autoload for any Gemini-touching file. **Writing this file is hook-gated** — invoke `Skill: gemini-live-api-dev` first to set `skills-gemini.flag`.

```yaml
---
paths:
  - "**/gemini*.py"
  - "**/demo_live*.py"
  - "**/demo_live*.html"
  - "sena-ai/services/onboarding/**/*.py"
  - "sena-ai/services/voice/src/voice/services/gemini*.py"
  - "sena-ai/services/case_review/src/case_review/**/gemini*.py"
---
```

Body covers: pre-coding prerequisites (skill + Context7), current models (`gemini-3.1-flash-live-preview` Live + `gemini-3-flash-preview` Flash, deprecated list), current API patterns (`send_realtime_input` for audio/text/video/audio_stream_end), forbidden patterns (old `session.send(input=...)`, `LiveClientRealtimeInput`, `send_client_content` for new messages, `media=` key), receive loop (per-turn `while True`, multi-part event handling), capability limits (no proactive audio, 15-min audio-only, 2-min audio+video, no async function calling), audio formats (16kHz in / 24kHz out), critical forbidden pattern (NEVER gate mic on `_agent_speaking` — silent VAD death), Flutter echo fix (mute during agent speech), best practices (8 items).

---

## §21 — `rules/build-and-run.md` template

Path-scoped autoload for Python project config / Docker / CI files.

```yaml
---
paths:
  - "sena-ai/Makefile"
  - "sena-ai/pyproject.toml"
  - "sena-ai/docker-compose.yml"
  - "sena-ai/docker-compose.deploy.yml"
  - "sena-ai/services/*/pyproject.toml"
  - "sena-ai/services/*/Dockerfile"
  - "sena-ai/.pre-commit-config.yaml"
---
```

Body covers: setup (per-service `pip install -e "services/<svc>[dev]"`), infrastructure (`docker-compose up -d`), run commands per service, pytest commands (always explicit path), ruff + mypy + pre-commit, Windows/PowerShell variant (no `&&`, use `;` + `$?`), health-check URL table.

---

## §22 — `rules/deployment.md` template

Path-scoped autoload for deployment artifacts.

```yaml
---
paths:
  - "sena-ai/Dockerfile"
  - "sena-ai/docker-compose.deploy.yml"
  - "sena-ai/.env.deploy*"
  - "sena-ai/DEPLOY_EC2_CHECKLIST.md"
  - "sena-ai/services/onboarding/Dockerfile"
---
```

Body covers: abbreviated EC2 flow (git clone → cp .env.deploy → docker compose up → curl health), deploy compose (sena-onboarding + redis containers), key differences from local dev (no local Postgres, Nginx reverse-proxy expected, docker network alias), demo-grade shortcuts to fix (no TLS, no secrets manager, single-node Redis), current state (voice + onboarding on EC2 since 2026-05-14, case_review not deployed).

---

## §23 — `rules/demo-stack.md` template

Path-scoped autoload for `demo_live*` files.

```yaml
---
paths:
  - "sena-ai/demo_live_server.py"
  - "sena-ai/demo_client.html"
---
```

Body covers: file pair (demo_live_server.py + demo_client.html), run command, env required, hook gating note (same gate as production Gemini code — must invoke skill + Context7 first).

---

## Notes on §17-§23 regeneration

When recreating any of these from scratch:

1. The `paths:` glob is the most important field — controls when Claude Code autoloads the rule.
2. Body content can be regenerated from CLAUDE.md sections OR from previous git history (`git log --all --source -- .claude/rules/<file>.md`).
3. **Do NOT duplicate this content into CLAUDE.md** — defeats the autoload purpose and bloats every session's token cost.
4. **Test the autoload:** open a file matching the glob → confirm the rule's contents appear in Claude's working context.
