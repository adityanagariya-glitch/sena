---
title: Persistent Task List
updated: 2026-05-07
---

> Last session end-state (2026-05-11): Task #15 state-sync desync repair **COMPLETE**. 4 frontend-reported bugs fixed surgically (service-address auto-copy, cross-screen flag default, emergency-contact update loop, JSON-as-Truth prompt rule). 198/198 tests pass (+6 regression). Stale `FLUTTER_VOICE_INTEGRATION_FIXES.md` removed; `FLUTTER_DEV_HANDOFF.md` extended with Issue #28 contract.
> **New session: read `.claude/SESSION_START.md` FIRST.**

# SENA Task List

Session-persistent todos. Survives `/compact` and session resets. Claude reads this file at session start and updates it as work progresses.

**Status legend:** `pending` | `in_progress` | `completed` | `blocked`

---

## Active

### #16 — Voice assistant UX bugs (VAD, validation, routines, amnesia) (2026-05-12)
- **Status:** completed (2026-05-12) — commit db2ee7c
- **Priority:** P0 (user-reported — blocks voice rollout sign-off)
- **Sub-fixes:**
  - V1 (VAD patience): `silence_duration_ms 1000 → 3000` in `gemini_live.py` — **DONE**
  - V2 (Email domain length): RFC 5321 per-label ≤63 + total domain ≤253 in `_email()` — **DONE**
  - V3 (Enum validation): `validate_field()` extended with `field_spec`; `multi_enum` checked against options; `enum_invalid` with `allowed_values`; Rules 13+14 in prompt — **DONE**
  - V4 (Mandatory routines): `section_min_unmet()` helper; fixture `min` 0→1; `advance_step` gate; Rule 9 rewritten + Rules 13/14 added — **DONE**
  - V5 (Session name amnesia): Rule 2 + address block updated with `prior_pages` fallback — **DONE**
- **Tests:** 198 → 238 (+40 new). All green.

### #15 — State-sync desync repair (2026-05-11)
- **Status:** completed (2026-05-11)
- **Priority:** P0 (user-reported regressions blocking voice rollout)
- **Trigger:** User report — 4 production-shape bugs after Task #14 shipped:
  1. Service-address auto-copy broken (schema declared `copy_from_if_flagged: home_address` but no code read it)
  2. Resumed sessions re-asked for name (cross-screen context flag default OFF)
  3. Emergency-contact updates dropped silently (`cross_section_blocked` after focus pinned to non-repeatable section)
  4. Double-prompted email even after the value was captured (agent not consulting `[LIVE_STATE_JSON]` before asking)
- **Root cause pattern:** State-sync desync — Gemini agent + Flutter UI built parallel views of "what's filled" instead of treating the server-authored JSON state as the single source of truth.
- **Fixes shipped:**
  - `core/settings.py:69` — `onboarding_cross_screen_context_enabled` default `False` → `True`. Bucket key (`{tenant_id}:{participant_id}`) makes isolation structural, not flag-dependent.
  - `services/tools.py` — new `_apply_copy_mirroring()` helper invoked after every successful `set_field`. Materialises schema's `copy_from_if_flagged` declaration. Idempotent; emits per-field `field_updated` events with new keys `source: "app"` and `auto_copied_from: <section>`.
  - `services/tools.py` `_update_field` — implicit-enter for repeatable targets. Auto-pins `focused_section` + `focused_repeatable_index` (mirrors `_add_repeatable_row` behaviour) so `cross_section_blocked` never fires for legitimate repeatable writes.
  - `prompts/onboarding_system.md` — new "JSON-as-Truth Protocol — MANDATORY pre-flight" block under ABSOLUTE STATE AUTHORITY. 5 enforcement rules: never ask for filled fields, never start from section[0] when state has data, never ask the same question twice, prior_pages personalisation, auto-copied fields are still filled.
