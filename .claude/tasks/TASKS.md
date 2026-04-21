---
title: Persistent Task List
updated: 2026-04-21
---

> Last session end-state (2026-04-21): Phases A+B+C complete. Harness routes live at /harness + /harness/fixtures/{step_id}. pip install -e . required to run onboarding service.
> Debug session (2026-04-21): VAD not detecting user voice after turn 6 — root cause = echo from speakers (no headphones + echoCancellation:false). Tried `_agent_speaking` echo gate → REVERTED (breaks VAD after 2-4 turns, documented in CLAUDE.md rule 6 + feedback_gemini_live_patterns.md rule 7+8). Correct fix: stream audio unconditionally, use START_SENSITIVITY_LOW. Firefox no-audio from speakers: separate issue, still unresolved (split AudioContext fix proposed but not applied — user should test beep button first).
> **New session: read `.claude/SESSION_START.md` FIRST.**

# SENA Task List

Session-persistent todos. Survives `/compact` and session resets. Claude reads this file at session start and updates it as work progresses.

**Status legend:** `pending` | `in_progress` | `completed` | `blocked`

---

## Active

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
- **Status:** in_progress (Phase C complete 2026-04-21)
- **Priority:** P1
- **Scope:** Tasks #3, #4, #5, #6, #7, #8 rolled into a single API-first delivery
- **Why consolidated:** mobile app already exists (screens in `SENA SCREENS ONBORDING/`); we build the backend only — all six tasks naturally share the same session model, WS protocol, and state store
- **Plan:** `.planning/ONBOARDING_VOICE_API_PLAN.md` (full architecture, API contract, 6 build phases)
- **Decisions locked (from user, 2026-04-20):**
  - Webhook to mock URL on step completion
  - Auth skipped MVP (pluggable seam for later)
  - One voice session == one onboarding step (clean resume semantics)
  - App backend owns schema, passes inline in session-create payload
  - FormState writer = voice only during WS; app PUTs only when WS closed
  - Document/photo capture via voice skipped (app handles)
  - Locale = Australian English (`en-AU`)
- **Source of form structure:** 17 screens in `C:\Users\Admin\Downloads\SENA\SENA SCREENS ONBORDING\` (analyzed 2026-04-20) — 5 steps + 6-section consent flow
- **Phases:**
  - A: REST scaffold + Redis state store + webhook ✓ (36/36 tests, 2026-04-20)
  - B: WS endpoint + Gemini Live wiring + system prompt injection (#3) ✓ (2026-04-21)
  - C: Tool calling — `update_field`, `get_session_context`, `advance_step`, `escalate_incident` (#4) ✓ (2026-04-21, 48/48 tests)
  - F (partial): `test_harness.html` at `/harness` — phases A/B/C testable in browser ✓ (2026-04-21)
    - `GET /harness` + `GET /harness/fixtures/{step_id}` routes added to `main.py` ✓ (2026-04-21)
    - **Run requirement:** `pip install -e .` from `sena-ai/services/onboarding/` before uvicorn (src-layout needs editable install)
  - D: Camera + screen frame ingress via `send_realtime_input(video=Blob)` (#5 + #6) ← next
  - E: Session resumption + Google Search grounding (#7 + #8)
  - F: OpenAPI docs + WS protocol doc + Postman collection + dev harness update
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
- RAG over NDIS documents (pgvector + structure-aware chunking) — BLOCKED on client sample docs
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
