# PRD: Validation Awareness, Sequencing Strictness, and Schema-Drift Discovery

## Problem Statement

When a participant uses voice to fill out their NDIS onboarding, three things go wrong that erode trust in the assistant:

1. **The assistant skips required fields and gets confused between sections.** It will jump from collecting the participant's own name straight to an emergency contact's name and treat them as the same field. It will mark a `*`-required field "complete" without ever asking. The order it walks the form does not match the schema, so participants either re-answer the same thing or leave required fields blank.
2. **The assistant accepts obviously bad data.** A participant can say their phone number is "12" or their date of birth is "January thirty-second" or their name is "asdfasdf" and the assistant nods along, calls `update_field`, and moves on. The frontend has validators that would have caught this, but the assistant never sees them. So the participant either has to come back and fix everything manually, or the bad data flows downstream.
3. **The frontend has no way to learn that the schema needs to grow.** A participant says "actually I have two emergency contacts" or "I'd like to add my evening routine" and the assistant either drops the request silently (when the section/field isn't repeatable, or doesn't exist in the schema), or adds a row but the frontend doesn't render it. The mobile dev team has no daily signal telling them "here are the fields users tried to give us that we don't have a place for."

Combined, the assistant feels capable in conversation but produces forms with skipped fields, junk values, and lost requests. Participants notice. Trust drops.

## Solution

The assistant becomes structurally incapable of skipping or scrambling required fields. The frontend's existing validators get a wire path so the assistant hears every failure and corrects course in the same turn. And every "new field" or "new section" attempt gets recorded so the schema can grow on real evidence rather than guesswork.

From the participant's perspective: the assistant always asks one required field at a time, in the order the form expects them, and never confuses your name with your emergency contact's name. When you give bad data — a half phone number, a future date of birth, a junk name — the assistant immediately tells you what's wrong and re-asks, in plain language, the way the form's error message would have phrased it. When you ask to add an emergency contact, the second contact card actually appears on screen. When you ask for something the form doesn't have ("add my evening routine"), the assistant tells you it's noted, the request is logged for the team, and offers to come back to it.

From the mobile dev's perspective: a single daily digest tells them exactly what users tried to give the assistant that the current schema couldn't accommodate. Instead of guessing what to build next, they read the digest.

## User Stories

1. As a **participant**, I want the assistant to ask me the required fields in the order they appear on the form, so that I don't get confused jumping between sections.
2. As a **participant**, I want the assistant to never confuse my name with my emergency contact's name, so that the form is filled correctly.
3. As a **participant**, I want the assistant to refuse to mark a required field complete without asking me, so that I don't reach the end of the step and discover a blank required slot.
4. As a **participant**, when I give a phone number with the wrong number of digits, I want the assistant to tell me "that needs ten digits" the moment I say it, so that I'm not surprised at the end of the step.
5. As a **participant** giving a date of birth, I want the assistant to flag dates in the future, dates that make me less than zero years old, or dates with impossible months/days, so that I cannot accidentally lock in nonsense.
6. As a **participant** with an unusual name, I want the assistant to accept it but flag low confidence, so that I get a chance to confirm rather than be auto-rejected.
7. As a **participant**, when I say "I have two emergency contacts," I want both rows to appear on the form before the assistant moves on, so that I see what I've authorised.
8. As a **participant**, when I ask the assistant to add a section that isn't in the form (e.g. "evening routine"), I want it to acknowledge the request, tell me it's been noted for the team, and continue with the next required field, so that my time isn't wasted but my request isn't dropped silently.
9. As a **participant**, when the assistant gets stuck because a field is read-only, I want it to say "the form has this locked" and move on, so that I'm not trapped in a loop.
10. As a **participant**, I want the assistant to re-prompt me with the exact error reason the form would have shown me, so that I don't get a generic "try again" with no explanation.
11. As a **participant**, when I say "the support worker's name is Jane," I want that to apply to the support-worker section, not to my own profile, so that the assistant doesn't mis-route fields.
12. As a **support worker** filling out forms with a participant, I want the assistant to verbalise which section it is currently in before each question, so that I can keep track when I'm not looking at the screen.
13. As a **mobile dev**, I want a daily digest of every field path the assistant attempted to update that didn't exist in the schema, so that I can grow the schema based on real participant requests.
14. As a **mobile dev**, I want the digest to also include every "new section" request, so that we know which structural additions are being asked for.
15. As a **mobile dev**, I want the validation contract documented in one place so that when I add a new validator on the frontend, I know exactly what payload to send the server so the assistant becomes aware of it.
16. As a **backend engineer**, I want the system prompt to include the next-required-field hint computed server-side, so that Gemini cannot miss it even if it ignored the schema order in earlier turns.
17. As a **backend engineer**, I want `update_field` to reject calls that target a field outside the currently-focused section without an explicit `section_id` confirmation, so that the assistant cannot accidentally bleed data across sections.
18. As a **backend engineer**, I want every rejection (validation, sequencing, unknown-field, unknown-section) to be a structured error returned to Gemini synchronously, so that the assistant can correct itself without breaking the conversation.
19. As a **product owner**, I want a metric for "fields skipped per completed step," so that I can tell whether the sequencing fix is actually working in production.
20. As a **product owner**, I want a metric for "validation failures surfaced to user," so that I can see how often the assistant catches bad data versus letting it through.
21. As a **QA tester**, I want a deterministic way to feed the assistant a known-bad value and assert it gets rejected, so that I can write regression tests.
22. As a **security reviewer**, I want assurance that validation rejection messages do not leak field-internal regex patterns or implementation details to the user, so that the assistant remains safe against probing.
23. As an **on-call engineer**, I want a single log line tagged `unknown_field_attempt` so that I can grep production logs for schema-drift signals during incident review.
24. As an **assistant prompt author**, I want a structured "current state of play" block in every system prompt that lists `next_required_field`, `current_section_id`, and `pending_validation_errors`, so that the model can never miss those three load-bearing facts.
25. As a **participant whose first language isn't English**, I want validation errors paraphrased in plain language not regex jargon, so that I can fix the issue without help.
26. As a **support worker on a slow connection**, I want validation errors to be a non-blocking conversational nudge, not a hard interrupt, so that the assistant doesn't keep cutting off the participant mid-sentence.
27. As a **frontend dev**, I want a single document that tells me which events I must emit, which payloads I must send, and which events I will receive — so that I can implement validation awareness in one PR rather than chasing pieces.