- **Docs:**
  - `FLUTTER_DEV_HANDOFF.md` — appended Issue #28 documenting auto-copy contract + new payload keys + flag-default note.
  - `FLUTTER_VOICE_INTEGRATION_FIXES.md` — **deleted** (superseded by HANDOFF). Log reference in `tools.py:537` updated.
- **Tests:** 192 → 198 (+6 regression):
  - `test_service_address_auto_copies_when_flag_default_true`
  - `test_service_address_no_copy_when_flag_explicit_false`
  - `test_service_address_copies_after_flag_flip_to_true`
  - `test_cross_screen_context_flag_defaults_on`
  - `test_repeatable_update_auto_pins_focus_when_other_section_focused`
  - `test_non_repeatable_cross_section_still_blocked_without_intent`
- **Plan artifact:** `SENA_AI/.claude/plans/no-graceful-muffin.md` (PRD style — overwrites prior cross-screen isolation plan, preserved in git history)
- **Flutter follow-up:** Issue #28 in `FLUTTER_DEV_HANDOFF.md` — accept new `source` + `auto_copied_from` keys on `field_updated` events; verify `tenant_id` + `participant_id` are non-empty on `POST /v1/onboarding/session` (Issue #26 dependency for resume context to populate `prior_pages`).
- **Anti-recurrence guard:** the JSON-as-Truth Protocol block is the durable fix for the bug *family*. Whenever a future "agent re-asked field X" report arrives, first check whether the prompt rule is still present and whether the cross-screen flag is still ON.

### #14 — Forensic audit fixes (anti-pattern remediation, 2026-05-07)
- **Status:** completed (2026-05-07)
- **Priority:** P0 (NDIS legal-compliance risk in N-2: cross-field invariants bypassed at advance gate)
- **Backend plan:** `.planning/PLAN-audit-2026-05-07-fixes.md` (7 sequential steps, 93 tests target)
- **Frontend plan:** `SENA_AI/FLUTTER_DEV_HANDOFF.md` Addendum 2026-05-07 — Issues #18-#22
- **Anti-patterns identified:**
  - **AP-1** Missing Consumer Subscription — Flutter switch has no `case` for 5 server events (validation_rejection, field_skipped_warning, schema_drift_detected, repeatable_section_entered/exited)
  - **AP-2** Prompt-vs-Schema Drift — Rule 5 had no anchor; Rule 9 had no min-zero protocol
  - **AP-3** Context Boundary Leak — `participant_display_name` buried in `[LIVE_STATE_JSON]`, not interpolated as directive
  - **AP-4** Trust-the-Model Termination — `confirmation_transcript` not required, cross-field invariants never gated
  - **AP-5** Producer-Without-Schema-Contract — new server events ship without typed Flutter contract
- **What's already done (this session):**
  - System prompt — Rule 10 (post-capture readback) + Rule 11 (self-knowledge from state) added; Pace section tightened (one-sentence default, listen-first rule)
  - Forensic report + plan files written; nothing else yet
- **Backend steps (all completed 2026-05-07):**
  1. ✓ `next_optional_field` in `services/validators/sequencing.py` + 2 tests
  2. ✓ `__PARTICIPANT_NAME__` + `__NEXT_OPTIONAL_FIELD__` tokens in `prompt_builder.py` + 4 tests
  3. ✓ `prompts/onboarding_system.md` — greeting directive + Rule 5 anchor + Rule 9 min-zero protocol
  4. ✓ `_advance_step` hardened — `confirmation_transcript` required + cross-field invariant gate + 4 tests
  5. ✓ Race fix in `_handle_validation_failed` — `audio_stream_end=True` before text injection
  6. ✓ v2 `field_errors` → `state.pending_validation_errors` mirror in `_handle_screen_state` + 3 tests (bug fixed: uses `state_v2.field_errors` dict not raw list)
  7. ✓ Auto-pin focus + emit `repeatable_section_entered` from `_add_repeatable_row` + 2 tests
