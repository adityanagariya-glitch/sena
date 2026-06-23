# Flutter Handoff — Voice Onboarding (MASTER, self-contained)

**The only doc the sena-mobile Flutter dev needs.** Everything required by the SENA_AI backend work landed after commit `41e988c62207063891a5799e6dd7073459161380` is inline here — staff flow, consent voice-sync, and three universal voice fixes. Every contract (WS frames, step ids, field paths, enums, code) is written out below; no other file required.

> The backend side of every item is already shipped. Nothing here needs a backend change — it's all Flutter.

---

## Priority overview

| # | Item | Priority | Applies to |
|---|------|----------|-----------|
| 1 | Staff onboarding voice flow (new) | **P0** | staff |
| 2 | Consent screen voice sync (Fix 1 + submit→advance) | **P0** | client step 6 |
| 3 | Surface on-screen validation errors to voice | **P1** | ALL flows |
| 4 | Auto-start the assistant on screen mount | **P1** | ALL flows |
| 5 | Render voice updates LIVE (DOB date-picker bug) | **P1** | ALL flows |
| 6 | Consent per-role access voice-fill (Fix 2) | P2 | client step 6 |
| 7 | NDIS-plan `preferred_schedule` overlap validation (NEW) | P1 | client step 3 (NDIS plan) |
| 8 | Voice session ↔ screen binding (stale controller answers wrong screen) | **P0** | ALL flows |

**Architectural fact:** items 3–5 are **universal** — the backend runs one flow-agnostic engine for client, staff, and every future voice flow. Implement them once in the shared `voice_session_controller` / sink layer and they work for all flows. No per-flow duplication.

---

# 1. Staff onboarding voice flow (P0 — NEW)

Staff voice onboarding reuses the entire voice engine. The only frontend work is **creating the 5 staff voice schemas** (analogous to `lib/core/voice_schemas/step1_personal_info_schema.dart …`) and sending the correct `stepId`s. **No staff voice schema exists yet.**

## 1.1 `stepId` contract (MUST match backend prompt filenames exactly)

| Inventory step | `stepId` to send |
|---|---|
| 1 Personal Information | `staff_personal_information` |
| 2 Role Information | `staff_role_information` |
| 3 Documents Upload | `staff_documents` |
| 4 Banking & Superannuation | `staff_banking` |
| 5 Policies Acknowledgement | `staff_policies` |

⚠️ **Silent-fail:** if you send any other `stepId`, the agent runs the generic prompt with **no field rules** and logs no error — it will sound plausible but won't know the fields. Use these exact ids. Flutter `FieldType.choice/multiChoice/longText` map to backend `enum/multi_enum/textarea` (your existing client serializer already does this).

## 1.2 Session creation (unchanged endpoint)

