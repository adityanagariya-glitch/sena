---
title: Persistent Task List
updated: 2026-05-02
---

> Last session end-state (2026-05-02): Onboarding #11 (7 behavioural rules + voice protocols) COMPLETE. 9 backend files + system prompt rewritten. Tests 78/78. Flutter delta documented in `FLUTTER_VOICE_INTEGRATION_FIXES.md` (Issues 7–9). Case Note Review #10 Phase D still next.
> **New session: read `.claude/SESSION_START.md` FIRST.**

# SENA Task List

Session-persistent todos. Survives `/compact` and session resets. Claude reads this file at session start and updates it as work progresses.

**Status legend:** `pending` | `in_progress` | `completed` | `blocked`

---

## Active

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
