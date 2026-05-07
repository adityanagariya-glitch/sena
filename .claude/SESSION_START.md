---
title: Session Start Guide
updated: 2026-05-07
purpose: Single entry-point doc. Future-Claude reads this FIRST in a new session to land in same state.
---

# Read-order for resuming SENA work

Read these files IN ORDER at the start of any new session. Stop when you have enough context for the user's current request.

## 1. MUST-READ (always)

| # | File | Why |
|---|------|-----|
| 1 | `CLAUDE.md` (project root) | Hard rules, architecture, Gemini API rules, cleanup rule, demo stack |
| 2 | `.claude/SESSION_START.md` (this file) | Tells you what to read next |
| 3 | `.claude/tasks/TASKS.md` | Current task state, active/completed/backlog |
| 4 | `.claude/issues-solved/INDEX.md` | Grep-first symptom→fix table. Check BEFORE debugging anything. |
| 5 | `.planning/ONBOARDING_VOICE_API_PLAN.md` | Historical build plan — onboarding voice API, phases A–F (all shipped 2026-04-29). Read for architecture context, NOT for next-step guidance. |
| 6 | `~/.claude/projects/C--Users-Admin-Downloads-SENA/memory/MEMORY.md` | Memory index — points to all user/project/feedback memories |

## 2. READ-IF-RELEVANT (task-dependent)