## Implementation Decisions

### Sequencing strictness

- The system prompt gains an explicit, non-negotiable rule: *walk required fields in schema order; never advance past a required field that has not been asked; before each question, name the section.* The rule is repeated in the live-state JSON's `next_required_field` hint, computed server-side from the schema and the current FormState.
- The dispatcher rejects `update_field` calls whose `section_id` does not match the focused-section hint unless the assistant explicitly passes a `cross_section_intent: true` flag. This prevents the "emergency contact name" → "participant name" leak.
- A new `next_required_field` server-side computation is added: it returns `(section_id, field_id, label)` for the first required field with an empty value, walking sections in declared order. The result is rendered into the system prompt and refreshed on every screen_state event.
- Repeatable sections get a special protocol: when the assistant enters a repeatable section, it must call a new `enter_repeatable_section(section_id, intent: "first" | "next")` tool that pins the focus to a specific row. All subsequent `update_field` calls inherit that row index until `exit_repeatable_section` is called. This eliminates the cross-row collision.

### Validation awareness (REVISED 2026-05-07)

**Decision change:** server-side validators are now **authoritative**, not a "soft" supplement. Every Step 1–6 validator that exists in the Flutter `lib/core/utils/validators.dart` is mirrored on the server, byte-equivalent in rule and error message, and runs **before** `update_field` writes to FormState. The frontend continues to validate (defense in depth) and continues to emit `validation_failed` WS events when its own validators fire — but the assistant no longer depends on those events to reject bad data. Round-trips are eliminated for any value the assistant captures by voice.

The authoritative reference for every validator's rule and error string is `.claude/client_onboarding_validations.md` — a field-by-field catalog that has been cross-checked against `lib/core/utils/validators.dart` (phone regex, DOB age-18, NDIS-9-digits, postcode-4-digits, full-name first+last, emergency-contact email uniqueness all confirmed identical). The server implementation MUST mirror that catalog exactly. When the catalog and the Flutter validator disagree, the catalog is canon and the Flutter validator is the bug.

How it works at the call site:

- `update_field` invokes a new `ServerValidator.validate(section_id, field_id, value, repeatable_index, formstate_for_cross_field)` BEFORE writing to FormState. The signature takes the surrounding FormState because some validators are cross-field (emergency-contact email uniqueness, plan-end-after-start, conditional-required-when-other-filled).
- On failure, validate returns `(rejection_code, reason_human, suggested_fix)`. The dispatcher returns this structured rejection to Gemini synchronously, so the model can re-prompt in the same turn.
- On success, the value is written; the bridge also clears any matching entry in the `pending_validation_errors` block.
- The bridge still pipes incoming `validation_failed` WS events from the Flutter app into Gemini (defense in depth) and writes them into `pending_validation_errors`. Gemini sees both server-side and client-side rejections through the same channel; deduplication is by `(section_id, field_id, repeatable_index)`.
- The system prompt is updated with explicit rules: read the validator's `reason_human` verbatim, never invent your own validation logic, never describe the rule in regex or technical language.