`POST /v1/onboarding/session` with: `participant_id` (the staff member's id), `step` (= the `stepId` above), `schema` (the inline `StepSchema`), `initial_state` / `bootstrap` (pre-filled values incl. readonly email/role/department), `tenant_id`. Same WS afterwards: `WSS /ws/onboarding/{session_id}`. Reference `StepSchema` JSON you can adapt as the inline payload: `tests/fixtures/staff/schema_staff_*.json` in this repo.

## 1.3 Field paths, types, enums, readonly (what the agent calls `update_field` with)

`update_field(section, field, value, repeatable_index?)`.

**Step 1 `staff_personal_information`** — sections `basics`, `address`

| section.field | type | required | readonly | rule |
|---|---|---|---|---|
| `basics.full_name` | text | yes | no | max 25 |
| `basics.email` | email | yes | **YES** | invite-prefilled; refuse |
| `basics.phone` | phone | yes | no | `+61`+9 digits (2/3/4/7/8); also `0`+9, `1300`/`1800`+6, `13`+4 |
| `basics.date_of_birth` | date | yes | no | ISO `YYYY-MM-DD`; not future; age ≥ 18 |
| `basics.gender` | enum | yes | no | `Male`, `Female`, `Other` |
| `basics.cultural_background` | enum | yes | no | `Australian`, `Indian`, `Asian` |
| `basics.languages_spoken` | multi-enum | yes (≥1) | no | `English`,`Mandarin`,`Arabic`,`Vietnamese`,`Cantonese`,`Punjabi`,`Greek`,`Italian`,`Hindi`,`Spanish` (send array) |
| `basics.requires_interpreter` | boolean | no | no | Yes/No |
| `basics.profile_picture` | file | yes | **YES (file)** | upload from screen; voice only opens picker |
| `address.address` | text | yes | no | max 100 |
| `address.state` | text | yes | no | free text, max 25 (do NOT force abbreviation) |
| `address.city` | text | yes | no | max 25 |
| `address.zip_code` | text | yes | no | **1–4 digits**, 0–9999 |

**Step 2 `staff_role_information`** — section `role_info`

| section.field | type | required | readonly |
|---|---|---|---|
| `role_info.role` | text | no | **YES** (org-set) |
| `role_info.department` | text | no | **YES** (org-set) |
| `role_info.experience` | textarea | yes | no — **the only voice-fillable field**, ≤ 500 chars |

**Step 3 `staff_documents`** — section `documents` (dynamic, org-defined slots; slot id is an opaque UUID, talk by the slot's display name)

| per-slot field | type | voice-mutable |
|---|---|---|
| `documents.{slot}.document` | file | NO — voice opens picker via `update_field(field="{slot}.document", value="true")` |
| `documents.{slot}.expiry_date` | date | YES when visible; future date |
| `documents.{slot}.not_applicable` | boolean | YES when slot optional |
| `documents.{slot}.ocr_data` | map | NO — screen-only |

**Step 4 `staff_banking`** — sections `banking`, `superannuation`, `tax_documents`

| section.field | type | required | rule |
|---|---|---|---|
| `banking.bank_name` | text | yes | max 50 |
| `banking.account_holder_name` | text | yes | max 50 |
| `banking.bsb` | text | yes | **exactly 6 digits** |
| `banking.account_number` | text | yes | digits, ≤ 12 |
| `superannuation.fund_name` | text | yes | max 50 |
| `superannuation.fund_abn` | text | yes | **exactly 11 digits** |
| `superannuation.member_number` | text | yes | max 50 |
| `tax_documents.{slot}.document` | file | from slot | screen upload (picker) — **dotless section id `tax_documents`** (the bridge splits the path on the first `.`) |
| `tax_documents.{slot}.expiry_date` | date | iff hasExpiry | future date |

**Step 5 `staff_policies`** — repeatable section `policies` (server-provided; do NOT `add_row`/`delete_row`)

| per-row field | type | voice-mutable |
|---|---|---|
| `policies.policy_name` | text | NO — readonly |
| `policies.policy_description` | text | NO — readonly |
| `policies.acknowledged` | boolean | YES |

## 1.4 Readonly registry (agent refuses to mutate)
```
basics.email
basics.profile_picture        (file — upload from screen)
role_info.role
role_info.department
policies[i].policy_name
policies[i].policy_description
documents.{slot}.document     (file — voice only opens the picker)
```

## 1.5 `voice_coverage` per step (send in the schema to restrict the agent)
- S1: all `basics.*` except `email`, `profile_picture`; all `address.*`
- S2: `role_info.experience` only
- S3: dynamic — per-slot `expiry_date` / `not_applicable` (files are screen-only)
- S4: all `banking.*` + `superannuation.*` text fields (tax doc is screen-only)
- S5: `policies.acknowledged` only

## 1.6 Policy acknowledgement — NO new tool
There is **no** `acknowledge_policy` tool. The agent acknowledges a policy via the existing `update_field`:
```
update_field(section="policies", field="acknowledged", value=true, repeatable_index=N)
```
Your controller must accept this write on the policy at row `N` and set its `acknowledgedAt`. The step can't submit until every row's `acknowledged` is true (enforce in Flutter; the agent guides).

## 1.7 Validation ownership (Option D — unchanged)
Flutter remains the **authoritative validator**. The backend relays `update_field` and reports back whatever your controller returns (`{ok:true}` / `{ok:false, reason}` / `{ok:false, blockers:[...]}`). All staff validations (BSB 6, ABN 11, zip 1–4, age ≥18, max-lengths, required-doc rules) live in Flutter `AppValidators`. The voice prompts encode these only so the agent *formats* + *re-asks* correctly — they do not enforce.

## 1.8 Cross-step handoff (`prior_pages`)
The backend carries only these keys across steps: `full_name`, `role`, `department`. Populate them in the bootstrap so the agent can greet by name and reference the role.

---

# 2. Consent screen voice sync — client step 6 (P0)

## 2.1 Symptom
On the Consent screen the voice agent says "I've saved that" but the on-screen checkboxes/dropdowns do NOT update. The NDIS-audit consent in particular: the agent confirms verbally, but the screen stays "I do not consent", so the form can't submit. Separately, on submit the agent loops forever asking to tick a written-consent box and the session dies.

## 2.2 Root cause — read/write namespace mismatch
- The agent is shown field paths **prefixed `consent.`** (e.g. `consent.allowed_information`) and writes them back as `section="consent"`, `field="allowed_information"`.
- Flutter resolves the write via `_voiceToSena` in `lib/core/voice_schemas/step6_consent_schema.dart` (lines 119-127), whose keys are `basic.*` / `info_sharing.*` / `media_consent.*` — **not** `consent.*`.
- Lookup misses → `voice_session_controller.dart` logs `unmapped field consent.<x> — ignoring` and **returns without touching the controller** → screen never updates.
- Validation accepts `section="consent"` but the **sink** only accepts `basic.`/`info_sharing.`/`media_consent.` — no single section works through both layers. So the resolver must be taught the `consent.` namespace.

## 2.3 Fix 1 — accept the `consent.` namespace (REQUIRED, ~7 lines, purely additive)
**File:** `lib/core/voice_schemas/step6_consent_schema.dart` — extend `_voiceToSena`:
```dart
static const Map<String, String> _voiceToSena = {
  // existing keys — keep them
  'basic.agreed_to_data_collection':   'consent.agreedToDataCollection',
  'basic.medication_support_consent':  'consent.medicationSupportConsent',
  'basic.financial_help_consent':      'consent.financialHelpConsent',
  'basic.ndis_audit_consent':          'consent.ndisAuditConsent',
  'info_sharing.allowed_information':  'consent.allowedInformation',
  'info_sharing.selected_roles':       'consent.selectedRoles',
  'media_consent.allowed_media_usage': 'consent.allowedMediaUsage',

  // NEW — accept the `consent.` prefix the agent is actually shown.
  'consent.agreed_to_data_collection':  'consent.agreedToDataCollection',
  'consent.medication_support_consent': 'consent.medicationSupportConsent',
  'consent.financial_help_consent':     'consent.financialHelpConsent',
  'consent.ndis_audit_consent':         'consent.ndisAuditConsent',
  'consent.allowed_information':         'consent.allowedInformation',
  'consent.selected_roles':             'consent.selectedRoles',
  'consent.allowed_media_usage':        'consent.allowedMediaUsage',
};
```
The sink (`client_step6_voice_sink.dart:30-83`) already handles all 7 camelCase senaPaths. No other change needed for the 7 base fields.

## 2.4 Fix 4 — voice `submit_step` must ADVANCE to review, not final-submit (REQUIRED — breaks the deadlock)
**Symptom:** the agent calls `submit_step`, gets a bare `{ok:false}` (no code/reason), and loops forever asking to tick a written-consent box that lives on the *next* page; the session dies.

**Root cause:** the consent voice `submit_step` is wired to the FINAL `submitConsent()` (`client_consent_controller.dart:410-419`), which hard-returns when `hasGivenWrittenConsent == false`:
```dart
if (!hasGivenWrittenConsent.value) {
  errorMessage.value = AppStrings.consentValidationWrittenConsent;
  isSaving.value = false;
  return;   // ← local early-return; replies to the bridge with a bare {ok:false}, no reason
}
```
The consent voice page is page 1 ("Consent Sharing" → *Continue*); the written-consent checkbox + *Confirm & Submit* are on page 2 ("Review & Confirm").

**Fix:** wire the consent-step voice `submit_step`/advance handler to **`proceedToReviewAfterRequirements()`** (`client_consent_controller.dart:341`) — validate the 7 voice fields + per-role detail, then navigate to review — NOT `submitConsent()`. Return a **structured** result over the bridge:
- advanced to review → `{ok: true}`
- real blocker (e.g. incomplete per-role `access_control` field) → `{ok: false, code: "<snake_case>", reason: "<human text>", path: "<field path>"}`

**NEVER** reply with a bare `{ok:false}` / empty reason — the backend relays exactly what you send, and the agent acts on it. Written-consent + Confirm & Submit stay human-only on page 2 (legal gate — keep). The backend `consent.md` prompt already treats consent submit as "advance to review" and stops looping on an empty rejection.

## 2.5 Fix 2 — per-role access detail voice-fill (P2, product wants it)
When roles are selected, the screen reveals a per-role panel (`accessControlByRole[role]`: `allowedInformation`, `purpose`, `timeframe`, `untilDate`). The sink has no case for these, so voice can't fill them; today the prompt directs the participant to tap each role on screen. To make them voice-fillable, add to `client_step6_voice_sink.dart` before `default:`:
```dart
case final p when p.startsWith('consent.access_control.'):
  _applyRoleAccess(p, value);
```
```dart
void _applyRoleAccess(String path, dynamic value) {
  // path = consent.access_control.<ROLE>.<attr>
  final parts = path.split('.');
  if (parts.length < 4) return;
  final role = ConsentRole.fromString(parts[2]);
  final attr = parts.sublist(3).join('.');
  final current = _ctrl.accessControlByRole[role];
  if (current == null) return; // role not selected yet
  switch (attr) {
    case 'allowed_information':
      final info = _parseStringList(value).map(ConsentInformationType.fromString).toList();
      _ctrl.updateRoleAccess(role, current.copyWith(allowedInformation: info));
    case 'purpose':
      _ctrl.updateRoleAccess(role, current.copyWith(purpose: value.toString()));
    case 'timeframe':
      _ctrl.updateRoleAccess(role, current.copyWith(timeframe: ConsentValidityType.fromString(value.toString())));
    case 'until_date':
      final d = DateTime.tryParse(value.toString());
      if (d != null) _ctrl.updateRoleAccess(role, current.copyWith(untilDate: d));
  }
}
```
`updateRoleAccess`/`copyWith`/per-role getters exist (`client_consent_controller.dart:272-299`). Also extend `readMappableValues` so the agent can read current per-role state. Ship with Fix 1 if product wants dynamic per-role voice-fill.

## 2.6 Fix 3 — written-consent checkbox: keep SCREEN-ONLY
`submitConsent` blocks unless `hasGivenWrittenConsent == true`. Keep this a human action on screen (legal gate). Do NOT add a voice sink case for `has_given_written_consent` unless compliance signs off.

## 2.7 Note — consent booleans default `false`
The four base consent booleans default to `false`; the backend prompt now treats `false` as "not yet asked" (it will ask each one). No Flutter change — but once Fix 1 is in, setting one `true` by voice WILL flip the checkbox on screen.

## 2.8 Consent file reference map
| File | Lines | Role |
|------|-------|------|
| `lib/core/voice_schemas/step6_consent_schema.dart` | 119-127 | `_voiceToSena` — **Fix 1** |
| `…/step6_consent_schema.dart` | 149-151, 163 | `toSenaPath` / `toSenaPathIndexed` |
| `…/voice_session_controller.dart` | 826-868 | `_applyFieldUpdate` — drops unmapped paths (857-859) |
| `…/client_step6_voice_sink.dart` | 30-83 | `applyVoiceUpdate` switch — **Fix 2** |
| `…/client_consent_controller.dart` | 341 | `proceedToReviewAfterRequirements` — **Fix 4 target** |
| `…/client_consent_controller.dart` | 410-419 | `submitConsent` — `hasGivenWrittenConsent` gate |
| `…/client_consent_controller.dart` | 272-299 | `updateRoleAccess` / `copyWith` |

---

# 3. Surface on-screen validation errors to the voice agent (P1 — ALL flows)

**Symptom:** participant changes a field (e.g. DOB) and the **screen** shows a red error, but the **voice agent says nothing** — it can't tell them what's wrong.

**Why:** the backend is a relay; it only knows about a validation failure if Flutter tells it.
- Voice-initiated change (agent called `update_field`): already works — return `{ok:false, reason}` to the tool call → agent speaks it. ✅
- **Screen-initiated** rejection (typed/picked value; picker rejects under-18 DOB): **Flutter currently sends nothing** → agent blind. ❌ ← fix this.

**Backend is ready:** it now speaks a `[SCREEN VALIDATION] … re-ask` cue for screen-originated errors on **both** channels below (newly-appearing errors only — it won't nag).

**Flutter — on EVERY on-screen validation failure, send ONE of:**

**Option A (preferred — explicit control frame):**
```json
{ "type": "validation_failed",
  "section_id": "basics", "field_id": "date_of_birth", "repeatable_index": null,
  "reason_human": "You must be at least 18 years old", "code": "client_validation_failed" }
```
- `section_id` + `field_id` REQUIRED (backend drops the frame otherwise).
- `reason_human` is spoken verbatim → phrase it how you want it heard.
- On fix, send `{ "type": "validation_cleared", "section_id":…, "field_id":…, "repeatable_index":… }` so the agent stops re-asking.

**Option B (reuse the screen_state you already send):**
```json
{ "type": "screen_state_v2", "data": {
  "step_id": "staff_personal_information",
  "field_errors": { "basics.date_of_birth": "You must be at least 18 years old" } } }
```
- Key = dotted `section.field`; value = the human reason.
- ⚠️ If your `screen_state_v2` includes a `turn` key, the backend takes the TurnPayload fast-path and ignores `field_errors`. Use Option A, or send the screen_state **without** a `turn` key.

**Verify:** type an under-18 DOB → agent says the age error and re-asks; fix it → agent stops.

---

# 4. Auto-start the assistant on screen mount (P1 — ALL flows)

**Symptom:** the agent doesn't greet/start on its own when the voice screen opens.

**Why:** `gemini-3.1-flash-live-preview` has **no proactive audio** — the model never speaks first. The backend works around this by injecting a hidden opener turn the instant the WS connects (you'll see `AGENT_SAID 'Hi …'` at turn 0). The backend now **always** does this, even with no seed state — so the greeting is guaranteed server-side on connect.

**Flutter — on screen mount, WITHOUT waiting for a user tap:**
1. **Open the WS** (`/ws/onboarding/{session_id}`) as soon as the session is created.
2. **Start the audio player** immediately so the greeting's `turn_start` + audio chunks play (don't lazy-init on first interaction).
3. **Start the mic stream** right away, gated by `_agentSpeaking` (mute on `turn_start`, unmute on `turn_complete`/`interrupted` — the echo rule), so barge-in works and the silence-watchdog timer is fed.
4. If there's a "tap to start voice" button today, auto-trigger that path in the screen's `onReady`/init.

**Verify:** open the voice screen cold → agent greets within ~2–3 s with no tap.

---

# 5. Render voice updates LIVE — the DOB date-picker bug (P1 — ALL flows)

**Symptom:** the agent updates a field (date of birth); the value IS saved (a new session re-fetches and shows it), but the **current screen doesn't update** until reload.

**Why (Flutter-side):** in Option D the backend is a pure relay. `update_field` → `tool_request` → Flutter validates/applies/returns `{ok:true, state}`. The backend emits **no** follow-up `field_updated`/`state` event (by design — re-emitting would double-apply). **The new value is already in the `tool_request` Flutter just processed** — the widget simply isn't rebuilding from Flutter's own state.

**Flutter — general rule (every voice-updated field, not just DOB):**
- The moment you handle an `update_field` `tool_request` and decide `ok:true`, **patch form state AND rebuild the bound widget right then** — do not wait for any backend event (there isn't one).
- Bind every input widget **reactively** to form state (e.g. the date-picker's displayed value reads from `state.basics.date_of_birth`), so a state change repaints it.
- Usual offenders are **non-text widgets** (date pickers, dropdowns, checkboxes, multi-select chips) built with a one-time `initialValue:` that never rebuilds. Text fields that *do* update live (e.g. address) show the correct path — make the others follow it.

**Verify:** voice-set a valid DOB → the date-picker shows it immediately, no restart.

---

# 7. NDIS-plan `preferred_schedule` overlap validation — client step 3 (P1 — NEW)

**Gap:** the NDIS-plan step lets the agent set a support item's schedule by voice
(`update_field(section="support_schedule", field="preferred_schedule", value="<DSL>")`). Same-day
time slots must NOT overlap, but nothing enforces it today — the backend has no validator and the
voice prompt's "soft" check is not a reliable gate. Per §1.7 this is **client-owned** validation.

**Contract (the §3 voice-initiated path):** on an `update_field` `tool_request` for
`preferred_schedule`, parse the proposed `value` — it REPLACES the whole row's schedule, so validate
it against itself — and if any same-day ranges overlap, reply
`{ok:false, code:"schedule_overlap", reason:"<spoken sentence>"}` (the agent reads `reason` verbatim).
No overlap → your normal `{ok:true}`. Touching ranges (`end == start`) are OK.

**Full spec — DSL grammar, the overlap algorithm, copy-paste Dart, and a test-vector table — is in
`FLUTTER_DEV_PREFERRED_SCHEDULE_OVERLAP.md` (this folder).**

---

# 8. Voice session ↔ screen binding — ALL flows (P0 — NEW)

**Symptom (tested 2026-06-22):** assistant opened on the Consent screen but kept reading/writing the
**Medical Information** screen (step 5); every consent write came back `unknown_path`; the agent said
*"I'm stuck on the medical information section"* and the session was abandoned.

**Root cause:** the session was *created* for `consent`, but `get_current_state` / `update_field` were
*answered* by the previous screen's (medical) controller — a stale voice controller / `tool_request`
handler that wasn't torn down on navigation. The backend relays whatever you return, so it read medical
and rejected consent fields.

**Fix:** the screen that creates a voice session MUST be the one whose controller answers that session's
`tool_request` frames. On navigation, fully dispose the old screen's voice controller (close WS,
unregister handler) before the next screen attaches; route `tool_request` by `session_id`. **Invariant:**
the `step_id` returned by `get_current_state` must equal the `step` sent at session create.

**Backend safety net (added this change):** on a `step_id` ≠ session-`step` mismatch the backend logs
`screen_session_mismatch` and tells the agent to ask the participant to reopen on the correct screen —
so it fails loud, not silent. **This is not a fix; the Flutter binding must still be corrected.**

**Full detail + verify steps → `FLUTTER_DEV_SCREEN_SESSION_BINDING.md` (this folder).**

---

# Acceptance checklist (hand back when done)

- [ ] **Staff:** 5 staff voice schemas send the exact `staff_*` stepIds; a full staff voice session works end-to-end (§1).
- [ ] **Consent:** voice flips checkboxes/chips on screen (Fix 1); `submit_step` advances to review with a structured result, no loop (Fix 4) (§2).
- [ ] **Validation:** any screen validation error (e.g. under-18 DOB) makes the agent speak it and re-ask (§3).
- [ ] **Auto-start:** voice screen greets within ~3 s on mount, no tap (§4).
- [ ] **Live render:** voice-set DOB (and dropdowns/checkboxes) update the widget live (§5).
- [ ] **NDIS plan:** overlapping same-day `preferred_schedule` slots are rejected with a spoken `reason`; non-overlapping (incl. touching) accepted (§7).
- [ ] **Screen binding:** `get_current_state` on any screen returns a `step_id` equal to that session's `step`; navigating between voice screens disposes the prior controller (§8).

---

*Backend status: all server-side changes for the above are already implemented in SENA_AI (staff prompts + schemas, consent prompt, screen-validation cue, guaranteed greeting kickoff, pure-relay update path). The pre-`41e988c` Step-1 validation-parity contract in `flutterhandoffdev.md` still applies and is compatible with everything here.*
