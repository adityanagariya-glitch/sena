# Flutter Dev Handoff — SENA Voice Onboarding

**Audience:** Flutter developer integrating with the SENA voice onboarding backend.
**Updated:** 2026-05-02
**Backend status:** complete and tested (78/78 unit tests pass). All remaining work is in `lib/`.

This is the single document you need. Apply the 9 issues below in the order shown.

---

## TL;DR

The backend is final. The Flutter app must change in 9 places to:

1. Stop the agent from hearing its own playback (echo loop).
2. Cut stale audio when the user interrupts.
3. Send a complete schema with field order matching the UI form.
4. Support repeatable sections (emergency contacts, etc).
5. Stop pre-filling new sessions with prior voice-captured values.
6. Send live screen-state on focus change (recommended).
7. Send a structured `bootstrap` envelope when creating a session.
8. Send `field_errors` reasons alongside `field_status` when the form rejects a value.
9. Render a new card when the backend emits `row_added`.

**If you do nothing else, do issues 1, 1b, 3, 4, 7. Without those the agent cannot collect every field, cannot stop echoing itself, and cannot cleanly resume sessions.**

---

## Implementation Order

| Order | Issue | Why first |
|-------|-------|-----------|
| 1 | #1 Echo mute gate | Without this, the assistant talks to itself in a loop. |
| 2 | #1b Flush audio on interrupt | Interruption feels broken until this is in. |
| 3 | #3 Replace schema with all 16 fields | Gemini cannot save a field that isn't in the schema — silent rejection. |
| 4 | #4 Repeatable section support | Required to collect emergency contacts. |
| 5 | #7 Send `bootstrap` envelope | Locks in clean session-isolation contract. |
| 6 | #5 Pass `initialState: null` for fresh sessions | Stops stale voice values polluting new sessions. |
| 7 | #2 Match schema field order to UI | Mostly handled by #3 if you copy the order from there. |
| 8 | #8 Send `field_errors` with `field_status` | Lets Gemini give useful re-ask hints. |
| 9 | #9 Subscribe to `row_added` event | Renders empty card when user says "add another contact". |
| 10 | #6 Live screen-state sync (FocusNode listeners) | Polish — Gemini follows the user's cursor in real time. |

---

## Files you will edit

```
lib/features/voice_onboarding/presentation/controllers/voice_session_controller.dart
lib/features/voice_onboarding/domain/entities/step_schema.dart
lib/features/voice_onboarding/data/models/step_schema_model.dart
lib/features/voice_onboarding/domain/usecases/create_voice_session_usecase.dart
lib/features/voice_onboarding/data/datasources/voice_session_datasource.dart
lib/core/voice_schemas/step1_personal_info_schema.dart
lib/features/voice_onboarding/presentation/widgets/client_step1_voice_sink.dart
lib/features/client/presentation/dashboard/home/client_onboarding/steps/step_content/personal_details_step_content.dart
lib/features/voice_onboarding/presentation/audio/voice_audio_player.dart
```

---

## Issue #1 — Echo loop (CRITICAL)

### Symptom
Sena speaks → phone speaker plays back → mic picks it up → server transcribes the agent's own speech → Gemini "hears itself" and either interrupts or talks in a loop.