Cross-field invariants the server enforces (mirroring the Flutter cross-step rules section of the reference doc):

- Emergency contact email ≠ client email (Step 1).
- Emergency contact emails unique across all rows (Step 1).
- Service-location fields all-required-when-any-filled (Step 1).
- Plan end > plan start (Step 3).
- Plan-manager fields appear only when `plan_management = "Plan Managed"` — server validates conditional presence.
- Time slots within a support item: `end_time > start_time`, no overlap on the same day (Step 3).
- Medical-history row all-required-when-any-filled (Step 5).
- Allergy/medication/medical-history row caps (10 each).
- Schedule-of-supports cap (5), time-slots-per-day cap (5), morning/evening routine cap (12), NDIS goals cap (10), emergency contact cap (5).

### Server-side Validator Catalog (mirror of frontend)

The full per-field catalog lives in `.claude/client_onboarding_validations.md`. The server implementation organises validators into one module per onboarding step (1 through 6), exposing a single `validate_field(field_path, value, formstate)` entry point per step plus a `validate_step_complete(formstate)` aggregate that runs at the `/complete` boundary. The aggregate is the gate that fails closed: `/complete` cannot return success if `validate_step_complete` returns any failure.

Every validator has, at minimum:
- A stable `code` (e.g. `phone_invalid_format`, `dob_under_18`, `emergency_email_matches_client`).
- A `reason_human` string that exactly matches the AppStrings constant on the Flutter side. The reference doc lists the canonical text for each.
- An optional `suggested_fix` plain-language hint when there is a constructive next step.
- An optional `min`/`max`/`pattern`/`enum` machine-readable spec used by the soft-validator path so the server can produce the rejection without relying on a hardcoded match block per field.

Localisation note: `reason_human` is English in v1 (matching the current AppStrings). Locale handling stays out of scope.

PII safeguard: rejection logs include `(tenant_id, participant_id, section_id, field_id, code)`. They do NOT include `attempted_value` because rejected raw values can be sensitive (phone, DOB, name). The diagnostic value is the rule that fired, not the value that fired it.

### Schema-drift discovery

- Two new structured logs at INFO level:
  - `unknown_field_attempt` — fires whenever the assistant calls `update_field` on a `(section, field)` pair the schema does not declare. Payload: `{tenant_id, participant_id, attempted_section, attempted_field, attempted_value_shape, transcript_excerpt}`.
  - `unknown_section_request` — fires whenever the participant or assistant asks for a section that does not exist (detected by a new `request_unknown_section(section_id, label)` tool the assistant calls when stuck). Payload: `{tenant_id, participant_id, requested_section_label, transcript_excerpt}`.
- Both logs feed a daily digest job that aggregates by attempted name and produces a ranked list for the mobile dev team. Out of scope for v1; v1 just emits the logs reliably.
- The frontend gets a new server→client event `schema_drift_detected` with the same payload, so the mobile UI can render a "this would normally be available" hint to the participant without crashing.

### Repeatable-row visibility

- The existing `add_repeatable_row` tool and `row_added` event remain. Strengthening: a new `repeatable_section_entered` event fires the moment the assistant enters a repeatable section, even if no row has been added yet. This gives the frontend a chance to scroll to the section header. Today it only knows after a row is materialised.
- The system prompt forces the assistant to verbally announce repeatable-section entry: "Now I'll ask about your first emergency contact" — the audible cue prevents the "name confusion" symptom.

### Frontend handoff

- All the above is documented in a new addendum to the existing handoff doc. The addendum lives below the existing cross-screen-context addendum so the chronological build-up is visible.
- The handoff explicitly enumerates: WS events the frontend must emit, payloads it must send, events it will receive, and the validation contract. One source of truth, not three.

## Testing Decisions

A good test here verifies external behaviour: given a state and a user utterance, what does the assistant do next? Not which functions it called internally.

### What gets tested

