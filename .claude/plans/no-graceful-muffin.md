# PRD — Onboarding Voice Assistant Reliability & Delivery

**Owner:** SENA AI backend
**Service:** `sena-ai/services/onboarding` (port 8083)
**Date:** 2026-05-08
**Status:** 4 of 8 root-cause fixes shipped this session; remaining 4 scoped here.

---

## Context

The voice-driven NDIS onboarding assistant suffered from a class of bugs that all trace to **state-contract drift** — the Gemini Live model and the Flutter UI disagreeing about what has been captured, what is required, and when the session can end. Four root causes were fixed in this session (personalization, sequential flow, strict validation, autofill enum mapping). Four remain (graceful close confirmation, vague "schedule support" prompts, frontend dynamic field sync, min-zero repeatable UI surfacing).

This PRD captures the complete delivery slice — both the four fixes already merged and the four remaining items — so the work can be shipped end-to-end, verified against the original 7-issue forensic report, and handed off to Flutter for the mobile-side counterparts.

(Note: this file replaces a prior, unrelated plan that lived at the same path. The earlier "Cross-Screen Context — Isolation Repair" plan is preserved in git history.)

---

## Problem Statement

A participant calls the voice assistant to fill an NDIS onboarding form. They expect:

- The assistant to recognise them by name on every screen.
- Every field to be addressed in visual order — required ones answered, optional ones explicitly offered.
- Their data to validate on the way in, not five minutes later.
- The Flutter UI to reflect every captured value live, including newly added repeatable rows.
- A polite "is that everything?" before the session ends — not a sudden disconnect.

Instead they hit silent skips, accepted-then-rejected garbage data (`testmail.com`), an empty UI even though they spoke their NDIS number, no min-zero section affordances, vague "anything else?" prompts that don't say WHAT is missing, and an abrupt close.

The downstream consequence is that Operations re-runs onboarding manually for affected participants, eroding the entire value proposition of the voice flow.

---

## Solution

A single, contract-first delivery slice that closes the bridge between three components:

1. **Server prompt + tool dispatcher** (`prompt_builder.py`, `tools.py`, `gemini_live.py`)
2. **WebSocket event protocol** (`ws_routes.py`, `gemini_live.py`)
3. **Flutter client** (handoff via `FLUTTER_DEV_HANDOFF.md`)

The core architectural move is to make the **server the authoritative source of "what is filled / what is missing / what was rejected"**, emit that authoritatively over a typed WS event stream, and have both the Gemini system prompt and the Flutter UI consume the same stream rather than building parallel views.

---

## User Stories

### A. Personalization (DONE — verify in QA)

1. As a participant whose name was captured on screen 1, I want the assistant to greet me by my first name on every subsequent screen, so I feel acknowledged and not anonymised.
2. As a returning user resuming a session, I want the assistant to use my name on the first utterance of the resumed session, so the resume feels human.

### B. Strict Sequential Flow (DONE — verify in QA)

3. As a participant, I want the assistant to walk fields in the same order I see them on screen, so I never feel like the conversation is shuffling me.
4. As a participant, I want the assistant to explicitly ask "would you like to share X? It's optional" for every optional field, so nothing is silently skipped.
5. As a participant on a step that has min-zero repeatable sections (morning routine, evening routine, medical history), I want the assistant to surface the section once and let me opt in or skip, so I'm not blindsided later that I missed something.
6. As a participant, I want `advance_step` to be impossible until every required field is filled and every optional field is either filled or explicitly declined, so I never accidentally submit half a form.

### C. Strict Validation (DONE — verify in QA)

7. As a participant who enters `testmail.com` for an email field, I want the assistant to refuse it and explain the format ("needs an @ and a domain"), so I don't ship invalid data downstream.
8. As a participant who is asked for their NDIS number, I want the assistant to insist on exactly nine digits, so I don't have to redo the form.
9. As a participant whose value was rejected by the frontend's runtime validator, I want the assistant to re-ask in plain language without quoting the regex, so I can correct without confusion.

### D. Autofill Mapping (DONE — verify in QA)

