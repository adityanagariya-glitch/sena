---
title: Task Archive — Completed Features
updated: 2026-05-14
purpose: Historical record of shipped features. Read only if you need to understand prior work; do NOT use as next-step guidance. The active queue lives in TASKS.md.
---

# SENA Task Archive

This file holds the full task history for features that are **complete and out of active scope**. New sessions should not pick up context from this file unless explicitly investigating prior work. The canonical "what to do next" lives in `.claude/tasks/TASKS.md`.

**Archived 2026-05-14:**
- Feature A — **Voice assistance** (onboarding voice API + onboarding voice protocols + voice/typed validation parity). Backend deployed to EC2 (`docker-compose.deploy.yml`). Flutter contract `SENA_AI/flutterhandoffdev.md` remains the canonical handoff; frontend implementation owned by the `sena-mobile` team.
- Feature B — **Case Review service** (Phase A-C shipped). Phase D-G **shelved 2026-05-14** — not on the active roadmap.

---

## Feature A — Voice Assistance (CLOSED 2026-05-14)

### #17 — Voice/typed validation parity, Step 1 client onboarding (2026-05-12)
- **Status:** backend complete (2026-05-12); frontend pending in `sena-mobile` per `SENA_AI/flutterhandoffdev.md`
- **Priority:** P0 (voice rollout blocker — NDIS data-quality risk if voice bypass persists)
- **What was broken:**
  - Voice writes bypassed every frontend validator (raw STT → controllers directly)
  - `validation_rejection` WS events silently dropped (no consumer wired)
  - No `input_method` ("typed"|"voice") tracking → impossible to audit which channel rejected
  - No POST `/errors` endpoint → no way for Flutter to report typed-validation failures back to
    the agent / training loop
- **What shipped this run (6-agent orchestration):**
  - `SENA_AI/flutterhandoffdev.md` (1651 lines, 91.8 KB after 2026-05-12 QA pass) — canonical
    Flutter handoff: per-field validator contract, voice sink interception, TTS error-speak
    + mic auto-reopen, AppStrings additions (paired on-screen / `voice*` keys where spoken
    differs from inline), full Step-1 field map
  - Backend `sena-ai/services/onboarding/`:
    - New `POST /v1/onboarding/session/{session_id}/errors` (204; strict body shape; persists to
      Redis list `sena:onboarding:errors:{sid}` with 7-day TTL)
    - `FieldValue.input_method: Literal["typed","voice"] | None` — propagated through writers
    - `build_envelope` (`services/field_apply.py`) now surfaces `input_method` on `field_apply`
    - Per-write cross-field invariant check inside `_update_field` (no longer only at advance gate)
    - Cross-field `reason_human` strings reconciled to match Flutter `AppStrings` verbatim
      (emergency-contact phone-equals-client, duplicate-contact, plan-end-before-start)
    - `basics.interpreter_required` → `_v_boolean_required`
    - `basics.about_me` → `_v_text250_required`
  - New tests: `test_errors_endpoint.py`, `test_field_apply.py`; extended `test_validators.py`
- **Definition of done (frontend, owned by Flutter team):**
  - Every Step-1 voice-mapped field validates-before-state for typed **and** voice input
  - `validation_rejection` event parsed on Flutter and surfaced as inline field error
  - TTS speaks the same on-screen string; mic auto-reopens after the speak completes
  - POST `/errors` fires on every typed-validation failure
  - AppStrings additions made (no inline copy)
  - `flutter analyze` → 0 warnings; test coverage for new validator/voice paths
- **Anti-recurrence guard:** any future "voice wrote bad data" report → check (a) `input_method`
  threaded end-to-end, (b) `POST /errors` firing on typed failures, (c) `validation_rejection`
  parsed by Flutter `VoiceEventModel.parse`.

### #16 — Voice assistant UX bugs (VAD, validation, routines, amnesia) (2026-05-12)
- **Status:** completed (2026-05-12) — commit db2ee7c
- **Priority:** P0 (user-reported — blocked voice rollout sign-off)
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
- **Tests:** 192 → 198 (+6 regression).
- **Flutter follow-up:** Issue #28 in `flutterhandoffdev.md` — accept new `source` + `auto_copied_from` keys on `field_updated` events.
- **Anti-recurrence guard:** the JSON-as-Truth Protocol block is the durable fix for the bug *family*. Whenever a future "agent re-asked field X" report arrives, first check whether the prompt rule is still present and whether the cross-screen flag is still ON.