- **Sequencing**: a unit test against `next_required_field` that asserts the right `(section, field)` is returned for several FormState fixtures (some with first section partially filled, some with optional fields filled before required). Pure function, no Redis.
- **Cross-section guard**: a unit test against the dispatcher that asserts `update_field("emergency_contacts[0]", "name", "Jane")` is rejected when the focus hint is `basics`. Mocked dispatcher state.
- **Validation echo**: a unit test that simulates a `validation_failed` event arriving at the bridge and asserts the next prompt-build call includes the failure in the `pending_validation_errors` block. Mocked Gemini bridge.
- **Server-side validator catalog**: one parameterised unit test per onboarding step that walks every field listed in `.claude/client_onboarding_validations.md`, asserts a known-bad value produces the expected `(code, reason_human)` pair, and asserts a known-good value passes. The fixtures live in the test file as table-driven data so adding a new validator is one row, not one new test. Bytes-exact match against the canonical AppStrings text for each field is the success criterion.
- **Cross-field invariants**: a unit test per cross-field rule (emergency email uniqueness, plan-end-after-start, conditional-required-when-any-filled service location, time-slot non-overlap, all-required-when-any-filled medical history). Each test uses a minimal FormState fixture and asserts the right rejection code fires.
- **Round-trip elimination**: a behavioural test that simulates `update_field("basics", "phone", "12")` and asserts the dispatcher returns a structured rejection WITHOUT writing to FormState AND WITHOUT requiring a `validation_failed` event from the Flutter side. Proves the server is now authoritative.
- **/complete gate**: a unit test that asserts `validate_step_complete` blocks the completion when any field has an unresolved rejection. Step is not marked completed; webhook does not fire.
- **Unknown field log**: a unit test that calls `update_field` on a non-existent path and asserts a log capture shows `unknown_field_attempt` with the right payload. `caplog`-style.
- **Repeatable entry**: a unit test that calls `enter_repeatable_section("emergency_contacts", "first")` and asserts the focus pin is set, subsequent `update_field` calls land on row 0, and the event is emitted.

### What is NOT tested in v1

- End-to-end Gemini behaviour. Gemini's instruction-following is verified manually via the test harness.
- Daily digest aggregation. Logs emit; aggregation is a follow-up.
- The "section name verbal cue" — qualitative, verified manually.

### Prior art

- `services/onboarding/tests/test_screen_context.py` for pure-function patterns (the new `next_required_field` test should mirror this style).
- `services/onboarding/tests/test_tools.py` for dispatcher rejection patterns (cross-section guard tests follow this style).
- `services/onboarding/tests/test_state_repo.py` for the `caplog` style if we land the unknown_field_attempt test.

## Out of Scope

- **End-to-end Gemini quality testing.** Manual via the test harness; LLM-level QA is a separate workstream.
- **Daily digest aggregation.** v1 emits the structured logs; aggregation/rollup is a follow-up.
- **Multi-language paraphrasing of validation errors.** v1 trusts the frontend's `reason_human` text verbatim. Locale handling is a follow-up.
- **Auto-growth of schema based on `unknown_field_attempt` frequency.** v1 logs only; humans review.
- **Voice-side handling of disability-specific input modes** (e.g. AAC devices). Separate workstream.
- **Cross-tenant analytics on validation/discovery telemetry.** Multi-tenant isolation is preserved by design (the structured logs include tenant_id but no aggregated cross-tenant view exists).
- **Backwards-compatible rollout path for clients that haven't shipped the validation_failed event yet.** They continue to work — the server is now the authoritative validator, so the absence of frontend validation_failed events is not a regression; it just means the assistant won't see two redundant signals. No breaking change.
- **Drift detection between server validators and Flutter validators.** v1 mirrors `lib/core/utils/validators.dart` against `.claude/client_onboarding_validations.md` once at implementation time. A future workstream may add a CI check that diffs the two; not in this PRD.
- **Server-side enforcement of fields that are display-only on the frontend.** The `email` field on Step 1 is `readOnly` (pre-filled from auth profile). The server-side validator for `email` rejects writes via `update_field` regardless of value — that's not "validation," it's a readonly-path rejection that already exists. Documented here so it isn't reinvented.
- **Refactoring the existing repeatable section logic.** The strengthening builds on top; the existing surface is unchanged.

## Further Notes

- The sequencing fix is the highest-leverage of the three. It will visibly change the assistant's behaviour the moment it ships. Validation awareness ships behind an enabled-by-default flag that lets us roll back if the conversational tone gets worse.
- The discovery telemetry has a small ongoing PII review burden: `transcript_excerpt` should be the last 2-3 turns max and should be redactable per tenant policy. Treat it like the cross-screen-summary block — same rules, same review cadence.
- The handoff doc gains a new top-level table of contents anchor "Issues observed during cross-screen testing" so the production-feedback issues live next to the original implementation issues, not buried at the bottom. The chronological order in the doc is the institutional memory.
- Defining `cross_section_intent: true` as an explicit flag (rather than inferring it) is deliberate. It forces the model to declare intent, and we can detect-and-reject silent cross-section writes. Implicit inference is the bug class we're trying to eliminate.

---

_This PRD is paired with handoff updates in `FLUTTER_DEV_HANDOFF.md` (Issues #14, #15, #16, #17) that document the wire contracts the frontend must implement._