10. As a participant who says "self-managed", I want the NDIS plan management dropdown on the screen to populate with `Self Managed` immediately, so I see my answer reflected.
11. As a participant who reads out a 9-digit NDIS number, I want it to land in the NDIS number field on the UI on the first try, regardless of casing or punctuation in my speech.

### E. Graceful Session Close (REMAINING — Issue #6 of original report)

12. As a participant nearing the end of the form, I want the assistant to read back a brief summary of what I provided and ask "is that everything?" before submitting, so I have a last chance to correct.
13. As a participant who says "wait, one more thing", I want the assistant to abort `advance_step`, accept my correction, and re-confirm before submitting, so my late edit isn't lost.
14. As a participant on a slow connection, I want the WS close to be deferred until after the `step_completed` event has been ack'd by the client, so the UI never races the close.

### F. "What's Left?" Enumeration (REMAINING — Issue #5 of original report)

15. As a participant who asks "what else do you need?", I want the assistant to list every outstanding required field by its human label ("we still need your address, your phone, and at least one emergency contact"), so I know exactly how much further we have to go.
16. As a participant on the support schedule step, I want the assistant to enumerate the specific fields it's asking about (frequency, day, time-of-day, location), not vaguely say "add more info", so I can answer concretely.

### G. Frontend Dynamic Sync (REMAINING — Issue #7 of original report)

17. As a Flutter app, I want a typed `field_updated` event after every successful capture, so I can re-render the affected field without polling state.
18. As a Flutter app, I want a `row_added` event with the new index when the assistant adds a repeatable row, so I can render the empty card immediately.
19. As a Flutter app, I want `repeatable_section_entered` and `repeatable_section_exited` events, so I can highlight the row currently being filled.
20. As a Flutter app, I want a `validation_rejection` event when a value fails server-side validation, so I can show inline error UI instead of relying on transcript inference.
21. As a Flutter app, I want a `schema_drift_detected` event when the active schema version diverges from what the WS opened with, so I can trigger an in-app refresh rather than crash silently.
22. As a Flutter app, I want a `field_skipped_warning` event when the agent decides to defer a field, so I can render a missing-field banner.

### H. Min-Zero Repeatable UI Surfacing (REMAINING — Issue #4 of original report)

23. As a participant on the requirements step, I want a "Morning Routine" section visible on the screen with an "Add" button, even when zero rows exist, so the visual state matches what the voice agent is offering.
24. As a participant who declines morning routine by voice, I want the section to remain visible on screen with a "Skipped" indicator, so I have a way to reopen it later.

---

## Implementation Decisions

### Module Boundaries

| Module | Responsibility | Already Modified This Session |
|---|---|---|
| `services/prompt_builder.py` | Renders the Gemini system prompt with `[LIVE_STATE_JSON]`, `next_required_field`, `next_optional_field`, `pending_validation_errors` | ✓ ADDRESS THE PARTICIPANT block + Rules 9, 12 |
| `services/tools.py` `ToolDispatcher` | Validates and dispatches Gemini function calls; owns enum coercion, cross-section guards, completion gate, webhook trigger | ✓ enum normalize, advance_step gates, repeatable focus auto-pin |
| `services/gemini_live.py` `GeminiLiveSession` | Bridges WS↔Gemini, mirrors screen state into `pending_validation_errors`, handles close codes | ✓ `field_errors` → `pending_validation_errors` mirror (test_gemini_live.py) |
| `services/screen_context.py` | Pure: ScreenStateMessage validation + render injection text + payload hash | unchanged |
| `services/grounding.py` | Builds Live API tool list + grounding switch | unchanged |
| `repositories/state_repo.py` | Redis-only state, WS lock, resumption handles | unchanged |
| `prompts/onboarding_system.md` | The voice agent's behavioural contract | ✓ Rules 8, 9, 12 + ADDRESS THE PARTICIPANT |

### New work — server side