- **Frontend steps remaining (separate session — Flutter team):**
  - Issue #18 — `validation_rejection` entity + parser + controller + UI binding
  - Issue #19 — `field_skipped_warning` entity + parser + banner + missing-field highlights
  - Issue #20 — `schema_drift_detected` entity + parser + inline notice + auto-refresh strategy
  - Issue #21 — `repeatable_section_entered/exited` entities + focused-row UI states
  - Issue #22 — `participantDisplayName` UI personalisation in voice-sheet header
  - Anti-recurrence — `default` arm of `VoiceEventModel.parse` logs `WARN` instead of silent `null`
- **Verification gates:**
  - After each backend step: `pytest services/onboarding/tests/ --ignore=test_cross_screen_context.py --ignore=test_validators.py -x -q`
  - Test count progression: 78 → 80 → 84 → 84 → 88 → 88 → 91 → 93
- **Bugs this addresses (from user report):**
  - #1 Email validation broken → Issue #18 (Flutter consumer gap)
  - #2 Non-sequential flow → Step 3 (Rule 5 anchor + Rule 9 min-zero)
  - #3 Personalisation lost on new screens → Step 2 + Step 3a (token interpolation)
  - #4 Morning Routine called optional → Step 3c (Rule 9 min-zero protocol)
  - #5 Vague "add more info" → Issue #19 (Flutter consumer gap)
  - #6 Abrupt session termination → Step 4 (`confirmation_transcript` required)
  - #7 No dynamic field-added sync → Issue #20 (Flutter consumer gap)
- **Newly discovered issues (Group 2):**
  - N-1 → Issue #21 (Flutter)
  - N-2 → Step 4 (cross-field gate) — **NDIS legal-compliance risk**
  - N-3 → Step 5 (audio race fix)
  - N-4 → Step 6 (v2 mirror)
  - N-5 → Step 7 (auto-pin focus)
  - N-6 → Issue #22 (Flutter)
  - N-7 → Step 4 (confirmation_transcript validated end-to-end)

### #13 — Onboarding validation awareness + sequencing + schema-drift discovery
- **Status:** completed (2026-05-07)
- **Priority:** P1
- **PRD:** `.planning/PRD-validation-sequencing-discovery.md`
- **Cross-check:** `.planning/VALIDATION-CROSS-CHECK-2026-05-07.md` (canon: Flutter code is ground truth, mirrored into server `validators.py` + `client_onboarding_validations.md`)
- **What shipped (server-side, this branch):**
  - `services/validators.py` — server-side authoritative validator catalogue (phone shape, date sanity, email, NDIS number, plan-date ordering, BSB, ABN, etc.) — runs BEFORE every `update_field` write; rejection upserts into `state.pending_validation_errors`
  - `FormState.pending_validation_errors: list[dict]` — keyed by `(section_id, field_id, repeatable_index)`; mirrored into `[LIVE_STATE_JSON]` block of system prompt every turn
  - `_advance_step` blocks while `pending_validation_errors` non-empty; emits `field_skipped_warning` with `missing_fields: [{section_id, field_id, repeatable_index?}]` when required fields still empty
  - WS server→client events:
    - `repeatable_section_entered` `{section_id, row_index, intent}` — emitted from `_enter_repeatable_section`
    - `repeatable_section_exited` `{section_id}` — newly emitted from `_exit_repeatable_section`
    - `field_skipped_warning` `{missing_count, required_filled, required_total, missing_fields[]}` — `missing_fields` enumerates exactly which required fields are empty
    - `schema_drift_detected` `{kind: "unknown_field"|"unknown_section", attempted_section, attempted_field?, label?}` — wired in 3 sites: `_update_field` unknown-section branch, `_update_field` unknown-field branch, `_request_unknown_section` tool
  - WS client→server frames (new handlers in `GeminiLiveSession._handle_control`):
    - `validation_failed` `{section_id, field_id, repeatable_index?, code, reason_human}` — upserts into `pending_validation_errors`, injects `[SCREEN VALIDATION]` text into Gemini stream so model re-asks
    - `validation_cleared` `{section_id, field_id, repeatable_index?}` — drops the entry from `pending_validation_errors`
  - System prompt — Rule 7 (frontend validation loop) + Rule 8 (server-side validation guard) + Rule 9 (sequencing + repeatable entry) added; `[LIVE_STATE_JSON]` block now exposes `pending_validation_errors` and `next_required_field`
