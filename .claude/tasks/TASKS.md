---
title: Persistent Task List
updated: 2026-05-25
---

> **Clean slate — 2026-05-14.** Voice assistance (feature A) shipped to EC2; Case Review
> (feature B) shelved at Phase C. Full history is in `.claude/tasks/ARCHIVE.md`. The next
> feature's tasks go below; do NOT carry voice/case-review context into a new feature's
> planning unless the work is directly building on shipped infrastructure.
>
> **New session: read `.claude/SESSION_START.md` FIRST.**

# SENA Task List

Session-persistent todos. Survives `/compact` and session resets. Claude reads this file at session start and updates it as work progresses.

**Status legend:** `pending` | `in_progress` | `completed` | `blocked`

---

## Active

### #2 — Option D state-channel fix for Gemini hallucination (2026-05-25)
- **Status:** server-side-shipped-pending-flutter-commit
- **Priority:** P0 (production hallucination firefight)
- **Pipeline:** planner ✓ · implementer ✓ · business-reviewer ✓ · security-reviewer ✓ · code-reviewer ✓ · bug-fixer ✓ (5 patches) · optimization-reviewer ✓ · doc-writer ✓ · cleaner ✓ (ruff/format/mypy clean; 19 pre-existing gemini_live.py mypy errors unchanged) · **git-committer pending user ack**
- **Server-side files (committed branch `voice-assistance-optimization`):**
  - `services/onboarding/src/onboarding/services/tools.py` — `get_current_state` in `_KNOWN_TOOLS` + `FUNCTION_DECLS` (7 tools total)
  - `services/onboarding/src/onboarding/services/prompt_builder.py` — `_bootstrap_state_json` helper; bootstrap shrunk to participant+step+next_target+bootstrap_mode when flag on
  - `services/onboarding/src/onboarding/services/gemini_live.py` — `SlidingWindow(target_tokens=4000)` Layer 3 compression
  - `services/onboarding/src/onboarding/core/settings.py` — `onboarding_tool_state_channel: bool = True`
  - `services/onboarding/src/onboarding/prompts/onboarding_system.md` — §1 rewrite + §1a FORBIDDEN PHRASES (9 bullets incl. NDIS) + §1b staleness + §6 7-tools + §8 demoted
  - `services/onboarding/tests/test_tools.py` — coverage extended for `get_current_state`
- **Flutter handoff:** `sena-ai/services/onboarding/FLUTTER_HANDOFF_OPTION_D.md` — full contract for sena-mobile team (every tool_response must carry fresh `state`; new `get_current_state` handler; UI-driven update path)
- **Mobile-side pending:** sena-mobile team must implement matching half. Until they do, the fix is incomplete and Gemini has no authoritative view of FormState. Feature flag `SENA_AI_ONBOARDING_TOOL_STATE_CHANNEL=false` is the hot rollback.
- **Followups (in `.claude/tasks/followups.md`):** rollback-asymmetry (prompt rules stay Option-D-shaped when flag=False — intentional per spec §7.11)
- **Reference:** `.claude/plans/per-screen-session-model/ISSUE_AND_SOLUTION.md` (full spec) · `.claude/plans/per-screen-session-model/OPTION_D_EXPLAINED.html` (storyboard) · `.claude/plans/per-screen-session-model/STATE_REFRESH_OPTIONS.html` (option comparison)

### #1 — Per-screen Live session model (2026-05-22)
- **Status:** plan-approved-deferred-to-phase-2 (Option D shipping first as P0 firefight)
- **Priority:** P1
- **Plan:** `.claude/plans/per-screen-session-model/PLAN.md`
- **Goal:** Replace one-Live-session-per-step with one-session-per-screen + parallel pre-warm. Fixes Gemini Live's poor adherence to the ~800-line monolithic system prompt.
- **Scope:** `services/onboarding/` only. 15 subtasks (S1–S15). Feature-flagged via `SENA_AI_ONBOARDING_PER_SCREEN_SESSIONS` (default false).
- **Locked decisions:** per-screen boundary (Flutter-driven `screen_changed`) · compact summary cross-section ctx · 2s parallel pre-warm · system-prompt-only pre-warm payload (billing) · single WS holder during overlap.
- **Researcher findings (2026-05-22):** parallel Live sessions SUPPORTED at all tiers (free 3 / T1 50 / T2 1000). Per-project quota. Context tokens re-billed per turn → minimal pre-warm payload required.
- **Files touched:** `gemini_live.py`, `ws_routes.py`, `prompt_builder.py`, `cross_screen_context.py`, `schema_spec.py`, `core/settings.py`, plus new tests `test_per_screen_integration.py`.
- **Open questions (block S9 + S15 commit):**
  1. Does Flutter commit to emitting `screen_changing` advisory? (sena-mobile team)
  2. Are screens 1:1 with `SectionSpec`, or are there multi-section screens? (schema team)
  3. `screen_state` vs `screen_changed` ordering when both arrive in same WS turn.
- **Next step:** route to `@agent-sena-task-breaker` to convert S1–S15 into atomic JSON tasks for `@agent-sena-implementer`.
- **Blockers:** none for S1–S8, S10–S14. S9 + parts of S15 wait on open question #1.



Add new feature tasks below. Each entry:
- Heading: `### #<id> — <one-line description> (<YYYY-MM-DD>)`
- Bullets: status, priority, scope, files touched, tests, blockers
- Move to `ARCHIVE.md` when the feature is shipped/closed

---

## Backlog (deferred / blocked / decisions pending)

### Demo / dev-only code (decision pending)
- `sena-ai/demo_live_server.py` + `sena-ai/demo_client.html` — standalone Gemini Live demo. Files retained per 2026-05-14 decision; no longer referenced from SESSION_START.md. Delete if and only if you have a replacement debugging path for Gemini Live regressions.
- `sena-ai/services/onboarding/src/onboarding/main.py:15` + `40-59` — harness routes (`/harness`, `/harness/fixtures/{step_id}`). `test_harness.html` was deleted 2026-05-14; routes now return 404. Listed in `CODE_FILES_TO_REVIEW.md` — remove if no longer used.

### Infrastructure-blocked
- **RAG over NDIS documents** — pgvector + structure-aware chunking. NDIS Commission PDFs already at `ndis_wiki/sources/` (markdown). Ready to plan when prioritised.
- **OCR service implementation** — BLOCKED on client document samples.
- **JWT auth + RLS policies** — BLOCKED on client JWT claims structure.
- **AU data residency sign-off for Gemini Live** — BLOCKED on legal/compliance review (production prerequisite).
- **Production voice service migration** — `gemini_live_service.py` in `services/voice/` still uses OLD API. Migration to `send_realtime_input` pattern (per `feedback_gemini_live_patterns.md`) deferred until Flow B work resumes.
- **Flow B (case note dictation) LiveKit Agent pattern** — deferred indefinitely; no active roadmap.
- **Context window compression for >15 min sessions** — deferred; current sessions are short enough not to hit limits.
- **Ephemeral token auth for browser-side** — deferred.

---

## Conventions

- Update this file whenever a task status changes or a new task is added.
- Lead each task with ID, status, and 1-line summary.
- Include file paths, constraints, and acceptance criteria for P0/P1 items.
- When a task ships, move the entry to `ARCHIVE.md` rather than deleting it. Keep `Active` clean for the next feature.
- When backlog grows stale, prune to a separate archive file.