### #14 — Forensic audit fixes (anti-pattern remediation, 2026-05-07)
- **Status:** completed (2026-05-07)
- **Priority:** P0 (NDIS legal-compliance risk in N-2: cross-field invariants bypassed at advance gate)
- **Backend plan:** `.planning/PLAN-audit-2026-05-07-fixes.md` (7 sequential steps, 93 tests target)
- **Anti-patterns identified:**
  - **AP-1** Missing Consumer Subscription — Flutter switch has no `case` for 5 server events
  - **AP-2** Prompt-vs-Schema Drift — Rule 5 had no anchor; Rule 9 had no min-zero protocol
  - **AP-3** Context Boundary Leak — `participant_display_name` buried in `[LIVE_STATE_JSON]`
  - **AP-4** Trust-the-Model Termination — `confirmation_transcript` not required, cross-field invariants never gated
  - **AP-5** Producer-Without-Schema-Contract — new server events ship without typed Flutter contract
- **Backend steps (all completed 2026-05-07):**
  1. ✓ `next_optional_field` in `services/validators/sequencing.py` + 2 tests
  2. ✓ `__PARTICIPANT_NAME__` + `__NEXT_OPTIONAL_FIELD__` tokens in `prompt_builder.py` + 4 tests
  3. ✓ `prompts/onboarding_system.md` — greeting directive + Rule 5 anchor + Rule 9 min-zero protocol
  4. ✓ `_advance_step` hardened — `confirmation_transcript` required + cross-field invariant gate + 4 tests
  5. ✓ Race fix in `_handle_validation_failed` — `audio_stream_end=True` before text injection
  6. ✓ v2 `field_errors` → `state.pending_validation_errors` mirror in `_handle_screen_state` + 3 tests
  7. ✓ Auto-pin focus + emit `repeatable_section_entered` from `_add_repeatable_row` + 2 tests
- **Test count progression:** 78 → 80 → 84 → 84 → 88 → 88 → 91 → 93

### #13 — Onboarding validation awareness + sequencing + schema-drift discovery (2026-05-07)
- **Status:** completed (2026-05-07)
- **Priority:** P1
- **PRD:** `.planning/PRD-validation-sequencing-discovery.md`
- **Cross-check:** `.planning/VALIDATION-CROSS-CHECK-2026-05-07.md` (canon: Flutter code is ground truth, mirrored into server `validators.py` + `client_onboarding_validations.md`)
- **What shipped (server-side):**
  - `services/validators.py` — authoritative validator catalogue runs BEFORE every `update_field` write; rejection upserts into `state.pending_validation_errors`
  - `FormState.pending_validation_errors: list[dict]` mirrored into `[LIVE_STATE_JSON]` block of system prompt every turn
  - `_advance_step` blocks while `pending_validation_errors` non-empty; emits `field_skipped_warning` with `missing_fields: [...]`
  - WS server→client events: `repeatable_section_entered`, `repeatable_section_exited`, `field_skipped_warning`, `schema_drift_detected`
  - WS client→server frames: `validation_failed`, `validation_cleared`
  - System prompt — Rules 7+8+9 added
- **Tests:** 78/78 pass

### #12 — Onboarding cross-screen shared context (2026-05-06)
- **Status:** completed (2026-05-06)
- **Priority:** P1
- **PRD:** `.planning/PRD-cross-screen-context.md`
- **What shipped:**
  - `services/cross_screen_context.py` — `KEY_ALIASES`, `VERBATIM_FIELDS`, `build_summary`, `compress_residual`/`decompress` (lossless), `render_for_prompt` (caps last 5 steps)
  - `repositories/user_context_repo.py` — Redis Hash + Set keyed `sena:onboarding:user_ctx:{tenant_id}:{participant_id}`, 7-day TTL
  - `models/cross_screen_summary.py` — `StepSummary`, `CrossScreenContext` (versioned `schema_version=1`)
  - Prompt-builder `__CROSS_SCREEN_SUMMARY__` placeholder
  - Routes — `POST /v1/onboarding/session` auto-hydrates `bootstrap.prior_pages`; `POST .../complete` persists `StepSummary` BEFORE webhook fires
  - `state_repo.assert_session_owner(session_id, tenant_id, participant_id)` — closes isolation gap
  - Settings flag `SENA_AI_ONBOARDING_CROSS_SCREEN_CONTEXT_ENABLED` (default `true`)
- **Tests:** 89/89 pass

### #11 — Onboarding rules-and-voice-protocols (2026-05-02)
- **Status:** completed (2026-05-02)
- **Priority:** P1
- **Plan:** `~/.claude/plans/cozy-waddling-river.md`
- **What shipped:**
  - Rules 1-7 in `prompts/onboarding_system.md` (full rewrite — 50→200 lines)
  - `SessionBootstrap` envelope (`models/session_bootstrap.py`) wired through routes → Redis → ws_routes → prompt_builder
  - Readonly enforcement in `_update_field`
  - `update_field` tool exposes both `value` (scalar) and `values` (array) parameters
  - `field_errors: dict[str, str]` on `ScreenStateV2`
  - Interrupt-intent preservation in voice protocol
  - `context_window_compression` with sliding window
  - Silence watchdog two-step