**1. Graceful Close Confirmation (Stories 12–14)**
- `prompts/onboarding_system.md`: extend the `## COMPLETION` section so the agent must do a one-sentence readback recap ("Got it — Jane Smith, 0412 345 678, two emergency contacts. Is that everything?") and only call `advance_step` after a yes-confirmation transcript.
- `services/tools.py` `_advance_step`: keep the existing 3-char minimum on `confirmation_transcript` (prevents accidental "ok" from passing) but add a positive-affirmation regex check (`yes|yeah|yep|correct|that's everything|done|all good`) so the agent can't bypass the gate by sending arbitrary filler.
- `services/gemini_live.py`: emit `step_completed` BEFORE closing the WS, then await a single ack frame from the client (or 2-second timeout), then close with code 4000.

**2. "What's Left?" Enumeration (Stories 15–16)**
- `services/prompt_builder.py`: add a new top-level field `pending_required_labels: list[str]` to `[LIVE_STATE_JSON]`, derived from `state.completion_stats` cross-referenced with schema labels. Add a new prompt rule: "When the user asks 'what else?' or similar, recite this list verbatim by label."
- Verify `support_schedule` schema fixture has descriptive `label` per field; if missing, add labels.

**3. Typed WS Event Protocol (Stories 17–22)**
Define an additive contract — never break existing event types. Each event is a JSON object with `type` (string) plus payload. Server emits via existing `_emit` channel. Clients ignore unknown event types.

| Event type | Trigger | Payload | Already emitted? |
|---|---|---|---|
| `field_updated` | After every successful `update_field` | `{section_id, field_id, repeatable_index, value, confidence}` | partial — need explicit emit |
| `state` | After every state mutation | full `state` snapshot | yes |
| `row_added` | After `add_repeatable_row` increments | `{section_id, new_index}` | yes |
| `repeatable_section_entered` | After `enter_repeatable_section` OR auto-pin from `add_repeatable_row` | `{section_id, intent, row_index}` | yes (added last session) |
| `repeatable_section_exited` | After `exit_repeatable_section` | `{section_id}` | needs emit |
| `validation_rejection` | When `update_field` returns rejection or cross-field gate fails | `{section_id, field_id, repeatable_index, code, reason_human}` | partial — unify path |
| `schema_drift_detected` | When `[SCREEN]` payload's schema_version != session schema_version | `{expected_version, observed_version}` | not yet |
| `field_skipped_warning` | When agent defers a required field across two section transitions | `{section_id, field_id, reason}` | not yet |
| `step_completed` | At successful `advance_step` | `{webhook_delivered}` | yes |

**4. Cross-cutting test additions**
- `tests/test_tools.py`: contract test that every successful `_update_field` emits exactly one `field_updated` AND one `state` event (currently the second is implicit).
- `tests/test_advance_step.py` (new file): test the positive-affirmation regex gate and that `step_completed` fires before WS close.
- `tests/test_screen_context.py`: test that schema_version mismatch in incoming `[SCREEN]` triggers `schema_drift_detected`.

### Flutter handoff (informational — out of this PRD's execution scope but blocking E2E)

`FLUTTER_DEV_HANDOFF.md` Issues #18–#22 already document the Flutter side. The server changes here MUST be additive — every existing WS event stays as-is, new events arrive alongside.

---

## Testing Decisions

### What makes a good test in this codebase

- Test the **dispatcher and prompt outputs**, not the Gemini call itself.
- Use the existing `FakeRedis` fixture pattern from `test_tools.py` — fast, deterministic, no network.
- Use `monkeypatch.setattr(tools_module, "validate_step_complete", ...)` for cross-field validator stubs (existing pattern).
- For `_handle_screen_state`, follow `test_gemini_live.py`'s pattern: `MagicMock` for the WS, `AsyncMock` for the Gemini session, real `FormStateRepo` against `FakeRedis`.
- Test EXTERNAL behaviour: events emitted, state mutations, rejection codes — not internal call counts unless they're contractually load-bearing (e.g., "exactly one webhook fire on step complete").

### Modules to test

| Module | Test type | Existing prior art |
|---|---|---|
| `_advance_step` positive-affirmation gate | Unit | `test_advance_step_rejects_short_confirmation_transcript` |
| `field_updated` event emit | Unit | `test_update_field_happy_path` (extend) |
| `_handle_screen_state` schema drift | Unit | `test_v2_screen_state_*` family |
| `pending_required_labels` injection | Unit on `prompt_builder.py` | `test_prompt_builder.py` (existing) |
| Graceful close ordering | Unit on `gemini_live.py` | `test_gemini_live.py` (extend) |

