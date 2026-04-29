# PRD — SENA Onboarding Voice API: Re-Plan Aligned to Flutter Reality

**Status:** Verified — 15/16 items implemented (2026-04-29). One gap: close code 4011 (`policy_block`).
**Owner:** Backend AI layer (`SENA_AI/sena-ai/services/onboarding/`)
**Date:** 2026-04-29
**Replaces:** v1 of this file (frozen below as historical context)
**Related:** `.planning/ONBOARDING_VOICE_API_PLAN.md`, `HANDOFF_VOICE_ONBOARDING.md`, `lib/features/voice_onboarding/**` (Flutter Track-A integration), `lib/core/voice_schemas/**`

## Implementation Verification (2026-04-29)

Audit run against live backend code. All module-level checks passed except one.

| # | Module | Check | Status |
|---|--------|-------|--------|
| 1 | `models/schema_spec.py` | `StepSchema.voice_coverage: list[str]` | ✅ |
| 2 | `models/schema_spec.py` | `StepSchema.voice_repeatable_sections: list[str]` | ✅ |
| 3 | `models/form_state.py` | `repeatable_rows` dict + `increment_repeatable_row()` | ✅ |
| 4 | `core/settings.py` | `voice_coverage_enforced` + `field_apply_log_level` | ✅ |
| 5 | `services/coverage.py` | `is_eligible`, `is_repeatable_eligible`, `coverage_paths` | ✅ |
| 6 | `services/field_apply.py` | `build_envelope()` | ✅ |
| 7 | `services/screen_context.py` | `ScreenStateV2` + `ScreenStateV2Message` + `from_v1()` adapter | ✅ |
| 8 | `services/gemini_live.py` | `screen_state_v2` dispatch (lines 206–257) | ✅ |
| 9 | `services/gemini_live.py` | v1 `screen_state` adapter path (same handler, `version=1`) | ✅ |
| 10 | `services/tools.py` | `add_repeatable_row` tool + `row_added` emit | ✅ |
| 11 | `services/tools.py` | `field_apply` envelope emit after `update_field` (lines 320-329) | ✅ |
| 12 | `services/prompt_builder.py` | `__VOICE_COVERAGE_SECTION__` substitution (line 83) | ✅ |
| 13 | `api/ws_routes.py` | `coverage` list in ready envelope | ✅ |
| 14 | `fixtures/schema_personal_information.json` | `voice_coverage` array (5 paths) | ✅ |
| 15 | `fixtures/schema_ndis_plan_details.json` | `voice_coverage` array (4 paths) | ✅ |
| 16 | `api/ws_routes.py` or `gemini_live.py` | Close code **4011** (`policy_block`) | ❌ NOT IMPLEMENTED |

**Note on screen_state_v2 routing:** dispatch lives in `gemini_live.py` (not `ws_routes.py`). Architecturally correct — WS route owns connection lifecycle; Gemini session owns message semantics.

### Remaining work
- [ ] Implement close code **4011** — fire when grounding is off and user asks a grounding-required policy question. Small addition to `gemini_live.py`.

---

## Why this PRD exists (v2 motivation)

v1 of this PRD shipped (`screen_state` JSON + resumption handles + grounding flag + OpenAPI/Postman/WS_PROTOCOL.md) under the assumption that the Flutter team would write the integration **against our contract**. We now have read-only access to the actual Flutter onboarding code and the partly-built `voice_onboarding` feature. Three things changed:

1. **Flutter already implemented Track-A voice integration** for step 1 only, with clean-architecture chain (`features/voice_onboarding/{data,domain,presentation}`), `record` for PCM16 16 kHz capture, `flutter_pcm_sound` for 24 kHz playback, `web_socket_channel` transport, `permission_handler`. A `VoiceMicFab` is already mounted on `ClientStep1Screen`, a `ClientStep1VoiceSink` bridges voice → step controller, and a `VoiceSessionController` manages session lifecycle (`VoiceSessionStatus` = idle/starting/active/ending/error).