- **Tests:** 78/78 pass

### #9 — Onboarding Voice API (consolidates #3–#8, shipped 2026-04-28→2026-04-29)
- **Status:** completed v2 (2026-04-29)
- **Plan:** `.planning/ONBOARDING_VOICE_API_PLAN.md`
- **Phases:**
  - A: REST scaffold + Redis state store + webhook ✓ (36/36 tests, 2026-04-20)
  - B: WS endpoint + Gemini Live wiring + system prompt injection ✓ (2026-04-21)
  - C: Tool calling — `update_field`, `get_session_context`, `advance_step`, `escalate_incident` ✓ (2026-04-21, 48/48 tests)
  - D: screen_state JSON WS message, screen_context.py pure module, Gemini inject ✓ (2026-04-28)
  - E: Session resumption (resumption.py, redeem GETDEL, resumable envelope, close 4010) + grounding (grounding.py, flag off by default) ✓ (2026-04-28)
  - F: OpenAPI unconditional /docs, WS_PROTOCOL.md, postman_collection.json ✓ (2026-04-28)
- **v2 files (2026-04-29):** `screen_state_v2` WS message + `ScreenStateV2` model + `from_v1()` adapter; `field_apply` envelope; `add_repeatable_row` Gemini tool; `coverage.py` + `field_apply.py` pure modules; `voice_coverage` / `voice_repeatable_sections` on `StepSchema`; `bio` → `about_me`; `prompt_version:"v2"` in ready envelope
- **Decisions locked (from user, 2026-04-20):**
  - Webhook to mock URL on step completion
  - Auth skipped MVP (pluggable seam for later)
  - One voice session == one onboarding step (clean resume semantics)
  - App backend owns schema, passes inline in session-create payload
  - FormState writer = voice only during WS; app PUTs only when WS closed
  - Document/photo capture via voice skipped (app handles)
  - Locale = Australian English (`en-AU`)

### #2 — Wiki + memory + planning docs for session resume (2026-04-20)
- **Status:** completed
- **Artifacts written:**
  - `.claude/SESSION_START.md` — read-order guide for new sessions (NEW)
  - `.planning/FEATURES_LEFT.md` — full roadmap across 13 categories
  - `.planning/GEMINI_LIVE_NATIVE_SCOPE.md` — voice-only, Gemini-native scope
  - `wiki/pages/gemini-live-multi-turn-config.md` — authoritative Live API config
  - `memory/feedback_gemini_live_patterns.md` — hard-won multi-turn rules
  - `memory/project_voice_demo_working.md` — demo working-state memory

### #1 — Voice assistant: conversational streaming (2026-04-17)
- **Status:** completed
- **Priority:** P0 (primary blocker, cleared)
- **Final solution:** see `wiki/pages/gemini-live-multi-turn-config.md` + `memory/feedback_gemini_live_patterns.md`
- **Files:** `sena-ai/demo_live_server.py`, `sena-ai/demo_client.html`
- **Verified:** multi-turn confirmed via USER_SAID/GEMINI_SAID logs

---

## Feature B — Case Note Review service (SHELVED 2026-05-14)

### #10 — Case Note Review service (pair-programming split)
- **Final status:** Phase A-C complete (2026-04-27). Phase D-G **shelved 2026-05-14** — not on the active roadmap. Re-open by moving entry back to TASKS.md and reading `.planning/CASE_NOTE_REVIEW_PLAN.md`.
- **Priority (when active):** P1
- **Scope:** AI intelligence layer around case notes (context, classify, review, incident). Other engineer owns drafting + storage.
- **Service path:** `sena-ai/services/case_review/` (port 8084, ai-db)
- **Phases:**
  - A — Scaffold + DB (4 tables) + stub client ✓
  - B — `/context` rolling summary ✓ (real Gemini call verified end-to-end)
  - C — `/classify` paragraph → fields + reask ✓ (classifier, classify_service, route, tests)
  - D — `/review` risks + restrictive practices + anomalies — **NOT STARTED, SHELVED**
  - E — `/incident/*` detect + autofill — **NOT STARTED, SHELVED**
  - F — `/submit` gate + routing — **BLOCKED + SHELVED** (register ownership TBD with other engineer)
  - G — Hardening + docs — **NOT STARTED, SHELVED**
- **Non-negotiables (when re-opened):** `tenant_id` on every row + RLS, staff acknowledgement per AI flag, audit log entry per action, `GEMINI_REGION=australia-southeast1`