Coverage target: every new branch covered. No integration tests against live Gemini in this slice — covered separately by manual QA against the handoff plan.

---

## Out of Scope

- **Flutter implementation** of the new event types — handed off via `FLUTTER_DEV_HANDOFF.md`. This PRD only ships the server-side contract.
- **Schema migration tooling** — the `schema_drift_detected` event surfaces the problem; it does NOT auto-resolve drift. Resolution is a separate refresh-and-retry loop owned by the Flutter app.
- **Webhook retry policy changes** — the existing 3-retry exponential backoff in `services/webhook.py` stays as-is.
- **Voice latency tuning** — Gemini Live thinking level / VAD sensitivity is a separate optimisation track.
- **Auth / RLS / multi-tenant isolation** — already covered by `assert_session_owner` and Phase B of the onboarding service. This PRD does not modify auth.
- **Case Note Review / Case Review service** — different service, different PRD.
- **NDIS source-of-truth schema sync** — schemas live in `fixtures/`; the upstream backend's schema repo is the canonical source and is out of scope here.

---

## Further Notes

### Why this delivery is contract-first, not feature-first

The forensic audit showed that every reported bug had the same shape: **two parallel views of "what is filled / what is missing / what was rejected" had drifted apart**. Fixing each bug locally would just push the drift to a new symptom. The contract-first approach (one server-authoritative event stream, consumed by both the Gemini prompt and the Flutter UI) eliminates the drift surface itself.

### Sequencing

1. Backend prompt + tool changes (Stories 12, 15, 16) — pure server, ship first, test in isolation.
2. Backend new event types (Stories 17–22) — additive, ship behind the existing `_emit` channel, no client breakage.
3. Flutter integration — separate handoff, blocked only by step 2 being merged.
4. End-to-end QA — replay the original 7-issue forensic report against a real session and confirm zero regressions.

### Rollback story

Each event type emit is gated by a try/except that logs and continues. A single bad payload format never kills the session. The only hard contract is `step_completed` ordering for graceful close — that one needs a feature flag (`SENA_AI_ONBOARDING_GRACEFUL_CLOSE_ENABLED`, default `true`, env-overridable) so we can disable if it causes WS hangs in production.

### Verification checklist (end-to-end)

- [ ] Start a fresh session, confirm `[LIVE_STATE_JSON].participant_display_name` flows into the first utterance.
- [ ] Walk a participant through the personal information step out of order in voice — confirm the agent corrects the sequence.
- [ ] Try to call `advance_step` with confirmation `"hmm"` — must reject.
- [ ] Provide `testmail.com` as email — must be re-asked.
- [ ] Provide `123` as NDIS number — must be re-asked.
- [ ] Say "I manage it myself" — confirm `update_field("plan_info", "plan_management", "Self Managed")` and the Flutter UI populates.
- [ ] Ask "what else do you need?" — agent must list every outstanding field by label.
- [ ] Add an emergency contact — confirm `row_added` + `repeatable_section_entered` + `field_updated` events arrive in order.
- [ ] Trigger a stale schema scenario (mock WS sends old schema_version) — confirm `schema_drift_detected` event.
- [ ] Complete a step — confirm one-sentence readback before `advance_step`, `step_completed` event, then graceful WS close (code 4000).

### Critical files

- `sena-ai/services/onboarding/src/onboarding/prompts/onboarding_system.md`
- `sena-ai/services/onboarding/src/onboarding/services/prompt_builder.py`
- `sena-ai/services/onboarding/src/onboarding/services/tools.py`
- `sena-ai/services/onboarding/src/onboarding/services/gemini_live.py`
- `sena-ai/services/onboarding/src/onboarding/services/screen_context.py`
- `sena-ai/services/onboarding/src/onboarding/api/ws_routes.py`
- `sena-ai/services/onboarding/tests/test_tools.py`
- `sena-ai/services/onboarding/tests/test_gemini_live.py`
- `sena-ai/services/onboarding/FLUTTER_DEV_HANDOFF.md`
