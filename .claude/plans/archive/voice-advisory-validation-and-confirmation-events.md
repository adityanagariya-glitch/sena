---
title: Voice-Advisory Validation + Voice Confirmation Events
created: 2026-05-18
owner: main session (handoff)
status: ready-to-execute
agent-pipeline: planner → task-breaker → implementer → business-reviewer (NDIS) → security-reviewer → bug-fixer (if FAIL) → optimization-reviewer → cleaner → git-committer
---

# Feature — Voice-Advisory Validation + Voice-Confirmation Events

> **Read this file first if you are landing in a fresh Claude session on this repo.** It contains the full context, decisions, file map, acceptance criteria, and the agent pipeline to execute. No back-and-forth needed.

---

## 0. Backstory — the bug report chain that led here

Sequence of events between 2026-05-15 and 2026-05-18:

1. **WS error 1008** — Gemini Live connect failed with code 1008 "policy violation". Root cause: `session_resumption=types.SessionResumptionConfig(handle=None)` in `gemini_live.py` serialised as `{"handle": null}` which `gemini-3.1-flash-live-preview` rejects. **Fixed.** Removed the line. Deployed to EC2 2026-05-14. Logged: `.claude/issues-solved/0007-gemini-live-1008-session-resumption-null-handle.md`.

2. **App showed `Voice unavailable: 404`** — Flutter app hit the wrong WS URL. Backend was returning `ws://localhost:<env-var-port>/...` but env var didn't match the actual running port. **Fixed.** `routes.py::create_session` now builds `ws_url` from `request.url.netloc`. Always reflects the live host:port.

3. **Operator hit "Project quota tier unavailable"** in AI Studio → Gemini Live denied access. Billing wasn't enabled on the GCP project linked to the API key. **Fixed** (operator-side): billing linked, retry succeeded.

4. **Operator reported three follow-up bugs after Flutter integration shipped:**
   - "State of screen not live — re-asking for address"
   - "Emergency contact still there"
   - "Valid email flagged invalid"

   Investigation by reading `logs2.txt` (Flutter VoiceCtrl + backend events for one real session):
   - **Symptom 1 ("re-asking address")** → NOT a bug. Was the agent's Rule 3 pre-fill confirmation flow ("I can see your address is filled — is that correct?"). User confirmed. Perceived as re-asking, was actually confirmation. (This is what motivated the `field_confirmed` event in §3.2 — Flutter has no way to distinguish confirmation from re-write.)
   - **Symptom 2 ("emergency contact still there")** → NOT a bug. The pre-fill payload contained a test row `{name: "name", relation: "Father", email: sara.brow@example.com, phone: +61400001399}`. Test data quality, not code.
   - **Symptom 3 ("valid email flagged invalid")** → CORRECT rejection. `aditya.client@yopmail.com` was being entered as `basics.email`; the old `_email()` validator applied the disposable-domain blocklist universally. Per `client_onboarding_validations.md` spec line 15, `basics.email` should NOT have disposable check — only `emergency_contacts.email` does (spec line 47). **Fixed.** Email validators split per-field per spec. **The operator's irritation here drove the broader decision** captured in §1 (frontend = authoritative, backend voice = advisory).

5. **WS closed mid-session (`code=null reason=null`)** — visible in `logs2.txt` line 2540 while agent was asking for `preferred_languages`. Likely Gemini's ~10-min session lifetime cap firing without a clean close-code. **NOT in scope for this plan** — separate ticket; needs `gemini_live.py` to emit a `ws_close_unhandled` structlog line so the next session has root-cause data.

### Schema-agnostic regression test landed

`services/onboarding/tests/test_screen_state_skip.py` walks every fixture schema dynamically, picks the first 2 required scalar fields per schema at runtime, and asserts:

- Populated `bootstrap.current_page_values` seeds FormState such that `next_required_field` skips those paths
- `screen_field_status: {path: "filled"}` overrides empty state in `next_required_field`
- Bootstrap values appear in the rendered `[LIVE_STATE_JSON]` block
- Negative control: marking one path filled does not affect unrelated paths