2. **The voice schema in Flutter is narrow on purpose.** `lib/core/voice_schemas/step1_personal_info_schema.dart` declares: *"Track-A scope: scalar text/date fields only. Address, emergency contacts, and profile picture are intentionally omitted from the mapping — the user will fill those manually for the integration testing build."* No voice schemas exist yet for steps 2–5. v1's PRD treated all five steps as symmetric; that was wrong.

3. **The shipped backend `screen_state` contract is too generic for what Flutter naturally emits.** Flutter's UI is GetX-reactive: focused field is `FocusNode.hasFocus`, filled/empty/invalid map to Rx fields and validators, repeatable row counts are `RxList.length`, conditional toggles (`interpreter_required`, `plan_management = PLAN_MANAGED`) drive `visible_if`. The current `{current_screen, visible_fields, prefilled, app_context}` shape forces Flutter to invent strings to populate those keys. We should redesign the contract around the signals Flutter has natively.

This PRD re-plans the implementation to align with the actual frontend, then re-implements. v1 code stays in tree as a starting point but the contract, prompt builder rendering, harness, and Flutter handoff all change.

## Problem Statement

The participant taps the mic on Step 1 of onboarding. The agent should:

- Know which **section** the participant is currently looking at within the step (basics vs home address vs emergency contacts) so it doesn't ask about the wrong thing.
- Know which **fields are already filled, empty, or invalid** so it skips what's done and revisits errors.
- Know how many **repeatable rows** exist (emergency contacts, NDIS goals, fund allocations, medications, allied health) so it can ask "do you want to add another?" without inventing rows that don't exist.
- Know the state of **conditional toggles** (`interpreter_required`, `plan_management`, `support_coordinator_present`) so it asks the right follow-up questions.
- Reflect captured values back into the **GetX controller** for that step so the user sees them appear on screen — not just in backend FormState.
- Survive a 10-second network blip without losing the conversation or the form.

Today: the backend ships v1 of all of the above as a generic context blob; Flutter has built a Track-A voice integration for step 1 (scalars only); they don't speak the same dialect. Steps 2–5 have zero voice support. There is no documented per-step rollout plan.

## Solution

Restructure the contract and the rollout in two layers:

**Layer 1 — Frontend-aligned WS protocol (this PRD's main delivery).**

- Replace v1's generic `screen_state` with a **typed, GetX-shaped** message: `step_id`, `focused_section`, `focused_field`, `field_status` (filled/empty/invalid per dotted-path), `repeatable_rows` (counts), `ui_flags` (conditional toggles).
- Add a new envelope `field_apply` (server → client) so the agent can push captured field values back into the step controller via `VoiceFieldSink`. This is what `client_step1_voice_sink.dart` is already wired to receive, but the server-side emit shape was never finalized.
- Keep `field_updated` as a coarse event for transcripts/UI badges, but `field_apply` is the deterministic write path.
- Keep `resumable` + close 4010 + grounding flag from v1 — those don't change.

**Layer 2 — Per-step voice coverage matrix.**

- Step 1 (personal_information): scalars only this milestone (matches Track-A). Address, emergency contacts, profile picture stay manual until Track-B.
- Steps 2–5: backend schema fixtures stay; Flutter integration is **out of scope** for this PRD beyond exposing a stub `VoiceStepConfig` for each. Backend coverage matrix in `WS_PROTOCOL.md` documents which fields are voice-eligible per step.
- Repeatable rows (`emergency_contacts`, `ndis_plan_goals`, `fund_allocations`, `support_schedule`, `medications`, `medical_history`, `allergies`, `allied_health`): backend exposes a new tool `add_repeatable_row` (currently shoehorned into `update_field`); first wired for step 3 NDIS goals only as the smallest test case.

## User Stories

### Participants

1. As a participant on Step 1, I want the agent to know I just focused the *email* field, so it asks me about email next instead of guessing.
2. As a participant, I want fields I've already typed to be skipped by the agent, so I don't repeat myself.
3. As a participant, I want fields the validator marked invalid (e.g. badly-formatted phone) to be re-asked specifically, so I can correct them by voice.
4. As a participant on Step 3, I want to add NDIS goals by saying "add another goal: …" and have the row appear on screen, so I don't have to tap "+ add" between dictations.
5. As a participant, I want the agent to acknowledge that I checked "interpreter required" and ask which language, so I don't have to volunteer that without prompting.
6. As a participant, I want the field I just dictated to appear in the form before the agent moves on, so I can confirm it visually.
7. As a participant, I want a 10-second network blip to recover the conversation, not restart it.
8. As a participant on Steps 2–5, I want a clear "voice not yet supported for this step" indicator if I tap the mic, so I'm not confused by an inert button.
9. As a participant, I want the agent to give me current NDIS policy info when grounding is enabled, so I get accurate answers about plan management.
10. As a participant, if I describe self-harm or abuse, I want it escalated regardless of network/resume state, so safety isn't dropped.

### Flutter app developers (this is the primary change vs v1)

11. As a Flutter dev, I want the WS server to accept a `screen_state` payload built from `Get.find<ClientStep1Controller>()` Rx fields plus `FocusNode.hasFocus`, so I emit it from `ever()` workers without a transformation layer.
12. As a Flutter dev, I want the server to emit `field_apply` envelopes with `{section_id, field_id, value, source: "voice"}` so I can route them through the existing `VoiceFieldSink` interface to the right controller setter.
13. As a Flutter dev, I want repeatable rows addressed by `{section_id, row_index, field_id}` so I don't invent dotted-path conventions on the client.
14. As a Flutter dev, I want the schema fixture's `visible_if` semantics honored by the agent, so toggling `interpreter_required` on the UI causes the agent to immediately follow up about language without me sending a second message.
15. As a Flutter dev, I want a documented "voice coverage matrix" listing which fields per step are voice-eligible, so my mic-FAB can disable itself or show a tooltip on unsupported sections.
16. As a Flutter dev, I want the WS to remain backwards-compatible with the v1 `screen_state` message for one release window, so the rollout is non-breaking.
17. As a Flutter dev, I want a tighter `ready` envelope that includes the *coverage matrix* for the current step, so I render the FAB enabled-state correctly without out-of-band config.
18. As a Flutter dev, I want resumption handles surfaced through the `VoiceSession` entity (already in `domain/entities/voice_session.dart`), so I don't add new state.
19. As a Flutter dev, I want grounding-disabled to be the user-visible default with no UI surface for the toggle in v2, so we don't ship a feature compliance hasn't approved.
20. As a Flutter dev, I want clear close codes with reason strings for: invalid resume (4010), session locked (4009), not found (4004), policy block (new — 4011), so I can map each to a snackbar.

### Backend developers (this repo)

21. As a backend dev, I want `screen_state` validation in a deep, pure module that consumes the *new* shape but normalizes v1 input through an adapter, so we ship one parser, not two.
22. As a backend dev, I want a new `field_apply_emitter` module that knows how to render a tool-call result into `{section_id, field_id, value}` envelopes, so the WS handler stays a thin dispatcher.
23. As a backend dev, I want the prompt builder's "Screen Context" section rewritten to consume the richer signals (focused/filled/empty/invalid/rows/flags), so Gemini gets actionable structure rather than a flat text dump.
24. As a backend dev, I want a per-step `voice_coverage` config in each fixture file (ids of fields the agent is allowed to ask for) so the agent doesn't hallucinate questions about non-voice fields.
25. As a backend dev, I want one new tool `add_repeatable_row(section_id)` so growing emergency_contacts / ndis_goals / fund_allocations / medications is one tool call, not synthesized from `update_field`.
26. As a backend dev, I want all schema fixtures to declare which sections are repeatable and what their item-fields are, so the prompt builder and tool dispatcher don't hardcode section names.
27. As a backend dev, I want the test harness updated to a "GetX-like" payload shape (focused/filled/empty/flags) so manual QA mirrors what Flutter actually sends.
28. As a backend dev, I want every new and changed module unit-tested against external behavior — pure modules with case tables, Redis-backed modules with `fakeredis`, integration tests with a stubbed `GeminiLiveSession`.

### Operators / org admins / compliance

29. As an org admin, I want webhook-once semantics preserved across resume + add_repeatable_row + field_apply chains, so completion isn't double-billed.
30. As compliance, I want grounding off by default and field_apply payloads logged at debug level only, so PII doesn't sit in production logs.
31. As compliance, I want resumption handles to remain opaque single-use UUIDs (unchanged from v1), so handle exposure can't leak session_id.

### QA

32. As QA, I want the harness to simulate focused-field changes with a dropdown selector for `focused_section` + `focused_field`, so I can rehearse Gemini's reaction.
33. As QA, I want a "fake repeatable row" button in the harness (add/remove rows) so I can test the agent's add_repeatable_row tool without a real Flutter app.
34. As QA, I want a coverage-matrix toggle in the harness that masks ineligible fields, so I can verify the agent never asks for an out-of-scope field.

## Implementation Decisions

### Module boundaries (changes from v1 in **bold**)

| # | Module | Type | Responsibility |
|---|--------|------|---------------|
| 1 | `services/screen_context.py` | **Rewrite** | New Pydantic model `ScreenStateV2`: `step_id`, `focused_section`, `focused_field`, `field_status` (dict[dotted_path, "filled"\|"empty"\|"invalid"]), `repeatable_rows` (dict[section_id, int]), `ui_flags` (dict[str, str\|bool]). Adapter `from_v1(legacy: ScreenStateMessage) → ScreenStateV2` to keep one parser. New `render_injection_text` produces structured multi-line `[SCREEN]` block. |
| 2 | `services/field_apply.py` | **New, pure** | Build `{type:"field_apply", section_id, field_id, row_index?, value, source:"voice", confidence}` envelope from a tool-call result. Validate that the field is in the step's `voice_coverage` allowlist. |
| 3 | `services/coverage.py` | **New, pure** | Read `voice_coverage` array from the loaded `StepSchema` fixture. Provide `is_eligible(section_id, field_id) → bool`. Used by tool dispatcher and by `field_apply.py`. |
| 4 | `services/tools.py` | **Modify** | Add 5th tool `add_repeatable_row(section_id)`. `update_field` gains `row_index` arg for repeatable sections. After every successful mutation, emit `field_apply` envelope (not just `field_updated`). |
| 5 | `services/prompt_builder.py` | **Modify** | "Screen Context" section consumes ScreenStateV2 directly. Add a new "Voice Coverage" section listing the allowlisted fields per current step. |
| 6 | `services/grounding.py` | Unchanged from v1 | `build_live_tools(function_decls, *, grounding_enabled)` — keep. |
| 7 | `services/resumption.py` | Unchanged from v1 | `issue_handle / redeem_handle / build_replay_context` — keep. |
| 8 | `services/gemini_live.py` | **Modify** | `inject_text_turn` — keep. Wire `add_repeatable_row` declaration into `build_live_tools`. |
| 9 | `api/ws_routes.py` | **Modify** | Accept both `screen_state` (v1) and `screen_state_v2` (v2) types via the adapter. Emit `field_apply` envelopes from tool dispatcher results. New close code 4011 (`policy_block`) for grounding-required-but-disabled-with-policy-question. `ready` envelope gains `coverage` (list[dotted_path]) for the current step. |
| 10 | `api/routes.py` | Unchanged from v1 | OpenAPI metadata pass already done. |
| 11 | `core/settings.py` | **Modify** | Add `field_apply_log_level: str = "DEBUG"`, `voice_coverage_enforced: bool = True`. Keep v1 settings. |
| 12 | `models/schema_spec.py` | **Modify** | Add `StepSchema.voice_coverage: list[str]` (dotted-paths of voice-eligible fields). Add `RepeatableConfig` already exists — verify and reuse. |
| 13 | `fixtures/schema_*.json` | **Modify** | Add `"voice_coverage": [...]` array to each. Step 1: scalars only (matches Track-A). Steps 2–5: empty list initially (no voice yet) — they're documented as "schema-only, no voice rollout in this PRD". |
| 14 | `prompts/onboarding_system.md` | **Modify** | Rewrite "Screen Context" section. Add "Voice Coverage" section with rule: *only ask for fields in the coverage list*. Keep "Resume Context" + "Grounding" as-is. |
| 15 | `test_harness.html` | **Modify** | Replace flat JSON editor with structured form: step_id selector, focused_section dropdown (populated from schema), focused_field dropdown (populated by section), field_status toggles, repeatable_rows numeric inputs, ui_flags checkboxes. Coverage indicator beside each field. |
| 16 | `docs/WS_PROTOCOL.md` | **Modify** | Document v2 message shape, the coverage matrix, the v1→v2 adapter window, the `field_apply` envelope, the `policy_block` close code, and per-step voice rollout phases. |
| 17 | `docs/postman_collection.json` | Unchanged | REST endpoints didn't change. |

### `screen_state_v2` contract (server-facing)

```json
{
  "type": "screen_state_v2",
  "data": {
    "step_id": "personal_information",
    "focused_section": "basics",
    "focused_field": "email",
    "field_status": {
      "basics.full_name": "filled",
      "basics.email": "empty",
      "basics.phone": "invalid",
      "basics.date_of_birth": "filled",
      "basics.interpreter_required": "filled"
    },
    "repeatable_rows": {
      "emergency_contacts": 0,
      "ndis_plan_goals": 0
    },
    "ui_flags": {
      "interpreter_required": true,
      "plan_management": "PLAN_MANAGED"
    }
  }
}
```

- `focused_section` / `focused_field`: nullable; emitted on focus change (Flutter `FocusNode.addListener`).
- `field_status` keys: dotted-paths `section_id.field_id` for non-repeatable, `section_id.row_index.field_id` for repeatable.
- Idempotency: identical consecutive payloads dropped server-side via deep-equal hash (carries over from v1).
- Size cap: 8 KB (`screen_state_max_bytes`, unchanged).
- Unknown keys ignored.

### v1 → v2 adapter (one release window)

- v1 message arrives → adapter fills `step_id` from session, sets `focused_section = data.current_screen`, `field_status` defaults to `filled` for everything in `data.prefilled`. Other v2 fields default to empty.
- Adapter is removed in the milestone after v2 ships.

### `field_apply` envelope (server → client, **new**)

```json
{
  "type": "field_apply",
  "section_id": "basics",
  "field_id": "full_name",
  "row_index": null,
  "value": "John Smith",
  "source": "voice",
  "confidence": 0.95
}
```

- Emitted after every successful `update_field` tool call.
- Flutter side consumes via existing `VoiceFieldSink` (defined in `lib/core/voice_schemas/voice_field_sink.dart`) which routes by `section_id` + `field_id` to controller setters.
- `field_updated` envelope kept for backwards compat (transcripts/UI badges).

### `add_repeatable_row` tool (**new**)

```python
add_repeatable_row(section_id: str) -> {ok: bool, new_row_index: int}
```

- Validates `section_id` is `repeatable=True` in the loaded `StepSchema`.
- Increments `FormState.repeatable_rows[section_id]` (new field on FormState).
- Emits envelope: `{"type":"row_added", "section_id":"ndis_plan_goals", "new_row_index": 1}`.
- Allowed sections (v2): `ndis_plan_goals` only. Other repeatable sections — emergency_contacts, fund_allocations, support_schedule, medications, medical_history, allergies, allied_health — declared in schema but not voice-eligible until later.

### Voice coverage matrix (per step, v2)

| Step | step_id | Voice-eligible (this PRD) | Manual-only |
|------|---------|---------------------------|-------------|
| 1 | `personal_information` | basics.full_name, basics.email, basics.phone, basics.date_of_birth, basics.gender, basics.bio, basics.preferred_language, basics.interpreter_required, basics.interpreter_language | home_address.*, service_location.*, emergency_contacts.* |
| 2 | `participant_requirements` | (empty — schema only, no voice) | all |
| 3 | `ndis_plan_details` | ndis_plan.ndis_number, ndis_plan.plan_start_date, ndis_plan.plan_end_date, ndis_plan.plan_management; **add_repeatable_row** for ndis_plan_goals | fund_allocations.*, support_schedule.* |
| 4 | `documents` | (empty — uploads never voice) | all |
| 5 | `medical_information` | (empty — schema only, no voice) | all |

The matrix is enforced server-side via `coverage.is_eligible()`; the agent is told via the prompt and fails closed if it tries to call `update_field` on an ineligible field.

### Prompt builder changes

System prompt gains two new sections (rendered only when their inputs are present):

```
## Screen Context
The user is currently on step "{step_id}".
Their focus is on section "{focused_section}", field "{focused_field}".
Field status:
  - Filled: basics.full_name, basics.date_of_birth, basics.interpreter_required
  - Empty: basics.email, basics.bio
  - Invalid: basics.phone (ask them to repeat the number)
Repeatable rows: ndis_plan_goals=0
UI flags: interpreter_required=true, plan_management=PLAN_MANAGED

## Voice Coverage
Only ask the user for these fields. Do NOT ask about anything else:
  - basics.full_name (text)
  - basics.email (email)
  - basics.phone (phone)
  - basics.date_of_birth (date)
  - basics.interpreter_language (text, only when interpreter_required=true)
```

`prompt_version` bumps from `v1` → `v2`.

### WS envelope changes (server → client)

| Envelope | Status | Shape |
|----------|--------|-------|
| `ready` | **Modify** | adds `coverage: list[str]` (dotted paths of voice-eligible fields for this step). |
| `field_apply` | **New** | see above. |
| `row_added` | **New** | `{type, section_id, new_row_index}`. |
| `field_updated` | Unchanged | kept for transcripts/UI badges. |
| `state` | Unchanged | full FormState after any mutation. |
| `step_completed` | Unchanged | webhook fired, WS closes (no resumption handle issued). |
| `resumable` | Unchanged | issued before any non-completion close. |
| `escalated` | Unchanged | safety event. |
| `error` (`policy_block`) | **New** | issued + close 4011 if grounding-required policy question hit while grounding is off. |

### WS close codes (additions)

| Code | Meaning |
|------|---------|
| 4011 | `policy_block` — user asked a policy question that needs grounding, but grounding is disabled. |

### Settings additions

```python
# core/settings.py
voice_coverage_enforced: bool = True            # SENA_AI_ONBOARDING_COVERAGE_ENFORCED
field_apply_log_level: str = "DEBUG"            # SENA_AI_ONBOARDING_FIELD_APPLY_LOG
```

### Architectural decisions (deltas vs v1)

- **Contract owner shifts to Flutter's emitted shape.** v1 invented a generic shape; v2 codifies what Flutter naturally emits (focused fields, Rx-derived statuses, RxList lengths, conditional toggles).
- **Coverage matrix is server-enforced.** Agent attempts to set out-of-scope fields → tool returns `{ok: false, reason: "out_of_coverage"}`. Closed-loop safety against hallucinated questions.
- **Repeatable rows become first-class.** New tool, new envelope, FormState carries row counts, prompt builder renders counts. Without this, growing emergency contacts / NDIS goals / medications by voice is a bag-on-the-side hack.
- **One adapter, one release window.** No long-lived dual contract. v1 path is parser-level, not protocol-level.
- **No breaking change to REST.** Session create/state/complete unchanged. WS-only delta.

## Testing Decisions

### Bar (unchanged from v1)

External-behavior tests at module seams. Pure modules → input → output case tables. Redis-backed modules → fakeredis with public-API assertions. WS routes → integration with stubbed `GeminiLiveSession` asserting envelopes + close codes + Redis side-effects.

### Modules with required test coverage

| Module | Test type | Cases |
|--------|-----------|-------|
| `screen_context.py` (rewrite) | Unit (pure) | (a) v2 valid payload → `[SCREEN]` block matches snapshot. (b) v1 legacy payload via adapter → equivalent v2 model. (c) oversize → `screen_state_too_large`. (d) malformed → `screen_state_invalid`. (e) unknown keys ignored. (f) idempotency hash equality. |
| `field_apply.py` (new) | Unit (pure) | (a) eligible field → envelope shape correct. (b) ineligible field → raises / returns None when `voice_coverage_enforced=true`. (c) row_index passed through for repeatable. (d) confidence clamped 0..1. |
| `coverage.py` (new) | Unit (pure) | (a) eligible / ineligible lookups. (b) repeatable item-field lookup. (c) empty coverage list → all ineligible. |
| `tools.py` (modify) | Unit | (a) `add_repeatable_row` happy path increments count, emits `row_added`. (b) on non-repeatable section → returns `{ok:false}`. (c) `update_field` with `row_index` for repeatable section persists correctly. (d) post-mutation `field_apply` envelope is built. |
| `resumption.py` | Unit + fakeredis | Unchanged from v1 (regression). |
| `grounding.py` | Unit (pure) | Unchanged from v1 (regression). |
| `prompt_builder.py` | Snapshot | Output diffs across {grounding off/on} × {fresh, with v2 screen state, with resume context} × {coverage list non-empty/empty}. |
| `ws_routes.py` | Integration | (a) Existing happy path regression. (b) Send v2 `screen_state_v2` → `[SCREEN]` block injected (assert via stub GeminiLiveSession received text). (c) Send v1 `screen_state` → adapter hits, equivalent injection. (d) Tool call `update_field` → `field_apply` envelope sent to client. (e) Tool call `add_repeatable_row` → `row_added` envelope. (f) Tool call out-of-coverage → tool returns ineligible, no envelope. (g) Reconnect with handle → unchanged from v1. (h) New `policy_block` close code path. (i) `ready` envelope contains `coverage` list. |
| `models/form_state.py` (modify) | Unit | repeatable_rows count increments and serializes. |
| `models/schema_spec.py` (modify) | Unit | `voice_coverage` parses; visible_if + repeatable still parse. |

### Coverage targets (unchanged from v1)

- New pure modules: 100% line.
- `resumption.py` / `coverage.py`: 100% line + branches.
- `ws_routes.py` new branches: 100%.
- Snapshot tests committed alongside prompt-builder changes.

## Out of Scope

- **Flutter / Dart code edits.** Read-only reference. Backend ships the contract; Flutter team consumes it. The hook (`.claude/hooks/guard-write-path.sh`) blocks writes outside `SENA_AI/`.
- **Voice rollout for steps 2, 4, 5.** Schema fixtures gain empty `voice_coverage` arrays — they participate in session creation and harness, but no fields are voice-eligible. Future PRD.
- **Voice rollout for repeatable sections beyond NDIS goals.** Emergency contacts, fund allocations, medications, etc. — schemas declared but not voice-eligible in this PRD.
- **JWT auth.** Stays dev-header.
- **Per-tenant grounding override.** Single global flag (unchanged from v1).
- **Multi-step session within one WS.** Still one step per WS.
- **Vertex Search / custom RAG grounding.** Still Google Search only when grounding flag is on.
- **JSON Schema / AsyncAPI artifact for WS.** Markdown stays canonical.
- **Removing the v1 adapter** — done in the milestone after v2 ships, not this one.

## Further Notes

### Implementation sequencing (recommended)

1. **Schema + coverage first.** `models/schema_spec.py` + fixtures + `coverage.py` + tests. No behavior change yet, just structure.
2. **`field_apply` + tools rewrite.** New tool, new envelope, modified `update_field`. Tests against stubbed Gemini.
3. **`screen_context.py` rewrite + adapter.** Both shapes parse, snapshot of injection text.
4. **Prompt builder rewrite.** Snapshot diffs.
5. **`ws_routes.py` wiring.** Dispatch v1+v2, emit field_apply / row_added, ready envelope coverage list, close code 4011.
6. **Harness rewrite.** Structured form for v2 payload + repeatable-row simulator + coverage indicator.
7. **Docs.** `WS_PROTOCOL.md`, HANDOFF, voice coverage matrix, per-step rollout phases.

Each step ships as one PR with its own tests and `.claude/issues-solved/` entries if anything bites.

### Risks

- **Token budget** — richer `[SCREEN]` block + voice coverage section grows the system prompt. Mitigation: cap field_status entries at ~32, render only changed paths if size becomes a concern.
- **Coverage drift** — adding new voice-eligible fields requires fixture edit + tool prompt update. Mitigation: a single `voice_coverage` list per fixture is the only place to look.
- **Adapter half-life** — keeping v1+v2 dual-parsing past one release invites bug rot. Mitigation: hard removal date in the PRD that ships v2 to staging.
- **`field_apply` race with manual edits** — user types in the field while voice writes it. Mitigation: client-side, manual edits win; server is fire-and-forget for `field_apply`. Documented in `WS_PROTOCOL.md`.

### Done criteria

- All module test suites green (incl. v1 regression: 36/36 + 48/48).
- Snapshot tests for prompt builder reviewed and committed.
- `[SCREEN]` block renders correctly in harness for every (focused_section, focused_field, field_status, rows, flags) combination of step 1.
- `add_repeatable_row` exercised end-to-end with NDIS goals via harness.
- v1 `screen_state` adapter test passes (one release window).
- `WS_PROTOCOL.md` v2 reviewed by Flutter dev (informally — they're not blocking).
- HANDOFF_VOICE_ONBOARDING.md updated with the new contract + per-step coverage matrix.
- Task #9 (re-implementation milestone) marked DONE on completion.

---

## Appendix A — Frontend reality (read-only reference)

These paths inform the contract; **do not edit them**.

```
sena-mobile/lib/features/voice_onboarding/
├── data/
│   ├── datasources/
│   │   ├── voice_audio_player.dart        # flutter_pcm_sound 24kHz playback
│   │   ├── voice_onboarding_remote_datasource.dart  # REST: POST /v1/onboarding/session
│   │   └── voice_onboarding_ws_client.dart # web_socket_channel transport
│   ├── models/
│   │   ├── form_state_model.dart
│   │   ├── step_schema_model.dart
│   │   ├── voice_event_model.dart         # {ready, user_said, agent_said, field_updated, state, …}
│   │   └── voice_session_model.dart       # carries session_id + ws_url + (future) resume handle
│   └── repositories/voice_onboarding_repository_impl.dart
├── domain/
│   ├── entities/
│   │   ├── form_state.dart
│   │   ├── step_schema.dart               # mirrors backend StepSchema
│   │   ├── voice_event.dart               # sealed union; VoiceStateUpdate, transcripts, etc.
│   │   └── voice_session.dart
│   ├── repositories/voice_onboarding_repository.dart
│   └── usecases/                          # create / send_audio / stream / stop / complete
└── presentation/
    ├── bindings/voice_session_binding.dart
    ├── controllers/voice_session_controller.dart  # VoiceSessionStatus enum
    └── widgets/
        ├── client_step1_voice_sink.dart   # routes field_apply → ClientStep1Controller setters
        └── voice_mic_fab.dart             # FAB on Step 1 only

sena-mobile/lib/core/voice_schemas/
├── voice_step_config.dart                  # abstract; defines schema + sink wiring
├── voice_field_sink.dart                   # interface for field_apply consumers
└── step1_personal_info_schema.dart         # Track-A: scalars only, no address/contacts/photo

sena-mobile/pubspec.yaml additions:
  record: ^6.2.0                            # PCM16 16kHz capture
  flutter_pcm_sound: ^3.3.3                 # PCM16 24kHz playback
  web_socket_channel: ^3.0.3
  permission_handler: ^11.3.1
```

Step screens:

```
sena-mobile/lib/features/client/presentation/dashboard/home/client_onboarding/
├── client_onboarding_step_config.dart
└── steps/
    ├── client_onboarding_step_scaffold.dart
    ├── step1_personal_details/  ← VoiceMicFab + ClientStep1VoiceSink mounted here
    ├── step2_requirements/
    ├── step3_ndis_plan/
    ├── step4_documents/
    ├── step5_medical/
    └── step_content/             # field-level UI per step
```

`step_id` strings used by Flutter (matching backend fixtures): `personal_information`, `participant_requirements`, `ndis_plan_details`, `documents`, `medical_information`.

## Appendix B — v1 PRD historical reference

v1 of this PRD shipped these capabilities (kept in tree, partially reworked here):

- Screen state injection via generic `{current_screen, visible_fields, prefilled, app_context}` JSON.
- Resumption handles (Redis GETDEL, opaque UUID, 600s TTL, close 4010).
- Google Search grounding behind `SENA_AI_ONBOARDING_GROUNDING_ENABLED=false`.
- OpenAPI metadata pass + `WS_PROTOCOL.md` + `postman_collection.json`.
- Test harness manual flows.

This PRD keeps resumption + grounding + OpenAPI/Postman docs untouched. It rewrites screen_context, prompt builder, harness, fixtures, tools, and `WS_PROTOCOL.md`. The v1 → v2 adapter exists for one release window so Flutter can migrate without a flag-day.