- **Flutter delta:** `SENA_AI/FLUTTER_DEV_HANDOFF.md` rewritten for accuracy — corrected event names (`section_entered` → `repeatable_section_entered`), payload shapes (added `missing_fields[]`), client→server tables, integration checklist
- **Tests:** 78/78 pass (excluding 2 pre-existing import errors in `test_cross_screen_context.py` and `test_validators.py` — unrelated to this work)
- **Files modified:**
  - `src/onboarding/services/tools.py` — schema_drift emits + missing_fields enumeration in advance_step
  - `src/onboarding/services/gemini_live.py` — `_handle_validation_failed` + `_handle_validation_cleared`
  - `src/onboarding/api/ws_routes.py` — docstring updated for new client→server frames
  - `SENA_AI/FLUTTER_DEV_HANDOFF.md` — full accuracy pass on event names + payloads + checklist
- **Out of scope:** Flutter implementation of `validation_failed`/`validation_cleared` emit + listener for the 4 new server events (mobile-team work, documented in handoff)

### #12 — Onboarding cross-screen shared context (per-(tenant, participant) bucket)
- **Status:** completed (2026-05-06)
- **Priority:** P1
- **PRD:** `.planning/PRD-cross-screen-context.md`
- **Plan:** `.claude/plans/no-graceful-muffin.md` (approved, executed end-to-end)
- **What shipped:**
  - New pure module `services/cross_screen_context.py` — `KEY_ALIASES` table, `VERBATIM_FIELDS = {name, dob, gender, goals, hobbies, interests}`, `build_summary`, `compress_residual`/`decompress` (lossless), `render_for_prompt` (caps inline-verbatim to last 5 steps)
  - New repository `repositories/user_context_repo.py` — Redis Hash + Set keyed `sena:onboarding:user_ctx:{tenant_id}:{participant_id}` and `…user_idx:…`, 7-day TTL refreshed on every write
  - New models `models/cross_screen_summary.py` — `StepSummary`, `CrossScreenContext` (versioned `schema_version=1`)
  - Prompt-builder `__CROSS_SCREEN_SUMMARY__` placeholder (between `__LIVE_STATE_JSON__` and SCHEMA), rendered only when bucket non-empty
  - `system prompt` template — placeholder added between bootstrap-mode line and behaviour-by-mode block
  - Routes — `POST /v1/onboarding/session` auto-hydrates `bootstrap.prior_pages` from bucket (client-supplied wins); `POST .../complete` persists `StepSummary` BEFORE webhook fires
  - `ws_routes` — best-effort summary flush on clean WS close (idempotent on `(participant_id, step_number)`); cross-screen text rendered into prompt
  - `state_repo.assert_session_owner(session_id, tenant_id, participant_id)` — closes latent isolation gap; wired into GET state and PUT state via X-Tenant-Id / X-Participant-Id headers
  - Settings flag `SENA_AI_ONBOARDING_CROSS_SCREEN_CONTEXT_ENABLED` (default `true`); single-flag rollback path
  - `.env.example` — new env var documented