### Why backend can't fix it
Mic audio originates on the phone. The backend must receive audio unconditionally (gating mic on the server breaks Gemini's VAD after 2-4 turns).

### Fix — `voice_session_controller.dart`

**Step 1.** Add an `_agentSpeaking` flag (around line 87 with the other private fields):

```dart
/// True while Gemini is speaking. Mic chunks are suppressed during this
/// window to prevent the assistant's own playback audio from looping back.
bool _agentSpeaking = false;
```

**Step 2.** In `_handleEvent`, replace the no-op turn handlers (around line 288):

```dart
case VoiceTurnStart():
  _agentSpeaking = true;
  break;
case VoiceTurnComplete():
case VoiceInterrupted():
  _agentSpeaking = false;
  break;
```

**Step 3.** In `_startMic`, gate the mic stream (around line 325):

```dart
_micSub = stream.listen(
  (chunk) {
    if (!_agentSpeaking) _sendAudio(chunk);
  },
  onError: (Object e) =>
      AppLogger.error('VoiceCtrl', 'mic stream error: $e'),
);
```

### Verify
1. Start a session. Sena greets. Confirm Sena does NOT interrupt herself.
2. Speak after `turn_complete`. Sena should respond to you, not herself.
3. Long session (>5 turns). Mic still works.

---

## Issue #1b — Stale audio plays after interrupt (CRITICAL)

### Symptom
User starts speaking → Gemini sends `interrupted` → user keeps hearing the agent for another 1-3 seconds because audio chunks already in the playback queue keep playing.

### Fix — `voice_audio_player.dart`

The exact API depends on your audio package, but the pattern is:

1. Track every active audio source (chunk player, buffer source, etc).
2. Add `Future<void> flush()` that:
   - Stops the active source.
   - Clears the queue.
   - Resets the playback head.
3. Call `_player.flush()` from the `VoiceInterrupted` handler.

```dart
class VoiceAudioPlayer {
  final List<_PendingChunk> _queue = [];
  AudioSource? _activeSource;

  Future<void> feed(Uint8List pcm) async {
    final chunk = _PendingChunk(pcm);
    _queue.add(chunk);
    _drainQueue();
  }

  /// Cancel every queued chunk and stop the active source.
  Future<void> flush() async {
    for (final c in _queue) c.cancelled = true;
    _queue.clear();
    await _activeSource?.stop();
    _activeSource = null;
  }
}
```

In `voice_session_controller.dart`:

```dart
case VoiceInterrupted():
  _agentSpeaking = false;
  await _player.flush();   // ← NEW
  break;
```

### Verify
1. Let Sena begin a long sentence.
2. Speak over her ("Stop, wait!").
3. Sena's audio should cut within ~150 ms — not finish the sentence.

---

## Issue #2 — Schema field order doesn't match UI (CRITICAL)

Solved together with Issue #3 — copy the order from there.

The backend follows the schema verbatim — whatever order Flutter sends is the order Gemini collects.

---

## Issue #3 — Schema missing 10+ fields (CRITICAL)

### Symptom
Gemini collects ~5 fields and calls `advance_step`. Gender, address, languages, emergency contacts are never collected — the participant must type them.

### Why
Backend `tools.py::_update_field` validates against `section.all_fields()`. Anything not in the schema is silently rejected. The current Flutter schema declares only 5 fields.

### Fix — `step1_personal_info_schema.dart`

Replace the `Step1PersonalInfoSchema` class with the 16-field version. Order matches the UI form.

```dart
import 'package:sena_mobile/core/voice_schemas/voice_step_config.dart';
import 'package:sena_mobile/features/voice_onboarding/domain/entities/step_schema.dart';

class Step1PersonalInfoSchema implements VoiceStepConfig {
  const Step1PersonalInfoSchema();

  @override
  StepSchema get schema => const StepSchema(
        stepId: 'personal_information',
        title: 'Personal Information',
        progressPercent: 20,
        sections: [
          SectionSpec(
            id: 'basics',
            title: 'About you',
            fields: [
              FieldSpec(id: 'full_name',            label: 'Full Name',           type: FieldType.text,        required: true),
              FieldSpec(id: 'email',                label: 'Email Address',       type: FieldType.email,       required: true),
              FieldSpec(id: 'phone',                label: 'Phone Number',        type: FieldType.phone,       required: true),
              FieldSpec(id: 'date_of_birth',        label: 'Date of Birth',       type: FieldType.date,        required: true),
              FieldSpec(id: 'gender',               label: 'Gender',              type: FieldType.choice,      required: true,
                        choices: ['Male', 'Female', 'Non-binary', 'Prefer not to say', 'Other']),
              FieldSpec(id: 'about_me',             label: 'About Me',            type: FieldType.longText,    required: true),
              FieldSpec(id: 'preferred_languages',  label: 'Preferred Language',  type: FieldType.multiChoice, required: true,
                        choices: ['English', 'Mandarin', 'Cantonese', 'Arabic', 'Vietnamese', 'Greek', 'Italian', 'Other']),
              FieldSpec(id: 'interpreter_required', label: 'Interpreter Required',type: FieldType.choice,      required: true,
                        choices: ['Yes', 'No']),
            ],
          ),
          SectionSpec(
            id: 'home_address',
            title: 'Home Address',
            fields: [
              FieldSpec(id: 'address',  label: 'Street Address', type: FieldType.text, required: true),
              FieldSpec(id: 'state',    label: 'State',          type: FieldType.text, required: true),
              FieldSpec(id: 'city',     label: 'City / Suburb',  type: FieldType.text, required: true),
              FieldSpec(id: 'zip_code', label: 'Postcode',       type: FieldType.text, required: true),
            ],
          ),
          SectionSpec(
            id: 'service_address',
            title: 'Service Address',
            fields: [
              FieldSpec(id: 'address',  label: 'Service Street Address', type: FieldType.text, required: false),
              FieldSpec(id: 'state',    label: 'State',                  type: FieldType.text, required: false),
              FieldSpec(id: 'city',     label: 'City / Suburb',          type: FieldType.text, required: false),
              FieldSpec(id: 'zip_code', label: 'Postcode',               type: FieldType.text, required: false),
            ],
          ),
          // emergency_contacts goes here — see Issue #4 for repeatable shape
        ],
      );

  // Voice path → Sena path mapping (every new field must map to the matching
  // ClientStep1Controller getter).
  static const Map<String, String> _voiceToSena = {
    'basics.full_name':            'personalDetails.fullName',
    'basics.email':                'personalDetails.email',
    'basics.phone':                'personalDetails.phone',
    'basics.date_of_birth':        'personalDetails.dateOfBirth',
    'basics.gender':               'personalDetails.gender',
    'basics.about_me':             'personalDetails.aboutMe',
    'basics.preferred_languages':  'personalDetails.preferredLanguages',
    'basics.interpreter_required': 'personalDetails.interpreterRequired',
    'home_address.address':        'personalDetails.address',
    'home_address.state':          'personalDetails.state',
    'home_address.city':           'personalDetails.city',
    'home_address.zip_code':       'personalDetails.zipCode',
    'service_address.address':     'personalDetails.serviceAddress',
    'service_address.state':       'personalDetails.serviceState',
    'service_address.city':        'personalDetails.serviceCity',
    'service_address.zip_code':    'personalDetails.serviceZipCode',
  };
  // (Reverse map _senaToVoice and _labels follow the same pattern — see the
  // existing file for the shape.)

  @override
  String? toSenaPath(String section, String field) =>
      _voiceToSena['$section.$field'];
}
```

### Update `ClientStep1VoiceSink`

Add routing cases for every new sena path: `gender`, `preferredLanguages`, `interpreterRequired`, `address`, `state`, `city`, `zipCode`, `serviceAddress`, `serviceState`, `serviceCity`, `serviceZipCode`. Apply enum values as the option string. Booleans (`interpreterRequired`) accept "Yes"/"No" or true/false.

### Verify
Speak through every field of the form. Confirm each one updates the matching UI input.

---

## Issue #4 — Add repeatable section support (CRITICAL)

### Why
Emergency contacts is a repeatable section. The `StepSchema` entity has no `repeatable` field, so Gemini cannot grow the list.

### Fix — `step_schema.dart`

```dart
class RepeatableConfig {
  final int min;
  final int max;
  const RepeatableConfig({this.min = 0, this.max = 10});
}

class SectionSpec {
  final String id;
  final String title;
  final List<FieldSpec> fields;       // for non-repeatable
  final List<FieldSpec>? itemFields;  // for repeatable
  final RepeatableConfig? repeatable;

  const SectionSpec({
    required this.id,
    required this.title,
    required this.fields,
    this.itemFields,
    this.repeatable,
  });

  bool get isRepeatable => repeatable != null;
}
```

### Fix — `step_schema_model.dart`

`SectionSpecModel.toJson()` must emit:

```json
{
  "id": "emergency_contacts",
  "label": "Emergency Contacts",
  "repeatable": { "min": 1, "max": 5 },
  "item_fields": [ /* ... */ ]
}
```

Also emit `voice_repeatable_sections: ["emergency_contacts"]` on `StepSchemaModel.toJson()` — the backend uses this to gate the `add_repeatable_row` tool.

### Add the section to `Step1PersonalInfoSchema`

```dart
SectionSpec(
  id: 'emergency_contacts',
  title: 'Emergency Contacts',
  fields: [],  // empty for repeatable
  repeatable: RepeatableConfig(min: 1, max: 5),
  itemFields: [
    FieldSpec(id: 'name',     label: 'Contact Name',  type: FieldType.text,   required: true),
    FieldSpec(id: 'relation', label: 'Relationship',  type: FieldType.choice, required: true,
              choices: ['Parent', 'Sibling', 'Partner', 'Friend', 'Carer', 'Other']),
    FieldSpec(id: 'email',    label: 'Contact Email', type: FieldType.email,  required: true),
    FieldSpec(id: 'phone',    label: 'Contact Phone', type: FieldType.phone,  required: true),
  ],
),
```

Voice→sena mapping for repeatables uses indexed paths: `personalDetails.emergencyContacts[0].name`. Wire this into `ClientStep1VoiceSink` so each indexed update lands on the right `ClientOnboardingEmergencyContactRow`.

### Verify
Say "I'd like to add an emergency contact". Confirm `add_repeatable_row` fires (see Issue #9 for the WS event), then provide a name, phone, etc. — each value lands on row index 0.

---

## Issue #5 — New session re-loads stale voice values (HIGH)

### Symptom
Complete a voice session. Restart voice. New session sees the prior values as `initial_state` and "confirms" them instead of starting fresh.

### Fix — `voice_session_controller.dart`

For brand-new sessions (not resumes), pass `initialState: null`:

```dart
final result = await _create(CreateVoiceSessionParams(
  participantId: _participantId,
  tenantId: _tenantId,
  locale: _locale,
  schema: _stepConfig.schema,
  initialState: null,  // was: initial — let Gemini collect everything fresh
));
```

### Verify
Run a session, restart. New session asks for name/phone fresh, doesn't say "I see your name is X — confirm?".

---

## Issue #6 — Live screen-state sync (RECOMMENDED)

### Why
After Issues 2-4 the schema is complete, but it's still sent ONCE at session start. If the user taps a different field mid-session, Gemini doesn't know.

### Fix — `voice_session_controller.dart`

Add a method that forwards focus + status to the backend:

```dart
Future<void> sendScreenState({
  required String focusedSection,
  required String focusedField,
  required Map<String, String> fieldStatus,    // 'filled' | 'empty' | 'invalid'
  Map<String, String> fieldErrors = const {},  // see Issue #8
  Map<String, int>? repeatableRows,
}) async {
  final session = _session;
  if (session == null) return;
  await _stream.sendScreenStateV2(
    sessionId: session.sessionId,
    payload: {
      'step_id': _stepConfig.schema.stepId,
      'focused_section': focusedSection,
      'focused_field': focusedField,
      'field_status': fieldStatus,
      'field_errors': fieldErrors,
      'repeatable_rows': repeatableRows ?? {},
      'ui_flags': {},
    },
  );
}
```

### Datasource — `voice_session_datasource.dart`

```dart
Future<void> sendScreenStateV2(Map<String, dynamic> payload) async {
  final frame = jsonEncode({
    'type': 'screen_state_v2',
    'data': payload,
  });
  _channel.sink.add(frame);  // same sink as audio_end / stop
}
```

### Wire `FocusNode`s — `personal_details_step_content.dart`

```dart
fullNameFocus.addListener(() {
  if (!fullNameFocus.hasFocus) return;
  voiceCtrl.sendScreenState(
    focusedSection: 'basics',
    focusedField: 'full_name',
    fieldStatus: _currentFieldStatus(),
  );
});
```

`_currentFieldStatus()` returns a map of every voice-mapped path → `filled` / `empty` / `invalid` based on controller text + validator result. **Debounce 200ms** to avoid flooding the WS.

### Verify
Start voice. Without speaking, tap `Email`. Within ~1 sec Gemini pivots: "I see you're on email — what's your email address?" instead of asking for `full_name` first.

---

## Issue #7 — Send `bootstrap` envelope (HIGH — NEW)

### Why
The backend now accepts a structured `bootstrap` envelope on session create. It tells Gemini exactly what state to inherit (Rule 1 strict isolation, Rule 2 multi-page handoff) and which fields are read-only (Rule 3).

### Wire contract

`POST /v1/onboarding/session` request body:

```json
{
  "participant_id": "...",
  "step": "personal_information",
  "schema": { /* StepSchema */ },
  "bootstrap": {
    "mode": "page_handoff",
    "current_page_values": {
      "basics.full_name": "Jane",
      "basics.phone": "0412345678",
      "basics.email": "jane@x.com"
    },
    "readonly_paths": ["basics.email"],
    "prior_pages": {
      "step_0_invitation": { "basics.email": "jane@x.com" }
    },
    "participant_display_name": "Jane"
  },
  "locale": "en-AU"
}
```

`bootstrap.mode` values:
- `new_user` — fresh participant, no prior data. Generic greeting.
- `returning_same_page` — same page, fresh voice session. Don't re-ask filled required fields.
- `page_handoff` — moved here from a prior step. Acknowledge by name.

### Fix — `create_voice_session_usecase.dart`

Add a `bootstrap` parameter to the params class:

```dart
class CreateVoiceSessionParams {
  final String participantId;
  final String tenantId;
  final String locale;
  final StepSchema schema;
  final Map<String, dynamic>? initialState;  // legacy — leave null per Issue #5
  final SessionBootstrap bootstrap;          // NEW — required
}

class SessionBootstrap {
  final String mode;  // 'new_user' | 'returning_same_page' | 'page_handoff'
  final Map<String, dynamic> currentPageValues;
  final List<String> readonlyPaths;
  final Map<String, Map<String, dynamic>> priorPages;
  final String? participantDisplayName;

  Map<String, dynamic> toJson() => {
    'mode': mode,
    'current_page_values': currentPageValues,
    'readonly_paths': readonlyPaths,
    'prior_pages': priorPages,
    if (participantDisplayName != null)
      'participant_display_name': participantDisplayName,
  };
}
```

Pass it into the request body in the datasource.

### How to populate it

| Scenario | Bootstrap |
|----------|-----------|
| First-ever onboarding, nothing typed yet | `mode: 'new_user'`, everything else empty/null |
| User opened the page, typed a few fields manually, then hit "Voice" | `mode: 'returning_same_page'`, `current_page_values: <typed values>`, `readonly_paths: <fields user shouldn't be able to change e.g. email>` |
| User finished page 1, navigated to page 2 | `mode: 'page_handoff'`, `prior_pages: { step_1: <values> }`, `participant_display_name: <name they gave on page 1>` |

### Verify
- `new_user`: agent greets generically, asks for name first.
- `returning_same_page` with name+phone+email pre-filled, email readonly: agent says "I see your name is X and phone is Y — confirm?" and treats email as read-only.
- `page_handoff` with prior data: agent says "Hi Jane, welcome to the next step."

---

## Issue #8 — Send `field_errors` with `field_status` (HIGH — NEW)

### Why
When Flutter rejects a value (regex fail, network error), the agent today just sees `field_status: invalid` and re-asks generically. Adding `field_errors` lets it say "looks like that wasn't a valid phone — make sure it's 10 digits with no spaces".

### Wire contract — `screen_state_v2` payload

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

Rules:
- Keys in `field_errors` must use the same dotted path (`section.field`) as in `field_status`.
- Only include a path in `field_errors` if its `field_status` is `invalid`.
- Reason strings are paraphrased to the user — keep them human (no regexes, no error codes).

### Fix

Extend `_currentFieldStatus()` (introduced in Issue #6) so it ALSO returns a parallel `Map<String, String> fieldErrors`. Pass both to `sendScreenState`.

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

### Verify
Type an invalid phone (`123`). On focus change, the screen_state_v2 frame includes `field_errors.basics.phone`. Next agent turn says: "It looks like the system didn't accept that phone — make sure it's 10 digits."

---

## Issue #9 — Subscribe to `row_added` event (HIGH — NEW)

### Why
When the user says "I'd like to add another emergency contact", the backend calls `add_repeatable_row` and emits a `row_added` WS event. Flutter must listen for this event and render an empty card for the new index.

### Wire contract — server-emitted WS event

```json
{
  "type": "row_added",
  "section_id": "emergency_contacts",
  "new_index": 1
}
```

### Fix — `voice_session_controller.dart`

In `_handleEvent`, add a case for `VoiceRowAdded`:

```dart
case VoiceRowAdded(:final sectionId, :final newIndex):
  _sink.addRepeatableRow(sectionId, newIndex);
  break;
```

In `client_step1_voice_sink.dart` add the handler:

```dart
void addRepeatableRow(String sectionId, int newIndex) {
  if (sectionId == 'emergency_contacts') {
    _step1Ctrl.addEmptyEmergencyContact();
  }
  // Add cases for other repeatable sections as they appear.
}
```

`addEmptyEmergencyContact()` should call the existing controller method that the "Add another" button uses — same path, just triggered by voice instead of tap.

### Verify
Say "Add another emergency contact". An empty card appears. Then say the contact's name, phone, etc. — values land in that new card.

---

## Backend Wire Contracts (reference)

### Server → Client WS events

| Event | Payload | What you do |
|-------|---------|-------------|
| `ready` | `{state, prompt_version, coverage}` | Session live; start mic |
| `turn_start` | — | Set `_agentSpeaking = true` (Issue #1) |
| `turn_complete` | — | Set `_agentSpeaking = false` |
| `interrupted` | — | Set `_agentSpeaking = false`; `_player.flush()` (Issue #1b) |
| `user_said` | `{text}` | Display in transcript |
| `agent_said` | `{text}` | Display in transcript |
| `field_updated` | `{section, field, value, repeatable_index?, confidence}` | Apply to UI controller |
| `state` | `{state}` | Full state snapshot — reconcile UI |
| `row_added` | `{section_id, new_index}` | Render empty card (Issue #9) |
| `step_completed` | — | Close voice modal, advance UI |
| `escalated` | `{reason, transcript_excerpt}` | Display safety message |
| `go_away` | `{time_left_ms}` | Call resume endpoint before expiry |
| `resumable` | `{handle, ttl_sec}` | Save handle for next reconnect |
| `error` | `{code, message}` | Display + close if fatal |

### Client → Server WS messages

| Type | Payload | When |
|------|---------|------|
| `start` | `{type: "start"}` | First message after WS open |
| Binary | raw PCM16 16kHz mono | Continuous mic stream |
| `user_text` | `{text}` | Typed-input alternative |
| `audio_end` | — | End-of-utterance flush |
| `screen_state_v2` | full v2 payload (Issues #6, #8) | On focus change, debounced 200ms |
| `stop` | — | Graceful client close |

---

## Final Checklist

- [ ] `flutter analyze` returns 0 warnings
- [ ] Echo loop fixed — Sena does not interrupt herself
- [ ] Interruption cuts agent audio within 150 ms
- [ ] Schema declares all 16 personal-info fields in UI order
- [ ] Repeatable emergency contacts work — at least 1 required, agent offers "another?"
- [ ] Stop voice mid-step, restart — new session does NOT re-confirm prior voice values
- [ ] `bootstrap` envelope sent on every session create with the right `mode`
- [ ] Type an invalid phone, focus another field — agent re-asks with the validator message paraphrased
- [ ] Say "add another emergency contact" — empty card appears, voice-fills it
- [ ] Tap a field mid-session — agent pivots to that field within ~1s

---

## Where the backend lives

If you need to inspect anything backend-side:

```
SENA_AI/sena-ai/services/onboarding/
├── src/onboarding/
│   ├── api/routes.py           # POST /v1/onboarding/session
│   ├── api/ws_routes.py        # WSS /ws/onboarding/{session_id}
│   ├── models/
│   │   ├── schema_spec.py      # StepSchema, SectionSpec, FieldSpec
│   │   └── session_bootstrap.py  # SessionBootstrap (Issue #7)
│   ├── services/
│   │   ├── tools.py            # update_field, add_repeatable_row, advance_step
│   │   ├── screen_context.py   # ScreenStateV2 (Issues #6, #8)
│   │   └── gemini_live.py      # Live API bridge
│   └── prompts/onboarding_system.md  # Agent instructions
└── test_harness.html           # In-browser smoke test
```

Backend port: **8083**. Run with `uvicorn src.onboarding.main:create_app --factory --reload --port 8083`.

---

## Questions for backend team

If anything in this doc is unclear or you hit unexpected behaviour, drop a note with:
1. What you sent (paste the WS frame or the request body).
2. What you got back (paste the WS event or response JSON).
3. The session_id and approximate timestamp.

Backend logs every rejected `update_field` call with the reason (`update_field REJECTED — field 'X' not in section 'Y'`), every `multi_value applied`, every `silence_watchdog fired`, and every `interrupt_intent preserved`. Those four log lines are the fastest way to confirm something landed correctly.