**No field IDs are hardcoded.** Any schema Flutter ships now or in future feeds the same test. The implementer's new code must keep these tests green.

### Temporary debug log line

`routes.py::create_session` emits `debug_client_bootstrap_payload` (info-level structlog) immediately after bootstrap resolution. Carries `current_page_values_keys`, `current_page_values_sample` (first 8 entries), `bootstrap_mode`, `legacy_initial_state_keys`. **Left in place until next deploy confirms Flutter is sending populated payloads** — then `@agent-sena-cleaner` should remove it (search marker: `# TEMP DEBUG — dump raw client payload`). NDIS APP 11 leak risk if left in production logs long-term.

---

## 1. Why this exists

The Flutter team needs **fine-grained validation to live client-side**, because validation rules will evolve quickly during early NDIS rollout. The current backend (onboarding voice service) is too strict — it blocks the conversation flow on every regex/length mismatch, forcing the voice agent to loop ("could we try that again?") on values the user clearly intends.

Decision (confirmed with product owner 2026-05-18):

- **Voice path = ADVISORY.** Backend still runs validators but emits warnings, persists the value anyway, lets the agent move on.
- **Typed `PUT /state` path = STRICT.** Unchanged. Flutter's typed-form fallback still trusts the server as a safety net.
- **Frontend submit button = SOLE GATE for advance.** Flutter runs the canonical validators on form submit; the user cannot leave the screen until Flutter is satisfied. That is the actual NDIS-compliance enforcement point.

Spec source of truth: `sena-mobile/client_onboarding_validations.md`.

---

## 2. What's already in place (do NOT redo)

These have already been delivered on `feat/onboarding-ai-merged` and don't need touching unless you find a defect:

- **WS URL fix** — `routes.py` now derives `ws_url` from `request.url.netloc`, not env var. Was returning wrong port when service ran on non-default port.
- **Email validator spec alignment** — three email rules now match the spec exactly:
  - `basics.email` → standard regex, no disposable check, no length cap (spec line 15)
  - `emergency_contacts.email` → strict regex + disposable + RFC 5321 length (spec line 47)
  - `plan_info.contact_email` / `billing_email` → standard + ≤50 chars (spec line 94-95)
- **`screen_field_status` kwarg** — `sequencing.next_required_field` and `prompt_builder._compute_next_required_field` honor a `{section.field: "filled"}` map. Param is plumbed through `_build_live_state_block` + `build_system_prompt`. **NOT yet wired from `gemini_live.py`** — see followups.md item 2.
- **Test harness** — `services/onboarding/test_harness.html` works end-to-end against local uvicorn.
- **Flutter wiring handoff doc** — `SENA_AI/FLUTTER_WIRING_HANDOFF.md` documents the full WS event protocol.

Existing schema-agnostic regression test: `services/onboarding/tests/test_screen_state_skip.py`. It parametrises over every fixture schema — your new code must keep it green.

---

## 3. What this plan delivers (scope)

### 3.1 Voice validator advisory mode

Change `tools._update_field` so that when `validators.field_rules.validate_field()` returns a rejection on a non-empty value:

- Persist the value into FormState anyway (write through).
- Emit a new event `field_advisory_warning` instead of `validation_rejection`.
- Return `{"ok": True, "warning": rej.model_dump()}` to the agent — NOT `{"ok": False, ...}`.