- **Tests:** 89/89 pass via `PYTHONPATH=services/onboarding/src python -m pytest services/onboarding/tests/ -q`. New file `tests/test_cross_screen_context.py` adds 11 cases covering round-trip (lossless property), verbatim passthrough, empty FormState, render snapshot, token-budget smoke.
- **Flutter delta:** auto-hydration is server-side only — Flutter benefits with no code change. Documented in `SENA_AI/FLUTTER_DEV_HANDOFF.md`.
- **Out of scope:** LLM-based summarization (deferred to v2), bucket-list API endpoint, schema-migration tooling, fakeredis tests for `user_context_repo` (PRD §"What is intentionally not unit-tested").
- **Files (5 new + 7 modified):**
  - NEW: `src/onboarding/services/cross_screen_context.py`
  - NEW: `src/onboarding/repositories/user_context_repo.py`
  - NEW: `src/onboarding/models/cross_screen_summary.py`
  - NEW: `tests/test_cross_screen_context.py`
  - MODIFIED: `src/onboarding/services/prompt_builder.py`, `src/onboarding/prompts/onboarding_system.md`, `src/onboarding/api/routes.py`, `src/onboarding/api/ws_routes.py`, `src/onboarding/repositories/state_repo.py`, `src/onboarding/core/settings.py`, `sena-ai/.env.example`
  - DOCS: `SENA_AI/CLAUDE.md`, `SENA_AI/.claude/SESSION_START.md`, `SENA_AI/FLUTTER_DEV_HANDOFF.md`

### #11 — Onboarding rules-and-voice-protocols (7 rules + interrupt + silence + compression)
- **Status:** completed (2026-05-02)
- **Priority:** P1
- **Plan:** `~/.claude/plans/cozy-waddling-river.md` (approved by user, executed end-to-end)
- **What shipped:**
  - Rule 1 + 2 — `SessionBootstrap` envelope (`models/session_bootstrap.py`) wired through `routes.py` → Redis (`state_repo.py`, new `_KEY_BOOTSTRAP`) → `ws_routes.py` → `prompt_builder.py` (`__LIVE_STATE_JSON__` placeholder) → `prompts/onboarding_system.md` (full rewrite, [LIVE_STATE_JSON] block as the SOLE state authority)
  - Rule 3 — readonly enforcement in `ToolDispatcher._update_field` (rejects paths in `bootstrap.readonly_paths`); pre-fill verify rule in system prompt
  - Rule 4 — multi-value capture: `update_field` tool decl now exposes both `value` (scalar) and `values` (array) parameters; dispatcher prefers `values` and logs `multi_value applied field=... count=N`
  - Rule 5 — proactive optional prompting rule in system prompt
  - Rule 6 — already-shipped `add_repeatable_row` tool / `row_added` event (verified, documented Flutter subscribe in Issue 9)
  - Rule 7 — `field_errors: dict[str, str]` field on `ScreenStateV2`; `render_injection_text` surfaces reasons in `Invalid (re-ask): path (reason)` form
  - Voice protocol — interrupt-intent preservation: `_last_interrupted_intent` retained, hidden `[INTERRUPTED]` text turn injected so next agent turn can address user AND finish the prior thought
  - Voice protocol — context_window_compression with sliding window enabled in `LiveConnectConfig` (with SDK-version fallback)
  - Voice protocol — silence watchdog two-step (existing single-threshold extended; `_silence_warned` flag tracks first warn vs follow-up summary)
- **Tests:** 78/78 pass via `PYTHONPATH=src python -m pytest tests/`. Added 2 new tests for Rule 7 `field_errors` rendering. Updated 1 stale `test_function_decls_cover_all_handlers` (4→5 handlers) and 4 stale v1-signature `render_injection_text` tests (now use v2 `ScreenStateV2`).
- **Flutter delta:** `SENA_AI/FLUTTER_VOICE_INTEGRATION_FIXES.md` Issues 7 (bootstrap), 8 (`field_errors`), 9 (subscribe `row_added`).
- **Files modified (9 + tests + docs):**
  - `src/onboarding/models/session_bootstrap.py` (NEW)
  - `src/onboarding/repositories/state_repo.py`
  - `src/onboarding/api/routes.py`
  - `src/onboarding/api/ws_routes.py`
  - `src/onboarding/services/prompt_builder.py`
  - `src/onboarding/services/screen_context.py`
  - `src/onboarding/services/tools.py`
  - `src/onboarding/services/gemini_live.py`
  - `src/onboarding/prompts/onboarding_system.md` (full rewrite — 50→200 lines)
  - `tests/test_tools.py`, `tests/test_screen_context.py`
  - `SENA_AI/FLUTTER_VOICE_INTEGRATION_FIXES.md`