| Task area | Read |
|-----------|------|
| Voice demo / Gemini Live bugs | `memory/feedback_gemini_live_patterns.md`, `memory/project_voice_demo_working.md` |
| What's left to build (voice) | `.planning/GEMINI_LIVE_NATIVE_SCOPE.md` (Gemini-native scope reference) — for next-step state read TASKS.md |
| Onboarding validation / sequencing / schema-drift | `.planning/PRD-validation-sequencing-discovery.md` + `.planning/VALIDATION-CROSS-CHECK-2026-05-07.md` + `.claude/client_onboarding_validations.md` (Flutter-canonical) |
| Case Note Review service (task #10) | `.planning/CASE_NOTE_REVIEW_PLAN.md` — phases A–G, subagent policy, blockers |
| Onboarding cross-screen context | `.planning/PRD-cross-screen-context.md` + `.claude/plans/no-graceful-muffin.md` — per-(tenant_id, participant_id) shared bucket, lossless compression, isolation guard |
| Architecture / code structure | `graphify-out/GRAPH_REPORT.md` |
| NDIS domain / compliance | specific files in `ndis_markdown_docs/` (never the whole folder) |

## 3. DO-NOT-READ

- `/archive/`, `.venv/`, `.vscode/` — token waste, ignored per CLAUDE.md
- `ndis_markdown_docs/` (whole folder) — massive token cost. Read only a specific file when an NDIS compliance question requires it.

---

## ✅ DONE: validation awareness + sequencing + schema-drift discovery (2026-05-07)

Task #13 — server-side validators authoritative; `pending_validation_errors` blocks `advance_step`; `validation_failed`/`validation_cleared` client→server frames wired in `gemini_live._handle_control`; 4 new server→client events shipped (`repeatable_section_entered/exited`, `field_skipped_warning` with `missing_fields[]` enumerating exactly which required fields are empty, `schema_drift_detected` with `kind: unknown_field|unknown_section`). `FLUTTER_DEV_HANDOFF.md` brought into full sync with backend reality. Tests 78/78 (excluding 2 pre-existing unrelated import errors). **PRD:** `.planning/PRD-validation-sequencing-discovery.md`. **Cross-check:** `.planning/VALIDATION-CROSS-CHECK-2026-05-07.md`. **Validator catalogue:** `.claude/client_onboarding_validations.md` (Flutter-canonical). See TASKS.md #13 for full file list.

## ✅ DONE: cross-screen shared context (2026-05-06)

Task #12 — per-(tenant_id, participant_id) shared bucket of step summaries (`UserContextRepo`, Redis Hash + Set, 7-day TTL); lossless compress/decompress; isolation guard via `state_repo.assert_session_owner`; rendered into prompt as EARLIER IN THIS ONBOARDING block (between `[LIVE_STATE_JSON]` and SCHEMA). Single feature flag `SENA_AI_ONBOARDING_CROSS_SCREEN_CONTEXT_ENABLED` (default `true`) for rollback. Tests 89/89. **PRD:** `.planning/PRD-cross-screen-context.md`. **Plan:** `.claude/plans/no-graceful-muffin.md` (isolation repair history). See TASKS.md #12 for full file list.

## ✅ DONE: onboarding 7-rules + voice protocols (2026-05-02)

Task #11 — implemented all 7 voice-onboarding behavioural rules plus interrupt-recovery, silence-watchdog two-step, and Gemini context_window_compression. Tests 78/78. **Plan artifact:** `~/.claude/plans/cozy-waddling-river.md`. **Flutter delta:** Issues 7–9 in `FLUTTER_VOICE_INTEGRATION_FIXES.md`. See TASKS.md #11 for full file list.

**Key entry points for resuming:**
- `models/session_bootstrap.py` — Rule 1/2 envelope; rendered into prompt as `[LIVE_STATE_JSON]`
- `prompts/onboarding_system.md` — fully rewritten with all 7 rules and voice protocols
- `services/screen_context.py::ScreenStateV2.field_errors` — Rule 7 reason hints
- `services/tools.py` — `update_field.values` array parameter (Rule 4); `_readonly_paths` set on dispatcher (Rule 3)

## ✅ DONE: onboarding v2 implemented (2026-04-29)

All 14 files complete. See TASKS.md #9 for full file list. **Next task: Case Note Review #10 Phase D** (`/review` endpoint — risks + restrictive practices + anomalies). Read `.planning/CASE_NOTE_REVIEW_PLAN.md` to resume.

### v2 summary (for reference)
- `screen_state_v2` WS message + `ScreenStateV2` model + `from_v1()` adapter
- `field_apply` envelope drives Flutter GetX controllers directly
- `add_repeatable_row` Gemini tool for growing repeatable sections
- `coverage.py` + `field_apply.py` — pure enforcement modules
- `voice_coverage` / `voice_repeatable_sections` on `StepSchema` (fixtures updated)
- `bio` → `about_me` in `schema_personal_information.json`
- `prompt_version:"v2"` + `coverage` array in ready envelope

---

## Current state (canonical pointer)

**TASKS.md is the authoritative tracker.** It's hook-bumped on every edit and survives `/compact`. Read it for: active task, completed-task trail, blocked items, and next-step guidance. Do not duplicate state here — old "Current state snapshot" blocks rotted between sessions.

**Active services & ports:**
- `sena-ai/services/onboarding/` — port 8083, Redis-only (FormState, transcript, WS lock, resumption handles, cross-screen bucket)
- `sena-ai/services/case_review/` — port 8084, ai-db (pgvector); 4 tables with RLS on tenant_id
- `sena-ai/demo_live_server.py` — port 8082, standalone Gemini Live demo

**How to run:**
```bash
# Onboarding
cd sena-ai/services/onboarding && pip install -e . && uvicorn src.onboarding.main:create_app --factory --reload --port 8083

# Case Review
cd sena-ai/services/case_review && pip install -e . && uvicorn src.case_review.main:create_app --factory --reload --port 8084

# Demo
cd sena-ai && uvicorn demo_live_server:app --reload --port 8082
```

**Known blocked (move to TASKS.md if these change):**
- Case Review Phase F (submit gate) — other engineer's register schema
- RAG (NDIS docs) — client sample docs
- Multi-tenant auth / RLS — client JWT claims structure
- OCR service — document samples
- AU data residency sign-off for Gemini Live — production blocker

---

## How to verify state on session start

Run these to confirm nothing rotted since 2026-04-21:

```bash
# 1. Demo still runs?
cd sena-ai && uvicorn demo_live_server:app --reload --port 8082
# Open http://localhost:8082 → Start → speak → expect reply

# 2. Git clean?
git status
git log --oneline -10

# 3. Env file present?
ls sena-ai/.env  # must contain SENA_AI_GEMINI_API_KEY + SENA_AI_GEMINI_LIVE_MODEL_ID=gemini-3.1-flash-live-preview
```

If demo breaks: first suspect `session.receive()` retry loop (`while True: ... continue`) and `realtime_input_config` presence. See `feedback_gemini_live_patterns.md`.

---

## Hook-enforced maintenance (how these docs stay live)

Three hooks in `.claude/settings.json` keep this system deterministic:

| Hook | Script | What it does |
|------|--------|--------------|
| `SessionStart` | `.claude/hooks/session-start.sh` | Injects this read-order as additionalContext on every new session — Claude sees the protocol before the first prompt |
| `Stop` | `.claude/hooks/stop.sh` | Rebuilds graphify graph + emits reminder to verify `TASKS.md` at every session boundary (including /clear, /compact, resume) |
| `PostToolUse` (Write\|Edit) | `.claude/hooks/bump-updated.sh` | Auto-bumps `updated: YYYY-MM-DD` frontmatter on SESSION_START.md, TASKS.md, MEMORY.md, CLAUDE.md whenever Claude edits them |

**You never need to manually update `updated:` fields.** The hook does it. If a file lacks frontmatter (e.g., CLAUDE.md), the hook no-ops safely.

If a hook seems broken: check `/hooks` menu, or run `bash .claude/hooks/<name>.sh` directly with a fake stdin payload to diagnose.

---

## Rules you MUST reload every session

From `CLAUDE.md`:
- Gemini code → invoke `Skill: gemini-live-api-dev` BEFORE editing
- Use `send_realtime_input(audio=Blob(...))` — NOT `session.send(LiveClientRealtimeInput(...))`
- Current model: `gemini-3.1-flash-live-preview`
- Do NOT delete "dead code" without grepping full codebase first
- NEVER read `/archive`, `.venv`, `.vscode`

From memory (`feedback_gemini_live_patterns.md`):
- `session.receive()` returns per-turn — wrap in `while True` with `continue`
- Multi-turn REQUIRES `realtime_input_config` with explicit VAD
- Use `await b2g`, not `asyncio.wait(FIRST_COMPLETED)`
- Single AudioContext on browser for mic+playback
- Manual 24kHz→native upsample before `createBuffer`
- **NEVER gate mic audio on `_agent_speaking` flag** — causes VAD to die after 2-4 turns. Send audio unconditionally; Gemini's native VAD + `START_OF_ACTIVITY_INTERRUPTS` handles barge-in.
- Use `START_SENSITIVITY_LOW` — HIGH fires on ambient noise and exhausts VAD budget