When the value is `None` / empty / malformed (cannot be type-coerced into the field's declared schema type), keep current behaviour: emit `validation_rejection`, return `{"ok": False, ...}`. There's no point persisting garbage that would crash downstream.

Same shift in `tools.advance_step` for cross-field rules (`validate_cross_fields`):

- Cross-field violations no longer block advance.
- Emit `field_advisory_warning` per violation.
- Continue advance as normal.

### 3.1.bis Guiding principle — keep it dynamic over schema

The operator's repeated directive throughout this work: **do not hardcode field IDs anywhere in this diff.** The schema is provided per-session by Flutter. Backend must operate on whatever section/field IDs the schema declares. If the implementer is tempted to write `if section == "basics" and field == "email"` somewhere — STOP. Walk the schema instead, or look up `field.type` / `field.required` / `field.options`.

Hot rule that has been broken before and must not be broken again: the per-field validator map in `validators/field_rules.py` is the ONLY place where (section_id, field_id) literals exist for business rules. That map is intentionally explicit because each NDIS field has bespoke validation. Adding a new "smart" code path that hardcodes a field outside that map is an INSTANT-FAIL.

### 3.2 Voice confirmation events (NEW — Flutter requirement)

**Problem.** When the user verbally confirms a pre-filled value ("yes, that's correct"), the agent calls `update_field` with the same value already in state. Flutter currently does not differentiate between:

- A new value being written for the first time
- An agent re-confirmation of an existing value (no semantic change)

Without that signal Flutter cannot mark the field as "confirmed by user this session", which is what the screen-save trigger watches for.

**Solution.** Emit a new WS event:

```json
{
  "type": "field_confirmed",
  "section_id": "basics",
  "field_id": "phone",
  "repeatable_index": null,
  "value": "+61482698312",
  "confirmation_source": "voice",
  "turn_id": 7
}
```

Emit triggers:

1. Agent calls `update_field` and the value is unchanged from current FormState (same path, same scalar value or same list contents).
2. User said an explicit yes/confirm in the same turn (the dispatcher already tracks `pending_confirmation` — reuse that flag).

Flutter consumes `field_confirmed` to:

- Update its local UI state ("✓ confirmed" pill on the field)
- Persist the screen-save event into its onboarding draft store
- Skip the field on its own client-side re-validation (the user already confirmed)

The event is additive — strictly new, no existing handler changes. Default arm in Flutter's `VoiceEventModel.parse` will WARN; Flutter handler adds the row.

### 3.3 System prompt update — Rule 7

Current Rule 7 in `prompts/onboarding_system.md` ("Frontend Validation Loop") tells the agent to re-ask on `validation_rejection`. Update to:

> **Rule 7 — Advisory Validation Feedback.**
> When the server returns a `warning` field on `update_field` ok=true, briefly acknowledge the concern to the user once and continue to the next field. Do NOT loop or re-ask unless the user volunteers a correction. The final validation gate is the user pressing Submit on the form — that is the only blocking check.
>
> The server only returns `ok: false` for truly malformed input (e.g., a value that can't be parsed at all). In that case, ask once for a clearer value.

### 3.4 New WS event documented

Update the canonical event table in `.claude/rules/api.md`:

| Event | Source | Payload | Flutter contract |
|-------|--------|---------|------------------|
| `field_advisory_warning` | `tools.py` | `{section_id, field_id, repeatable_index?, code, reason_human, severity: "advisory"}` | Inline non-blocking hint; field still considered written |
| `field_confirmed` | `tools.py` | `{section_id, field_id, repeatable_index?, value, confirmation_source: "voice", turn_id}` | Mark field as user-confirmed; trigger local screen-save |

`validation_rejection` stays in the table — still emitted for truly malformed input.

---

## 4. NDIS-compliance check (mandatory for `@agent-sena-business-reviewer`)

Cross-field rules that currently block advance:

- `emergency_email_unique_and_differs_from_client` — NDIS rule; emergency contact must be reachable separately from client
- `emergency_phone_unique_and_differs_from_client` — same
- `plan_end_after_start` — NDIS-mandated plan-date sanity
- `medical_history_all_or_none` — completeness within a row
- `time_slot_no_overlap` — schedule-of-supports invariant

**Question for business-reviewer:** which of these can safely go advisory on voice path, trusting Flutter submit-button enforcement? Decision blocker — must answer before implementer ships.

Recommendation: **all** can go advisory IF AND ONLY IF Flutter has all five enforced on submit. Verification: open `client_onboarding_validations.md` cross-field section; cross-reference against Flutter's `step1_personal_information_screen.dart` (or equivalent) submit handler. If a rule is NOT in Flutter, leave it strict on the voice path (advisory mode applies only to rules Flutter mirrors).

---

## 5. File map (exact paths)

### Backend — `SENA_AI/sena-ai/services/onboarding/`

| File | Edit | Why |
|------|------|-----|
| `src/onboarding/services/tools.py` | Modify `_update_field` (~line 982) + cross-field block in `advance_step` (~line 1041) | Advisory mode + emit `field_advisory_warning` + emit `field_confirmed` |
| `src/onboarding/prompts/onboarding_system.md` | Replace Rule 7 body | Match advisory semantics |
| `src/onboarding/core/settings.py` | Add `onboarding_voice_validation_advisory: bool = True` setting (rollback lever) | Operator can flip back to strict via env var if a regression slips |
| `src/onboarding/models/form_state.py` | Verify `FieldValue` has a `confirmed_in_session: bool = False` flag (add if missing) | Server-side memory of "confirmed this WS session" so we only emit `field_confirmed` once per field per session |
| `.claude/rules/api.md` | Add the two new event rows to the canonical table | Anti-AP-5: every emitted event must be documented |

### Tests — `SENA_AI/sena-ai/services/onboarding/tests/`

| File | Edit | Why |
|------|------|-----|
| `test_tools.py` | Adjust `test_email_disposable_domain_rejected` (already targets `emergency_contacts.email`) to assert ok=true + warning when advisory mode is on; add `test_advisory_persists_value_with_warning`; add `test_advisory_field_confirmed_emits_on_unchanged_value` | New behaviour |
| `test_validators.py` | No change — `field_rules.validate_field` semantics unchanged; only the dispatcher's response handling changes | — |
| `test_screen_state_skip.py` | Keep green | Regression gate |

### Frontend — `sena-mobile/lib/features/voice_onboarding/`

Out of scope for this backend PR but document the contract:

| File | Change | Why |
|------|--------|-----|
| `presentation/controllers/voice_session_controller.dart` | Add handler for `field_advisory_warning` → show toast/snackbar, do NOT block; add handler for `field_confirmed` → mark field confirmed, trigger screen-save | Honor new contract |
| `domain/entities/voice_event_model.dart` | Add `VoiceAdvisoryWarning` + `VoiceFieldConfirmed` variants; ensure default arm of `VoiceEventModel.parse` logs WARN, never silently returns null | Anti-AP-5 |

Update `SENA_AI/FLUTTER_WIRING_HANDOFF.md` §6 event table with the two new rows.

---

## 6. Acceptance criteria

A PR for this work is **only acceptable** when ALL of:

- [ ] `tools._update_field` returns `{"ok": True, "warning": ...}` on validator rejection of a non-empty parsable value AND persists the value to FormState
- [ ] `field_advisory_warning` event is emitted, carries `{section_id, field_id, code, reason_human, severity}`
- [ ] `field_confirmed` event fires when agent's `update_field` value matches current FormState scalar (or list-by-set for multi-value fields)
- [ ] `field_confirmed` emitted at MOST once per (section, field, row) per WS session — server tracks `confirmed_in_session`
- [ ] `validation_rejection` still emitted on truly malformed input (None / empty / type-parse failure)
- [ ] `advance_step` no longer blocks on cross-field warnings — those become advisory events, advance proceeds
- [ ] System prompt Rule 7 rewritten to match advisory wording
- [ ] `.claude/rules/api.md` event table updated with both new event rows
- [ ] `SENA_AI/FLUTTER_WIRING_HANDOFF.md` §6 + §15 updated
- [ ] New env var `SENA_AI_ONBOARDING_VOICE_VALIDATION_ADVISORY` documented in `.env.example` (default `true`)
- [ ] `pytest services/onboarding/tests/ -x -q` is **all green** (excluding the known pre-existing `test_emergency_phone_duplicate_reason_human_bytematch` — see followups.md)
- [ ] `ruff check services/onboarding/src/` clean
- [ ] `mypy services/onboarding/src/onboarding/` clean
- [ ] Business reviewer confirmed cross-field advisory is safe re: NDIS compliance (or carved out the rules that must stay strict)

---

## 7. Agent pipeline (run in order)

```
@agent-sena-planner
  ↓  (plan DAG + risk analysis — confirm NDIS carveouts)
@agent-sena-task-breaker
  ↓  (atomic JSON tasks per file)
@agent-sena-implementer
  ↓
@agent-sena-business-reviewer  ⟵ MUST PASS — NDIS gate
  ↓ PASS                        FAIL → @agent-sena-bug-fixer → loop
@agent-sena-security-reviewer
  ↓ PASS                        FAIL → @agent-sena-bug-fixer → loop
@agent-sena-optimization-reviewer (fixes inline)
  ↓
@agent-sena-cleaner (fixes inline — ruff/mypy/dead-code)
  ↓
@agent-sena-git-committer (Conventional Commits, NEVER push)
```

Spawn rule: ONE focused subtask per agent invocation, per `.claude/rules/sena-rules.md` constraint #2.

---

## 8. Known unknowns (resolve before implementer ships)

1. **Where is `pending_confirmation` set in `tools.py`?** Re-use the existing flag for `field_confirmed` emission. If it doesn't exist, add it on the FormState model.
2. **Does Flutter currently subscribe to `validation_rejection` as a blocker?** If yes, transitional plan: emit BOTH the new `field_advisory_warning` AND the legacy `validation_rejection` for two sprints; remove the legacy emit only after Flutter has migrated.
3. **Multi-value fields (`multi_enum`)** — what counts as "same value" for `field_confirmed`? Recommendation: set-equality on list contents (order-independent). Confirm with planner.

---

## 9. Linked artefacts

- Spec (single source of truth for field rules): `sena-mobile/client_onboarding_validations.md`
- Flutter wiring handoff (per-feature contract): `SENA_AI/FLUTTER_WIRING_HANDOFF.md`
- Flutter diagnostic (how to capture bootstrap logs): `SENA_AI/FLUTTER_DIAG_VOICE_BOOTSTRAP.md`
- Canonical Flutter event contract: `SENA_AI/flutterhandoffdev.md`
- Followups (open): `SENA_AI/.claude/tasks/followups.md` — three items related to this work (screen_field_status wiring, repeatable row support, phone-format normalisation)
- Issues-solved index: `SENA_AI/.claude/issues-solved/INDEX.md` (entry 0007 = the 1008 resumption-null-handle root cause)
- Test harness (in-browser end-to-end test): `SENA_AI/sena-ai/services/onboarding/test_harness.html`
- Schema-agnostic regression test (must stay green): `SENA_AI/sena-ai/services/onboarding/tests/test_screen_state_skip.py`
- Current event table (where new events MUST be added): `SENA_AI/.claude/rules/api.md` §SENA WebSocket events
- Validators: `SENA_AI/sena-ai/services/onboarding/src/onboarding/services/validators/` (field_rules.py, cross_field.py, sequencing.py)
- Prompt template: `SENA_AI/sena-ai/services/onboarding/src/onboarding/prompts/onboarding_system.md` (Rule 7 lives here)
- Tool dispatcher: `SENA_AI/sena-ai/services/onboarding/src/onboarding/services/tools.py` (`_update_field`, `advance_step`)
- Service rules autoload (path-scoped): `SENA_AI/.claude/rules/service-onboarding.md`, `SENA_AI/.claude/rules/api.md`, `SENA_AI/.claude/rules/gemini.md`

---

## 10. How to start a session from this plan

In the SENA_AI directory:

```bash
cd C:\Users\Admin\Downloads\sena-mobile\sena-mobile\SENA_AI
claude
```

Then in the new session prompt:

> Read `.claude/plans/voice-advisory-validation-and-confirmation-events.md` and execute it via the agent pipeline at §7. Start with `@agent-sena-planner` and report back the plan DAG before invoking task-breaker.

The planner will produce a DAG; route through the pipeline; you approve at each reviewer gate.

---

## 11. DO NOT TOUCH (load-bearing decisions already made)

These are not bugs; they are deliberate architectural choices. Reverting any of them silently is the worst-failure mode for this work.

- **Cross-screen context bucket** (`services/cross_screen_context.py`, `repositories/user_context_repo.py`, the bucket auto-hydration in `routes.py:174-208`). Operator explicitly said cross-screen bucket is finalized — do not change behaviour. This was investigated as a possible cause of the "state not live" symptom and ruled out. The bucket is the SEPARATE mechanism for multi-step prior_pages handoff, not for per-screen live state.
- **`screen_field_status` kwarg** is plumbed but DORMANT until `gemini_live.py` wires it. That wiring is in `followups.md` item 2 and is OUT OF SCOPE for this plan unless the planner pulls it in deliberately.
- **`basics.email` standard regex** (no disposable check) — spec line 15. Do not re-add the blocklist there. If a reviewer thinks "but auth.com is risky", route the question to product owner — auth-prefilled emails are trusted by definition.
- **`emergency_contacts.email` strict regex + disposable + RFC 5321 length** — spec line 47. Keep strict. Do not "harmonise" with the standard rule.
- **`plan_info.contact_email` / `plan_info.billing_email` standard + ≤50 chars** — spec lines 94-95. Keep the 50-char cap; it is in the spec.
- **System prompt Rules 1-6** — keep numbered exactly as they are. Only Rule 7 changes in this plan. The prompt's `[LIVE_STATE_JSON]` placeholder rendering pipeline is correct (audited 2026-05-18).
- **Schema-agnostic regression** (`test_screen_state_skip.py`) must stay green. Do not hardcode field IDs in any new test — parametrise over fixture schemas.
- **No Postgres in onboarding service.** Redis only. App backend is DB of record.
- **NDIS APP 11** (Australian Privacy Principle 11) — do not log PII verbatim. Existing structlog patterns log IDs (`session_id`, `tenant_id`, `participant_id`) and hashes, not raw values. The temporary `debug_client_bootstrap_payload` line is the ONE exception and must be removed after Flutter logs validate the pipeline.
- **Gemini API rules** (`.claude/rules/gemini.md`) — hook-gated. Any edit to `gemini*.py` or `demo_live*` files requires `Skill: gemini-live-api-dev` + Context7 query for `google-genai` THIS session. Re-earn at session start; don't try to bypass.

---

## 12. Glossary (for fresh-session reviewers)

- **FormState** — Redis-backed snapshot of one participant's progress through one onboarding step. Lives ~30 min TTL.
- **Bootstrap envelope** (`SessionBootstrap`) — client-supplied hygiene context: mode, current_page_values, readonly_paths, prior_pages, participant_display_name. Rendered into `[LIVE_STATE_JSON]` block of the system prompt.
- **screen_state_v2** — WS frame from Flutter carrying the LIVE UI focus state during a session: focused_section, focused_field, field_status, field_errors. Updates per turn.
- **`update_field` tool** — Gemini function call made by the agent every time it captures a value. Lands in `tools.py::ToolDispatcher.dispatch`. The advisory shift in this plan modifies this handler's response semantics.
- **`advance_step` tool** — Gemini function call when the user finishes a step. Runs `validate_step_complete` (sequencing + cross-field). The cross-field block goes advisory in this plan.
- **NDIS** — Australia's National Disability Insurance Scheme. Imposes data-residency, audit-log, and tenant-isolation requirements on every change.
- **Anti-AP-5** — Flutter `default` arm of `VoiceEventModel.parse` must log WARN on unknown event types, never silently return null. Every new WS event must be added to both Flutter's parser AND `.claude/rules/api.md`'s event table.

---

*End of plan. No back-and-forth needed — every decision is captured above.*