### #10 — Case Note Review service (pair-programming split)
- **Status:** in_progress — Phase C complete (2026-04-27), Phase D next
- **Priority:** P1
- **Plan:** `.planning/CASE_NOTE_REVIEW_PLAN.md` (authoritative — read this to resume)
- **Scope:** AI intelligence layer around case notes (context, classify, review, incident). Other engineer owns drafting + storage.
- **Service path:** `sena-ai/services/case_review/` (port 8084, ai-db)
- **Phases:**
  - A — Scaffold + DB (4 tables) + stub client ✓
  - B — `/context` rolling summary ✓ (real Gemini call verified end-to-end)
  - C — `/classify` paragraph → fields + reask ✓ (classifier, classify_service, route, tests)
  - D — `/review` risks + restrictive practices + anomalies ← next
  - E — `/incident/*` detect + autofill
  - F — `/submit` gate + routing (BLOCKED: register ownership TBD)
  - G — Hardening + docs
- **Blockers logged in plan §7**

### #1 — Voice assistant: conversational streaming (Siri/Assistant-style)
- **Status:** completed (2026-04-17)
- **Priority:** P0 (primary blocker, now cleared)
- **Final solution:** see `wiki/pages/gemini-live-multi-turn-config.md` + `memory/feedback_gemini_live_patterns.md`
- **Files:** `sena-ai/demo_live_server.py`, `sena-ai/demo_client.html`
- **Verified:** multi-turn confirmed via USER_SAID/GEMINI_SAID logs

### #2 — Wiki + memory + planning docs for session resume
- **Status:** completed (2026-04-20)
- **Artifacts written:**
  - `.claude/SESSION_START.md` — read-order guide for new sessions (NEW)
  - `.planning/FEATURES_LEFT.md` — full roadmap across 13 categories
  - `.planning/GEMINI_LIVE_NATIVE_SCOPE.md` — voice-only, Gemini-native scope
  - `wiki/pages/gemini-live-multi-turn-config.md` — authoritative Live API config
  - `memory/feedback_gemini_live_patterns.md` — hard-won multi-turn rules
  - `memory/project_voice_demo_working.md` — demo working-state memory

---

## Next up (picked by user when resuming)

### #9 — Onboarding Voice API (consolidates #3–#8)
- **Status:** VERIFIED 95% — v2 implemented (2026-04-29); one gap: close code **4011** (`policy_block`) not yet in `gemini_live.py`
- **v2 files implemented (2026-04-29):**
  - `models/schema_spec.py` — added `voice_coverage`, `voice_repeatable_sections` to `StepSchema`
  - `models/form_state.py` — added `repeatable_rows`, `increment_repeatable_row()`
  - `core/settings.py` — added `voice_coverage_enforced`, `field_apply_log_level`
  - `services/coverage.py` — NEW pure module: `is_eligible`, `is_repeatable_eligible`, `coverage_paths`
  - `services/field_apply.py` — NEW pure module: `build_envelope` (field_apply WS event)
  - `services/screen_context.py` — REWRITTEN: `ScreenStateV2`, `ScreenStateV2Message`, `from_v1()` adapter, v2 `render_injection_text`
  - `services/tools.py` — added `add_repeatable_row` tool + dispatch, `field_apply` emit in `_update_field`
  - `services/prompt_builder.py` — added `_voice_coverage_section()`, `__VOICE_COVERAGE_SECTION__` substitution
  - `services/gemini_live.py` — `screen_state_v2` branch, v2 handler, v1 adapter path
  - `api/ws_routes.py` — `prompt_version:"v2"`, `coverage` in ready envelope
  - `prompts/onboarding_system.md` — updated [SCREEN] rule for v2, added `__VOICE_COVERAGE_SECTION__`
  - `fixtures/schema_personal_information.json` — `bio`→`about_me`, `required:false`, `voice_coverage` added
  - `fixtures/schema_ndis_plan_details.json` — `voice_coverage` + `voice_repeatable_sections` added
