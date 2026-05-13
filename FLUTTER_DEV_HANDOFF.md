# Flutter Dev Handoff — SENA Voice Onboarding

**Audience:** Flutter developer integrating with the SENA voice onboarding backend.
**Updated:** 2026-05-12
**Backend status:** final and tested.

Prior issues #1, #1b, #2, #3, #6, #7, #10, #11, #12, #14, #15 have been audited against `lib/features/voice_onboarding/` and confirmed implemented — they are no longer listed here. The remaining four items below are the only Flutter work outstanding.

---

## TL;DR — Four open items

| # | Status | Item |
|---|--------|------|
| 4+9 | PARTIAL | Repeatable section UI wiring — events are parsed but no sink renders/fills repeatable cards |
| 5 | PARTIAL | Pass `initialState: null` explicitly on fresh voice sessions |
| 8 | PARTIAL | Include `field_errors` (not just `field_status`) in `screen_state_v2` |
| 13 | PARTIAL | UX polish — readonly visual lock, confidence colour switch |
| **16** | **NEW** | **Render-after-validation invariant — never paint a captured value into the form until `field_updated` arrives** |
| **17** | **NEW** | **Handle `enum_invalid` + `allowed_values` from backend — show option picker for multi-enum fields** |
| **18** | **NEW** | **Handle `section_min_unmet` advance_step failure + `__section_min__` sentinel in `field_skipped_warning`** |

---

## ⚠️ Backend changes you should know (2026-05-11)

### A. Cross-screen context now only forwards five concepts

Previously `prior_pages` carried verbatim field-paths PLUS a compressed JSON of every other field. That noise is gone. Backend now only forwards five concepts between steps:

- `name`
- `dob`
- `gender`
- `goals`
- `hobbies_interests`

`prior_pages["step:N"]` shape is now keyed by concept name, not field path:

```json
{
  "step:1": {
    "name": "Aditya",
    "dob": "2000-02-25",
    "gender": "Male",
    "goals": ["Find part-time work", "Build social circle"],
    "hobbies_interests": "Chess and gardening",
    "_step_label": "Personal Information"
  }
}
```

**No Flutter action required** — `prior_pages` auto-hydrates server-side from the cross-screen bucket. Send `prior_pages: {}` on session create and the backend fills it. Heads-up only.

### B. Low-confidence captures now return `CONFIRM_REQUIRED` (B5)

Any `update_field` call with `confidence < 0.90` is NOT committed. The backend returns:

```json
{
  "ok": false,
  "rejection": {
    "code": "CONFIRM_REQUIRED",
    "section": "basics",
    "field": "gender",
    "heard_value": "Male",
    "confidence": 0.80,
    "reason_human": "I wasn't fully sure I caught that correctly — did you say Male?"
  }
}
```

`field_updated` events will NOT fire for these. The agent re-asks; once the user confirms, a fresh `update_field` with confidence=1.0 commits and the event fires normally. No Flutter action required — just be aware that a value heard with low confidence will round-trip through user confirmation before showing up in the UI.

### C. Australian state validation (B4)

`home_address.state`, `service_address.state`, and `staff_basics.state` now reject any value that is not one of NSW, VIC, QLD, SA, WA, TAS, ACT, NT (or a recognised full-name alias). The error surfaces as a `validation_rejection` event (handled identically to other Rule 8 rejections); the agent re-asks.

---

## ⚠️ Backend changes you should know (2026-05-12)

### D. VAD patience extended to 3 s

No Flutter action required. `silence_duration_ms` was increased from 1 s → 3 s. Gemini now waits 3 seconds of silence before ending a participant's turn. `turn_complete` may arrive up to 2 s later than before — size any mic-flush debounce accordingly.

### E. Email validation tightened (RFC 5321)

`email_invalid` now also fires for:
- Any domain label > 63 chars (e.g. `aaaa...64...aaaa.com`)
- Total domain length > 253 chars

Mirror this in the Flutter frontend validator so inline errors appear before the voice round-trip:

```dart
bool _domainValid(String email) {
  final domain = email.split('@').last;
  if (domain.length > 253) return false;
  return !domain.split('.').any((label) => label.length > 63);
}
```

### F. Multi-enum fields validated against schema options (Issue #17 — V3)

New rejection code: **`enum_invalid`**

Fires when a `multi_enum` field (e.g. `mode_of_communication`) receives a value not in the field's `options` list. The `validation_rejection` WS event now carries `allowed_values` when this code fires:

```json
{
  "type": "validation_rejection",
  "section_id": "requirements",
  "field_id": "mode_of_communication",
  "code": "enum_invalid",
  "reason_human": "That option isn't available. Please choose from the list — for example: \"Verbal (spoken)\", \"Written (text/email)\", \"AAC device\".",
  "allowed_values": ["Verbal (spoken)", "Written (text/email)", "AAC device", "Sign Language", "Visual aids"]
}
```

`pending_validation_errors` inside a `state` WS event also includes `allowed_values` for `enum_invalid`:

```json
{
  "section_id": "requirements",
  "field_id": "mode_of_communication",
  "repeatable_index": null,
  "code": "enum_invalid",
  "reason_human": "...",
  "allowed_values": ["Verbal (spoken)", "Written (text/email)", "AAC device", "Sign Language", "Visual aids"]
}
```

`allowed_values` is **only present** when `code == "enum_invalid"`. Absent for all other codes.

**Flutter action (Issue #17):** When a `validation_rejection` or `pending_validation_errors` entry has `allowed_values`, render a chip-group / multi-select picker showing those options. Pass the user's selections as a `List<String>` into the next `update_field` call.

### G. Morning and evening routines are now MANDATORY (Issue #18 — V4)

`morning_routine` and `evening_routine` now have `min: 1` in the schema. The backend enforces this.

**`advance_step` now returns a new failure shape when zero rows exist:**

```json
{
  "ok": false,
  "error": "section_min_unmet",
  "sections": ["morning_routine", "evening_routine"],
  "message": "Please add at least one entry to: Morning Routine, Evening Routine"
}
```

The agent reads this and insists the participant adds entries. No Flutter action on this specific payload shape.

**`field_skipped_warning` WS event — new `__section_min__` sentinel:**

```json
{
  "type": "field_skipped_warning",
  "missing_count": 2,
  "required_filled": 0,
  "required_total": 2,
  "missing_fields": [
    {
      "section_id": "morning_routine",
      "field_id": "__section_min__",
      "label": "At least 1 Morning Routine entr(y) required"
    },
    {
      "section_id": "evening_routine",
      "field_id": "__section_min__",
      "label": "At least 1 Evening Routine entr(y) required"
    }
  ]
}
```

`__section_min__` (double-underscore prefix) is a **sentinel** — it means "this whole section needs at least one row", not a specific field. Do NOT try to highlight a named input field.

**Flutter action (Issue #18):**
1. When `field_id == "__section_min__"` in `missing_fields`, show a section-level required indicator on the routine card (e.g. "At least one routine entry required").
2. Do NOT show `morning_routine` or `evening_routine` as optional anywhere in the UI.
3. The "Next" / advance button should surface the agent's `section_min_unmet` message rather than silently failing.

---

## Issue #4 + #9 — Repeatable section sink wiring (CRITICAL)

### Status
- ✅ `RepeatableConfig` / `SectionSpec.repeatable` already on `step_schema.dart`
- ✅ `voice_event_model.dart` parses `row_added`, `repeatable_section_entered`, `repeatable_section_exited`
- ✅ `Step1PersonalInfoSchema` declares `emergency_contacts` with `repeatable: RepeatableConfig(min: 1, max: 5)`
- ❌ Sinks (`client_step1_voice_sink.dart` etc.) do not handle these events — agent says "added new contact" but no card appears, and field_updated values targeted at row N never land on a card.

### Fix — `voice_session_controller.dart`

Dispatch the events to the active sink:

```dart
case VoiceRowAdded(:final sectionId, :final newIndex):
  _sink.addRepeatableRow(sectionId, newIndex);
  break;
case VoiceRepeatableSectionEntered(:final sectionId, :final rowIndex):
  _sink.focusRepeatableRow(sectionId, rowIndex);
  break;
case VoiceRepeatableSectionExited(:final sectionId):
  _sink.unfocusRepeatableRow(sectionId);
  break;
```

### Fix — `client_step1_voice_sink.dart`

Add the three handlers. They should call into whatever method `Step1Controller` already uses for the manual "Add contact" button so voice and tap paths share the same code:

```dart
void addRepeatableRow(String sectionId, int newIndex) {
  if (sectionId == 'emergency_contacts') {
    _step1Ctrl.addEmptyEmergencyContact();
    _step1Ctrl.scrollToEmergencyContact(newIndex);
  }
}

void focusRepeatableRow(String sectionId, int rowIndex) {
  if (sectionId == 'emergency_contacts') {
    _step1Ctrl.highlightEmergencyContactRow(rowIndex);
  }
}

void unfocusRepeatableRow(String sectionId) {
  if (sectionId == 'emergency_contacts') {
    _step1Ctrl.clearEmergencyContactHighlight();
  }
}
```

### Fix — `onFieldUpdated` in the same sink

When `repeatableIndex != null`, route to the correct row:

```dart
void onFieldUpdated(String section, String field, dynamic value, {int? repeatableIndex, double confidence = 1.0}) {
  if (section == 'emergency_contacts' && repeatableIndex != null) {
    final row = _step1Ctrl.emergencyContactRowAt(repeatableIndex);
    switch (field) {
      case 'name':     row.nameCtrl.text = value as String;
      case 'relation': row.relation.value = value as String;
      case 'email':    row.emailCtrl.text = value as String;
      case 'phone':    row.phoneCtrl.text = value as String;
    }
    return;
  }
  // existing non-repeatable routing...
}
```

### Verify
1. Start a step-1 voice session, fill required fields.
2. Say "I'd like to add another emergency contact" → empty card appears.
3. Provide name, relation, email, phone → values land on the new row (not the first row).

---

## Issue #5 — Pass `initialState: null` on fresh voice sessions (PARTIAL)

### Why
After completing a voice flow once, restarting voice on the same step sends `initialState: { ...prior voice values... }` instead of starting fresh. The backend's compatibility shim then synthesises a `returning_same_page` bootstrap and the agent says "I see your name is X — confirm?" instead of greeting fresh.

### Status
`CreateVoiceSessionParams` already has the optional `initialState` field. It's just relying on default-omission; that lets a stale value sneak in. Make the null explicit.

### Fix — `voice_session_controller.dart`

For brand-new sessions (not resumes), explicitly pass `initialState: null` and rely entirely on the `bootstrap` envelope:

```dart
final result = await _create(CreateVoiceSessionParams(
  participantId: _participantId,
  tenantId: _tenantId,
  locale: _locale,
  schema: _stepConfig.schema,
  initialState: null,        // ← explicit
  bootstrap: bootstrap,
));
```

### Verify
Complete a voice session. Restart voice on the same step. The agent must start with a generic greeting (no readback of prior values).

---

## Issue #8 — Send `field_errors` alongside `field_status` (PARTIAL)

### Why
`field_status: invalid` tells Gemini a field is broken but not why. Adding `field_errors` lets the agent paraphrase the actual validator message ("Make sure that's 10 digits, no spaces") instead of a generic "didn't catch that — try again".

### Status
`voice_session_controller.dart` already sets `field_status` in outbound `screen_state_v2`. The `field_errors` key is missing.

### Wire contract — `screen_state_v2` (additive)

```json
{
  "type": "screen_state_v2",
  "data": {
    "step_id": "personal_information",
    "focused_section": "basics",
    "focused_field": "phone",
    "field_status": {
      "basics.phone": "invalid",
      "basics.email": "filled"
    },
    "field_errors": {
      "basics.phone": "Must be 10 digits with no spaces"
    },
    "repeatable_rows": {},
    "ui_flags": {}
  }
}
```

### Rules
- Keys in `field_errors` use the same `section.field` paths as `field_status`.
- Only include a path in `field_errors` if its `field_status` is `invalid`.
- Reason strings are paraphrased to the user verbatim — keep them human (no regexes, no error codes).

### Fix
Extend the current `_currentFieldStatus()` to also return errors:

```dart
({Map<String, String> status, Map<String, String> errors}) _currentScreenState() {
  final status = <String, String>{};
  final errors = <String, String>{};
  for (final entry in _voiceToSena.entries) {
    final ctrl = _controllerFor(entry.value);
    final text = ctrl.text;
    final validatorMessage = _validatorFor(entry.key)?.call(text);
    if (validatorMessage != null) {
      status[entry.key] = 'invalid';
      errors[entry.key] = validatorMessage;
    } else if (text.isEmpty) {
      status[entry.key] = 'empty';
    } else {
      status[entry.key] = 'filled';
    }
  }
  return (status: status, errors: errors);
}
```

Then pass both into `sendScreenStateV2`.

### Verify
Type "abc" into the phone field, focus a different field. The agent should re-ask with a phone-format hint, not a generic "could you try again".

---

## Issue #13 — UX polish (PARTIAL)

### Status
- ✅ `readonly_paths` is parsed off the bootstrap and lives on the controller.
- ❌ No visual disabled-state on input fields when they appear in `readonly_paths`.
- ❌ `field_updated.confidence` is received but no colour signal is rendered.

### A. Readonly fields — visual disabled state

When `bootstrap.readonly_paths` includes a field, the corresponding text input should:
- Render with `enabled: false` (or `readOnly: true`)
- Show a small lock icon trailing the input
- Not respond to taps that would open the keyboard

The user just heard "Your email is locked for this step" — the visual must match.

### B. Confidence colouring on `field_updated`

```dart
final color = switch (confidence) {
  >= 0.9 => AppColors.success,    // green — committed
  >= 0.7 => AppColors.warning,    // amber — soft visual flag
  _      => AppColors.error,      // red
};
```

Note: with the new backend B5 gate, `confidence < 0.90` never commits — so amber/red dots will only appear on legacy events (server-side fallback only). The amber/red branches stay as defensive UI.

### Verify
- Lock icon visible on `basics.email` when bootstrap declares it readonly.
- After voice fills `basics.gender` with confidence ≥ 0.90, the chip glows green.

---

## Issue #16 — Render-after-validation invariant (CRITICAL — NEW 2026-05-11)

### Why
The backend now enforces a strict contract: a captured value DOES NOT EXIST in the form until `update_field` returns `{ok: true}`. The UI must mirror this. Otherwise the user sees a value appear (optimistic render), then the backend rejects it (validation, low confidence, lock conflict), and the value either lingers wrongly or flickers out — both are bad UX.

### The rule
- Do NOT bind a voice-captured value into a `TextEditingController`, `Rx<T>` value, or any UI-visible state until you receive a `field_updated` event from the WS.
- Do NOT show a transcript echo or "..." placeholder inside the target FORM field while the value is in flight. The voice transcript pane MAY show the user's spoken words (that's `user_said` — a separate channel).
- Treat these server responses as "value does NOT exist" — render nothing in the field:
  - `{rejection: {code: CONFIRM_REQUIRED}}` — value is in limbo, awaiting confirmation
  - `{rejection: {code: PENDING_CONFIRMATION_LOCKED}}` — a different field is blocking
  - `{rejection: {code: dob_under_18 / au_state_invalid / email_disposable / ...}}` — value rejected
- Only `field_updated` is authoritative. There is no client-side prediction.

### Fix — `client_step*_voice_sink.dart`
The existing `onFieldUpdated` handler is already the only path that mutates form controllers. Audit your sinks to make sure NO other listener (e.g. an optimistic preview on `user_said`) writes to those controllers.

### Verify
1. Speak a deliberately invalid phone ("blah blah blah"). The transcript pane shows your words; the phone form field stays blank. The agent re-asks.
2. Speak a phone with a wrong digit slowly enough that confidence < 0.90. The agent says "I heard X — is that right?" — the phone form field is STILL blank. After you say "yes", `field_updated` arrives and the value finally lands.
3. While in the "is that right?" state, try to use the manual UI to enter a different field. The backend rejects with `PENDING_CONFIRMATION_LOCKED` — surface that gracefully ("Please confirm the previous value first").

---

## Backend Wire Contracts (reference)

### Server → Client WS events

| Event | Payload | What you do |
|-------|---------|-------------|
| `ready` | `{state, prompt_version, coverage}` | Session live; start mic |
| Binary | raw PCM16 24kHz mono | Feed to audio player |
| `turn_start` | — | Set `_agentSpeaking = true` |
| `turn_complete` | — | Set `_agentSpeaking = false` |
| `interrupted` | — | Set `_agentSpeaking = false`; `_player.flush()` |
| `user_said` | `{text}` | Append to transcript view |
| `agent_said` | `{text}` | Append to transcript view |
| `field_updated` | `{section, field, value, repeatable_index?, confidence, turn_id}` | Apply to UI (`value` can be String OR List<String>) |
| `state` | `{state: <full FormState>}` | Reconcile UI from full snapshot |
| `row_added` | `{section_id, new_index}` | **Issue #4/#9 — render empty card** |
| `repeatable_section_entered` | `{section_id, row_index, intent}` | **Issue #4 — focus row** |
| `repeatable_section_exited` | `{section_id}` | **Issue #4 — unfocus row** |
| `field_skipped_warning` | `{missing_count, required_filled, required_total, missing_fields[{section_id, field_id, label?}]}` | Show required-field indicators. `field_id == "__section_min__"` means section-level (whole section needs ≥1 row) — do not highlight a named input. |
| `validation_rejection` | `{section_id, field_id?, code, reason_human, repeatable_index?, allowed_values?[]}` | Inline error display. `allowed_values` present only for `enum_invalid` — show chip picker. See rejection codes table below. |

### New rejection codes (2026-05-11)

| Code | Meaning | What Flutter does |
|------|---------|-------------------|
| `CONFIRM_REQUIRED` | Backend B5 — low-confidence capture awaits user "yes". Heard value NOT rendered. | Show transcript-only; do not paint the field. |
| `PENDING_CONFIRMATION_LOCKED` | A different field is the current AWAITING_CONFIRMATION target. Now rare — most cross-field bleeds are buffered as `DEFERRED` instead. | Surface as inline error: "Please confirm the previous value first." |
| `DEFERRED` | C2 — backend buffered this call onto `pending_batch`. Will auto-replay when the lock clears. | **Do nothing.** The buffered call will fire `field_updated` later when it commits. No rollback, no retry. |
| `BUFFER_FULL` | C2 — buffer cap (32 entries) reached. Hard reject. | Surface: "Too many updates queued — please confirm the previous answer." Same UX as `PENDING_CONFIRMATION_LOCKED`. |
| `au_state_invalid` | Backend B4 — value isn't one of NSW/VIC/QLD/SA/WA/TAS/ACT/NT (or a recognised full-name alias). | Re-ask via agent; inline state-enum hint on field. |
| `email_disposable` | Backend M3 — disposable inbox domain (mailinator, guerrillamail, etc.). | Re-ask; suggest permanent email. |
| `dob_under_18` | Backend `_v_dob` — participant under 18 at today's date. | Agent reads `reason_human` verbatim and closes session politely. |
| `enum_invalid` | Value not in the field's schema `options` list (e.g. `mode_of_communication`). `allowed_values[]` is always present on this code. | Show chip-group / multi-select picker with `allowed_values`; submit selection as `List<String>`. |
| `emergency_phone_matches_client` | Cross-field — emergency contact phone equals participant phone. | Re-ask the emergency contact's phone. |
| `emergency_phone_duplicate` | Cross-field — two emergency contacts share the same phone. | Re-ask the duplicate row's phone. |
| `emergency_email_matches_client` | Cross-field — emergency contact email equals participant email. | Re-ask the emergency contact's email. |
| `emergency_email_duplicate` | Cross-field — two emergency contacts share the same email. | Re-ask the duplicate row's email. |
| `step_completed` | `{webhook_delivered}` | Close voice modal, advance step (controller also calls `POST .../complete`) |
| `escalated` | `{reason, transcript_excerpt}` | Show safety message; close voice |
| `go_away` | `{time_left_ms}` | Schedule resume reconnect |
| `resumable` | `{handle, ttl_sec}` | Save handle for next reconnect |
| `error` | `{code, message}` | Show message; pair with close code |

### Client → Server WS messages

| Type | Payload | When |
|------|---------|------|
| `start` | `{type: "start"}` | First message after WS open. Required handshake. |
| Binary | raw PCM16 16kHz mono | Continuous mic stream while not muted |
| `user_text` | `{text}` | Typed-input alternative |
| `audio_end` | — | End-of-utterance flush |
| `screen_state_v2` | full v2 payload | On focus change, debounced 200ms — **Issue #8 — include `field_errors`** |
| `validation_failed` | `{section_id, field_id, repeatable_index?, reason_human, code?, attempted_value?}` | When the frontend validator rejects a value |
| `validation_cleared` | `{section_id, field_id, repeatable_index?}` | When a previously-failed field passes validation |
| `stop` | — | Graceful client close |

### REST endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/v1/onboarding/session` | Create session (sends schema + bootstrap inline). Returns `session_id`, `ws_url`, `expires_at`. |
| `GET` | `/v1/onboarding/session/{id}/state` | Read FormState |
| `PUT` | `/v1/onboarding/session/{id}/state` | Update FormState manually. **Returns 409 if WS is active** — close WS first. |
| `POST` | `/v1/onboarding/session/{id}/complete` | Finalise + fire webhook (already wired in `complete_voice_session_usecase.dart`) |

### WebSocket URL

```
wss://<host>:8083/ws/onboarding/{session_id}                     # fresh
wss://<host>:8083/ws/onboarding/{session_id}?resume=<handle>     # resume
```

---

## How validation flows end-to-end

There are **two validation channels** that feed the voice agent. Understanding both is key to knowing why you send certain WS messages and what you get back.

### A — Backend rejects (server → Flutter)

1. Voice agent calls `update_field(section, field, value)` as a Gemini function.
2. Backend validator runs. If rejected:
   - Emits a `validation_rejection` WS event to Flutter.
   - Records the error in `state.pending_validation_errors` (visible in the next `state` WS event).
   - The agent's next turn is prompted with the error reason and `allowed_values` (if `enum_invalid`).
3. Flutter shows inline error on the field.
4. `field_updated` fires **only** when `update_field` returns `{ok: true}` — this is the only authoritative signal that a value landed.

### B — Frontend rejects (Flutter → server)

1. Flutter's own AppValidators run on each field as the user types (phone format, required, etc.).
2. On failure: send `validation_failed` WS message → backend injects this into the Gemini prompt.
3. On clear: send `validation_cleared` WS message.
4. Also include `field_errors` in `screen_state_v2` (Issue #8) — the agent uses these to paraphrase the error aloud instead of a generic "try again".

### Summary

| Source | Event / message | Direction | Gemini sees it? |
|--------|----------------|-----------|----------------|
| Backend validator | `validation_rejection` WS event | server → Flutter | yes (in next prompt turn) |
| Backend FormState | `pending_validation_errors` in `state` event | server → Flutter | yes |
| Flutter AppValidator | `validation_failed` WS message | Flutter → server | yes |
| Flutter AppValidator | `validation_cleared` WS message | Flutter → server | yes |
| Flutter AppValidator | `field_errors` in `screen_state_v2` | Flutter → server | yes |

---

## Audio Format Spec

| Direction | Encoding | Sample rate | Channels |
|-----------|----------|-------------|----------|
| Mic → server | raw PCM16 little-endian | 16000 Hz | mono |
| Server → speaker | raw PCM16 little-endian | 24000 Hz | mono |

Voice is `Aoede`; speech config language is `en-AU`.

---

## Final Checklist

- [ ] `flutter analyze` returns 0 warnings
- [ ] Say "add another emergency contact" — empty card appears, voice-fills the new row (Issue #4/#9)
- [ ] Restart voice on the same step — agent greets fresh, does NOT replay prior values (Issue #5)
- [ ] Type an invalid phone, focus another field — agent re-asks with the validator message paraphrased, not generic (Issue #8)
- [ ] Readonly fields show a lock icon when `bootstrap.readonly_paths` lists them (Issue #13A)
- [ ] Field chip glows green after a confident voice capture (Issue #13B)
- [ ] Form fields stay BLANK until `field_updated` arrives — no optimistic render (Issue #16)
- [ ] `CONFIRM_REQUIRED` rejection shows in transcript but does not write to form (Issue #16)
- [ ] Say a value not in the `mode_of_communication` list (e.g. "Walkie Talkies") → `validation_rejection` arrives with `code: enum_invalid` + `allowed_values`; chip-group picker renders with the allowed options (Issue #17)
- [ ] Try to advance from step 2 with no morning routine entries → section-level required indicator appears; "Next" surfaces the agent's message rather than silently failing (Issue #18)
- [ ] `field_skipped_warning` with `field_id == "__section_min__"` does not crash or attempt to highlight a named field (Issue #18)

---

## Where the backend lives

```
SENA_AI/sena-ai/services/onboarding/
├── src/onboarding/
│   ├── api/routes.py              # POST /v1/onboarding/session — accepts bootstrap; auto-hydrates participant_display_name + prior_pages from CSC bucket
│   ├── api/ws_routes.py           # WSS /ws/onboarding/{session_id}?resume=
│   ├── services/
│   │   ├── cross_screen_context.py  # 5-field allowlist for prior_pages
│   │   ├── tools.py                  # update_field (B5 low-confidence gate), advance_step (affirmative gate)
│   │   ├── validators/field_rules.py # AU state validator + full table
│   │   └── gemini_live.py
│   └── prompts/onboarding_system.md  # Rule 3, 7b, 10 — updated 2026-05-11
└── tests/                            # pytest services/onboarding/tests -q
```