- **v1 status (frozen):** DONE — Phases A–F shipped (2026-04-28)
- **Prior status:** in_progress (Phase C complete 2026-04-21)
- **Priority:** P1
- **Scope:** Tasks #3, #4, #5, #6, #7, #8 rolled into a single API-first delivery
- **Why consolidated:** mobile app already exists; we build the backend only — all six tasks naturally share the same session model, WS protocol, and state store
- **Plan:** `.planning/ONBOARDING_VOICE_API_PLAN.md` (full architecture, API contract, 6 build phases)
- **Decisions locked (from user, 2026-04-20):**
  - Webhook to mock URL on step completion
  - Auth skipped MVP (pluggable seam for later)
  - One voice session == one onboarding step (clean resume semantics)
  - App backend owns schema, passes inline in session-create payload
  - FormState writer = voice only during WS; app PUTs only when WS closed
  - Document/photo capture via voice skipped (app handles)
  - Locale = Australian English (`en-AU`)
- **Source of form structure:** mobile-app screens (analyzed 2026-04-20, since crystallized into `services/onboarding/fixtures/schema_*.json`) — 5 steps + 6-section consent flow
- **Phases:**
  - A: REST scaffold + Redis state store + webhook ✓ (36/36 tests, 2026-04-20)
  - B: WS endpoint + Gemini Live wiring + system prompt injection (#3) ✓ (2026-04-21)
  - C: Tool calling — `update_field`, `get_session_context`, `advance_step`, `escalate_incident` (#4) ✓ (2026-04-21, 48/48 tests)
  - F (partial): `test_harness.html` at `/harness` — phases A/B/C testable in browser ✓ (2026-04-21)
    - `GET /harness` + `GET /harness/fixtures/{step_id}` routes added to `main.py` ✓ (2026-04-21)
    - **Run requirement:** `pip install -e .` from `sena-ai/services/onboarding/` before uvicorn (src-layout needs editable install)
  - D: ~~Camera/screen frame ingress~~ → screen_state JSON WS message, screen_context.py pure module, Gemini inject ✓ (2026-04-28)
  - E: Session resumption (resumption.py, redeem GETDEL, resumable envelope, close 4010) + grounding (grounding.py, build_live_tools, flag off by default) ✓ (2026-04-28)
  - F: OpenAPI unconditional /docs, WS_PROTOCOL.md, postman_collection.json ✓ (2026-04-28)
- **Acceptance:** mobile engineer can integrate from docs alone; webhook fires with final FormState; resumption works across reconnect; grounded NDIS answers

### Individual tasks (folded into #9)
- #3 Form-aware system prompt — Phase B
- #4 Tool calling scaffold — Phase C
- #5 Camera frames — Phase D
- #6 Screen state frames — Phase D
- #7 Session resumption — Phase E
- #8 Google Search grounding — Phase E

---

## Backlog (deferred, blocked, or later milestone)

- Production voice service migration: `gemini_live_service.py` uses OLD API → migrate to `send_realtime_input` pattern from demo
- ~~Wiring `ws_routes.py` with demo's VAD config + receive-loop pattern~~ — done in Phase B
- Audio transcription display in demo UI
- RAG over NDIS documents (pgvector + structure-aware chunking) — source docs now available at `ndis_wiki/sources/` (NDIS Commission PDFs → markdown). Ready to plan when prioritised.
- OCR service implementation — BLOCKED on client document samples
- JWT auth + RLS policies — BLOCKED on client JWT claims structure
- Context window compression for >15 min sessions
- Ephemeral token auth for browser-side
- Flow B (case note dictation) LiveKit Agent pattern
- AU data residency sign-off for Gemini Live (production blocker)

---

## Conventions

- Update this file whenever a task status changes or a new task is added.
- Lead each task with ID, status, and 1-line summary.
- Include file paths, constraints, and acceptance criteria for P0/P1 items.
- When a task completes, keep the entry (don't delete) for a few sessions — provides trail.
- When backlog grows stale, prune to a separate archive file.
