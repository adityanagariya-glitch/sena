# Flutter Dev Handoff — SENA Voice Onboarding

**Audience:** Flutter developer integrating with the SENA voice onboarding backend.
**Updated:** 2026-05-04
**Backend status:** complete and tested (78/78 unit tests pass). All remaining work is in `lib/`.

This single document covers every Flutter-side change required to ship the voice feature end-to-end. Apply the issues in the order shown.

---

## TL;DR

The backend is final. The Flutter app must change in 13 places to:

1. Stop the agent from hearing its own playback (echo loop).
1b. Cut stale audio when the user interrupts.
2. Send a complete schema with field order matching the UI form.
3. Cover every field the user is expected to fill (16, not 5).
4. Support repeatable sections (emergency contacts, etc).
5. Stop pre-filling new sessions with prior voice-captured values.
6. Send live screen-state on focus change.
7. Send a structured `bootstrap` envelope on session create.
8. Send `field_errors` reasons alongside `field_status`.
9. Render a new card when the backend emits `row_added`.
10. Accept array values in `field_updated` events (multi-value capture).
11. Implement the connection lifecycle and resume flow (`go_away`, `resumable`).
12. Handle every WS close code with the right user-facing fallback.
13. Surface UX changes — read-only fields, proactive optional prompts, confidence colouring.

**Critical-path subset (do these first):** 1, 1b, 3, 4, 7, 10, 11. Without those the agent cannot collect every field, cannot stop echoing itself, cannot survive a session drop, and cannot store multi-value answers.

---

## Implementation Order

| Order | Issue | Severity | Effort | Why |
|-------|-------|----------|--------|-----|
| 1 | #1 Echo mute gate | CRITICAL | 5 min | Without this the assistant talks to itself |
| 2 | #1b Flush audio on interrupt | CRITICAL | 15 min | Interrupt feels broken otherwise |
| 3 | #3 Replace schema with 16 fields | CRITICAL | 30 min | Backend rejects undeclared fields silently |
| 4 | #4 Repeatable section support | CRITICAL | 20 min | Required for emergency contacts |
| 5 | #10 Array values in `field_updated` | CRITICAL | 15 min | Multi-value answers crash today's handler |
| 6 | #7 Send `bootstrap` envelope | HIGH | 20 min | Activates Rules 1+2+3 server-side |
| 7 | #11 Resume flow + `go_away` handling | HIGH | 45 min | Without this long sessions silently drop |
| 8 | #5 `initialState: null` for fresh sessions | HIGH | 5 min | Stops stale voice values polluting new sessions |
| 9 | #2 Match schema field order to UI | CRITICAL | 5 min | Bundled with #3 |
| 10 | #12 WS close codes | HIGH | 20 min | User sees blank screen on otherwise-handled errors |
| 11 | #8 `field_errors` with `field_status` | HIGH | 15 min | Lets Gemini give useful re-ask hints |
| 12 | #9 Subscribe to `row_added` | HIGH | 15 min | Voice "add another contact" needs UI hook |
| 13 | #13 UX adjustments (readonly + proactive + confidence) | HIGH | 1 h | Voice flow is correct but visually confusing without |
| 14 | #6 Live screen-state sync (FocusNode listeners) | RECOMMENDED | 1 h | Polish — Gemini follows the user's cursor |

---

## Files you will edit

```
lib/features/voice_onboarding/presentation/controllers/voice_session_controller.dart
lib/features/voice_onboarding/presentation/audio/voice_audio_player.dart
lib/features/voice_onboarding/domain/entities/step_schema.dart
lib/features/voice_onboarding/domain/entities/voice_event.dart        // sealed event class — Issue #9, #10
lib/features/voice_onboarding/data/models/step_schema_model.dart
lib/features/voice_onboarding/data/models/voice_event_model.dart      // parses incoming WS frames
lib/features/voice_onboarding/domain/usecases/create_voice_session_usecase.dart
lib/features/voice_onboarding/data/datasources/voice_session_datasource.dart
lib/core/voice_schemas/step1_personal_info_schema.dart
lib/features/voice_onboarding/presentation/widgets/client_step1_voice_sink.dart
lib/features/client/presentation/dashboard/home/client_onboarding/steps/step_content/personal_details_step_content.dart
```

---

## Issue #1 — Echo loop (CRITICAL)

### Symptom
Sena speaks → speaker plays → mic picks it up → server transcribes the agent's own speech → Gemini "hears itself" and either interrupts or talks in a loop.

### Why backend can't fix it
Mic audio originates on the phone. The backend must receive audio unconditionally — gating mic on the server breaks Gemini's VAD after 2-4 turns (model audio for turn N+1 arrives before `turn_complete` of turn N, keeping the gate closed).

### Fix — `voice_session_controller.dart`

**Step 1.** Add the flag (around line 87 with the other private fields):

```dart
/// True while Gemini is speaking. Mic chunks are suppressed during this
/// window to prevent the assistant's playback audio from looping back.
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
3. Run >5 turns. Mic still works.

---

## Issue #1b — Stale audio plays after interrupt (CRITICAL)

### Symptom
User starts speaking → Gemini sends `interrupted` → user keeps hearing the agent for 1-3 seconds because audio chunks already scheduled in the playback queue keep playing.

### Fix — `voice_audio_player.dart`

Track every active source and add a `flush()` that stops them. Wire to `VoiceInterrupted`.

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
Let Sena begin a long sentence. Speak over her. Sena's audio cuts within ~150 ms.

---

## Issue #2 — Schema field order doesn't match UI (CRITICAL)

The backend follows the schema verbatim. Bundled with Issue #3 — copy the order from there.

---

## Issue #3 — Schema missing 10+ fields (CRITICAL)

### Symptom
Gemini collects ~5 fields and calls `advance_step`. Gender, address, languages, emergency contacts are never collected.

### Why
Backend `tools.py::_update_field` validates against `section.all_fields()`. Anything not in the schema is rejected silently with `{"ok": false, "error": "field 'X' not in section 'Y'"}` — Gemini relays it to the user as "I can't record X by voice."

### Fix — `step1_personal_info_schema.dart`

Replace `Step1PersonalInfoSchema` with the 16-field version. Order matches `personal_details_step_content.dart` exactly.

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

  @override
  String? toSenaPath(String section, String field) =>
      _voiceToSena['$section.$field'];
}
```

### Update `ClientStep1VoiceSink`
Add routing cases for every new sena path. Apply enum values as the option string. Booleans (`interpreterRequired`) accept "Yes"/"No" or true/false. Multi-value (`preferredLanguages`) accepts a list — see Issue #10 for the array-handling code.

### Verify
Speak through every field of the form. Confirm each updates the matching UI input.

---

## Issue #4 — Add repeatable section support (CRITICAL)

### Why
Emergency contacts is a repeatable section. The current `StepSchema` entity has no `repeatable` field, so Gemini cannot grow the list and `add_repeatable_row` rejects with "section X is not repeatable".

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

Also emit `voice_repeatable_sections: ["emergency_contacts"]` on `StepSchemaModel.toJson()`. The backend uses this to allow `add_repeatable_row` for those sections.

### Add the section to `Step1PersonalInfoSchema`

```dart
SectionSpec(
  id: 'emergency_contacts',
  title: 'Emergency Contacts',
  fields: [],
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

Voice→sena mapping for repeatables uses indexed paths: `personalDetails.emergencyContacts[0].name`. Wire in `ClientStep1VoiceSink`:

```dart
void onFieldUpdated(String section, String field, dynamic value, {int? repeatableIndex}) {
  if (section == 'emergency_contacts' && repeatableIndex != null) {
    final row = _step1Ctrl.emergencyContactRowAt(repeatableIndex);
    switch (field) {
      case 'name':     row.nameCtrl.text = value as String;
      case 'relation': row.relation.value = value as String;
      case 'email':    row.emailCtrl.text = value as String;
      case 'phone':    row.phoneCtrl.text = value as String;
    }
  }
  // ... non-repeatable cases
}
```

### Verify
Say "I'd like to add an emergency contact" — `row_added` fires (Issue #9), card appears, you provide name/phone — values land on row 0.

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
  initialState: null,        // legacy field — leave null
  bootstrap: bootstrap,      // see Issue #7
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
  final s = _currentScreenState();
  voiceCtrl.sendScreenState(
    focusedSection: 'basics',
    focusedField: 'full_name',
    fieldStatus: s.status,
    fieldErrors: s.errors,
  );
});
```

**Debounce 200ms** to avoid flooding the WS when a user tabs through fields.

### Verify
Start voice. Without speaking, tap `Email`. Within ~1 sec Gemini pivots: "I see you're on email — what's your email address?".

---

## Issue #7 — Send `bootstrap` envelope (HIGH — NEW THIS SESSION)

### Why
The backend now accepts a structured `bootstrap` envelope on session create. It tells Gemini exactly what state to inherit (Rule 1 strict isolation, Rule 2 multi-page handoff) and which fields are read-only (Rule 3).

### Wire contract — `POST /v1/onboarding/session`

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

**Backwards compatibility:** If `bootstrap` is omitted, the backend synthesises one from `initial_state`. Setting both is allowed; explicit `bootstrap` wins.

### Fix — `create_voice_session_usecase.dart`

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
| User typed a few fields manually, then hit "Voice" | `mode: 'returning_same_page'`, `current_page_values: <typed values>`, `readonly_paths: <fields user shouldn't change>` |
| User finished page 1, navigated to page 2 | `mode: 'page_handoff'`, `prior_pages: { step_1: <values> }`, `participant_display_name: <name from page 1>` |

### Verify
- `new_user`: agent greets generically, asks for name first.
- `returning_same_page` with name+phone+email pre-filled, email readonly: agent says "I see your name is X and phone is Y — confirm?" and treats email as read-only.
- `page_handoff` with prior data: agent says "Hi Jane, welcome to the next step."

---

## Issue #8 — Send `field_errors` with `field_status` (HIGH — NEW THIS SESSION)

### Why
When Flutter rejects a value (regex fail, network error), the agent today just sees `field_status: invalid` and re-asks generically. Adding `field_errors` lets it say "looks like that wasn't a valid phone — make sure it's 10 digits with no spaces".

### Wire contract — `screen_state_v2` payload (additive — old payloads still valid)

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

Extend `_currentFieldStatus()` (Issue #6) to also return `Map<String, String> fieldErrors`. Pass both to `sendScreenState`.

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

## Issue #9 — Subscribe to `row_added` event (HIGH — NEW THIS SESSION)

### Why
When the user says "I'd like to add another emergency contact", the backend calls `add_repeatable_row` and emits a `row_added` WS event. Flutter must listen and render an empty card for the new index.

### Wire contract

```json
{
  "type": "row_added",
  "section_id": "emergency_contacts",
  "new_index": 1
}
```

### Fix — `voice_event.dart` (sealed class)

Add a new variant:

```dart
sealed class VoiceEvent {}
// ... existing variants ...
class VoiceRowAdded extends VoiceEvent {
  final String sectionId;
  final int newIndex;
  VoiceRowAdded({required this.sectionId, required this.newIndex});
}
```

### Fix — `voice_event_model.dart` (parser)

```dart
case 'row_added':
  return VoiceRowAdded(
    sectionId: json['section_id'] as String,
    newIndex: json['new_index'] as int,
  );
```

### Fix — `voice_session_controller.dart`

```dart
case VoiceRowAdded(:final sectionId, :final newIndex):
  _sink.addRepeatableRow(sectionId, newIndex);
  break;
```

### Fix — `client_step1_voice_sink.dart`

```dart
void addRepeatableRow(String sectionId, int newIndex) {
  if (sectionId == 'emergency_contacts') {
    _step1Ctrl.addEmptyEmergencyContact();
    // Optional: auto-scroll to the new card so the user sees it.
    _step1Ctrl.scrollToEmergencyContactRow(newIndex);
  }
}
```

`addEmptyEmergencyContact()` should call the same controller method the "Add another" button uses.

### Verify
Say "Add another emergency contact". An empty card appears. Voice-fill it.

---

## Issue #10 — Handle array values in `field_updated` (CRITICAL — NEW THIS SESSION)

### Why
The backend `update_field` tool now accepts `values: array<string>` for multi-value fields. Gemini will use it for fields like `preferred_languages`. The resulting `field_updated` event will have `value` as a list, not a string. Existing handlers that assume string crash with a type error.

### Wire contract — `field_updated` event (multi-value)

```json
{
  "type": "field_updated",
  "section": "basics",
  "field": "preferred_languages",
  "value": ["English", "Mandarin"],
  "repeatable_index": null,
  "confidence": 0.95,
  "turn_id": 4
}
```

For scalar fields, `value` is still a string:

```json
{
  "type": "field_updated",
  "section": "basics",
  "field": "full_name",
  "value": "Jane Smith",
  "repeatable_index": null,
  "confidence": 0.92,
  "turn_id": 1
}
```

### Fix — `voice_event_model.dart` (parser)

Change the `value` type from `String` to `dynamic` (or `Object`) so it accepts both shapes:

```dart
case 'field_updated':
  return VoiceFieldUpdated(
    section: json['section'] as String,
    field: json['field'] as String,
    value: json['value'],  // dynamic — can be String OR List<String>
    repeatableIndex: json['repeatable_index'] as int?,
    confidence: (json['confidence'] as num?)?.toDouble() ?? 1.0,
  );
```

### Fix — `client_step1_voice_sink.dart`

```dart
void onFieldUpdated(String section, String field, dynamic value, {int? repeatableIndex, double confidence = 1.0}) {
  // Coerce value into the shape the target controller expects.
  if (section == 'basics' && field == 'preferred_languages') {
    final list = value is List ? value.cast<String>() : <String>[value.toString()];
    _step1Ctrl.preferredLanguages.assignAll(list);  // RxList<String>
    return;
  }

  // Scalar paths
  final str = value is List ? (value as List).join(', ') : value.toString();
  // ... existing scalar routing logic
}
```

### Verify
Say "I prefer English and Mandarin". Confirm:
1. Backend log shows `multi_value applied field=basics.preferred_languages count=2`.
2. UI shows BOTH chips selected (not just one).
3. Only ONE `field_updated` event arrived (not two).

---

## Issue #11 — Connection lifecycle & resume flow (HIGH — NEW THIS SESSION)

### Why
Gemini Live sessions have a hard ceiling (~10 min connection lifetime). The backend now emits `go_away` when Gemini is about to drop, and `resumable` with a one-time handle when the WS closes for non-terminal reasons. Without handling these, the voice cuts off mid-flow with no recovery.

### Wire contract

```json
{ "type": "go_away", "time_left_ms": 8000 }
```

```json
{ "type": "resumable", "handle": "rh_abc123...", "ttl_sec": 600 }
```

To resume, reconnect the WS at `wss://<host>:8083/ws/onboarding/{session_id}?resume=rh_abc123...`. The handle is single-use (atomic GETDEL on the server) and TTL'd at 10 minutes.

### Fix — `voice_event.dart`

```dart
class VoiceGoAway extends VoiceEvent {
  final int timeLeftMs;
  VoiceGoAway(this.timeLeftMs);
}

class VoiceResumable extends VoiceEvent {
  final String handle;
  final int ttlSec;
  VoiceResumable({required this.handle, required this.ttlSec});
}
```

### Fix — `voice_session_controller.dart`

Track the latest resume handle and react to `go_away` by proactively reconnecting before the deadline:

```dart
String? _resumeHandle;
Timer? _goAwayTimer;

case VoiceGoAway(:final timeLeftMs):
  // Reconnect ~2 seconds before Gemini drops, using whatever resume handle
  // we last received. If we don't have one yet, we'll get it on the close.
  final reconnectIn = (timeLeftMs - 2000).clamp(0, timeLeftMs);
  _goAwayTimer?.cancel();
  _goAwayTimer = Timer(Duration(milliseconds: reconnectIn), () async {
    await _reconnectWithResume();
  });
  break;

case VoiceResumable(:final handle, :final ttlSec):
  _resumeHandle = handle;
  // Persist locally in case the app process gets killed before reconnect.
  _localStore.saveResumeHandle(handle, ttlSec);
  break;

Future<void> _reconnectWithResume() async {
  final handle = _resumeHandle;
  if (handle == null) return;
  await _stream.close();           // close current WS
  await _stream.openWithResume(    // open new one with ?resume=
    sessionId: _session!.sessionId,
    resumeHandle: handle,
  );
  _resumeHandle = null;            // single-use; backend already deleted it
}
```

### Datasource — `voice_session_datasource.dart`

```dart
Future<void> openWithResume({required String sessionId, required String resumeHandle}) async {
  final url = '${_wsBaseUrl}/ws/onboarding/$sessionId?resume=$resumeHandle';
  _channel = WebSocketChannel.connect(Uri.parse(url));
  // ... rest of WS setup, same as initial connect
}
```

### Verify
1. Run a session for 10+ minutes. Confirm reconnect happens silently when `go_away` arrives.
2. Confirm conversation continues without re-introducing the agent (the backend replays the last 4 turns).
3. Kill the app process during a session, restart within 10 min, resume — confirm it picks up.

---

## Issue #12 — Handle WS close codes (HIGH — NEW THIS SESSION)

### Why
The backend uses specific close codes for different failure modes. Without per-code handling, the user sees a generic "connection lost" for distinct problems that need distinct UX.

### Close-code table

| Code | Meaning | What Flutter shows |
|------|---------|--------------------|
| 1000 | Normal close | No message (expected exit) |
| 1011 | Internal error | "Something went wrong. Try again." + retry button |
| 4004 | `session_not_found` — session expired | "Your session expired. Start over." + back to step 0 |
| 4008 | `protocol_error` — first message wasn't `start` | Should never hit in production. Log + retry. |
| 4009 | `session_locked` — another voice session is already active | "Voice is in use on another device." + close modal |
| 4010 | `resume_invalid` — bad/expired/used handle | Drop the cached handle; offer "Continue without resume" |
| 4011 | `policy_block` — policy boundary hit | Show the policy message from the `error` event; close voice |

### Fix — `voice_session_controller.dart`

```dart
void _onWsClose(int code, String? reason) {
  switch (code) {
    case 1000:
      break;  // expected close
    case 4004:
      _showError('Your session expired. Please start over.');
      _navToStepStart();
    case 4009:
      _showError('Voice is already in use on another device.');
      _closeModal();
    case 4010:
      _localStore.clearResumeHandle();
      _showError('Could not resume — please try again from the start.');
    case 4011:
      // The 'error' event already carried the policy_block message;
      // surface it without duplicating.
      break;
    default:
      _showError('Connection lost. Tap to reconnect.');
      _showRetryButton();
  }
}
```

### Verify
- Trigger 4004 by deleting the session via REST then opening WS — confirm "session expired" copy.
- Trigger 4009 by opening two WS connections to the same session — second sees "in use on another device".
- Trigger 4010 by reusing a handle twice — second use shows "could not resume".

---

## Issue #13 — UX adjustments (HIGH)

These are visual/interaction details. The voice flow is functionally correct without them, but the user experience is confusing.

### A. Read-only fields visual state (Rule 3)

When `bootstrap.readonly_paths` includes a field, the corresponding text input should:
- Be `enabled: false` or have `readOnly: true`.
- Show a small lock icon trailing the input.
- Not respond to taps that would open the keyboard.

The user just heard "Your email is read-only" — the visual must match.

### B. Confidence colouring on field_updated

The `field_updated` event includes `confidence: 0.0–1.0`. Use it to colour-flag low-confidence captures so the user can verify them.

```dart
final color = switch (confidence) {
  >= 0.8 => AppColors.success,    // green dot
  >= 0.6 => AppColors.warning,    // amber
  _      => AppColors.error,      // red — definitely re-ask
};
```

### C. Optional fields stay visible during the proactive prompt (Rule 5)

The agent will now ask about every `required: false` field after required ones are filled. If your UI auto-collapses optional fields once the section has all required fields, the user has nowhere to look while the agent asks. Either:
- Keep optional fields in the same scroll position they were in, OR
- When the agent's transcript shows "Would you also like to add a [field]?", auto-scroll the form to that field.

### D. Auto-scroll on `row_added` (Issue #9 polish)

After adding a new emergency-contact card via voice, scroll the new card into view so the user sees what's about to be filled.

### E. Multi-value chips visible during multi_enum capture (Rule 4)

For `preferred_languages` (and any future multi_enum), the chip-multi-select must show ALL selected chips after one `field_updated` event. If your widget only highlights one chip at a time, swap it for a multi-select component.

### Verify
Run a full session. After every backend interaction, ask: "did the UI tell the user what just happened?" If the answer is no, that's a UX bug.

---

## Backend Wire Contracts (complete reference)

### Server → Client WS events

| Event | Payload | What you do |
|-------|---------|-------------|
| `ready` | `{state, prompt_version, coverage}` | Session live; start mic |
| Binary | raw PCM16 24kHz mono | Feed to audio player |
| `turn_start` | — | Set `_agentSpeaking = true` (Issue #1) |
| `turn_complete` | — | Set `_agentSpeaking = false` |
| `interrupted` | — | Set `_agentSpeaking = false`; `_player.flush()` (Issue #1b) |
| `user_said` | `{text}` | Append to transcript view |
| `agent_said` | `{text}` | Append to transcript view |
| `field_updated` | `{section, field, value, repeatable_index?, confidence, turn_id}` | Apply to UI controller — **value can be String OR List<String>** (Issue #10) |
| `state` | `{state: <full FormState>}` | Reconcile UI from full snapshot |
| `row_added` | `{section_id, new_index}` | Render empty card (Issue #9) |
| `step_completed` | — | Close voice modal, advance to next step |
| `escalated` | `{reason, transcript_excerpt}` | Show safety message; close voice |
| `go_away` | `{time_left_ms}` | Schedule resume reconnect (Issue #11) |
| `resumable` | `{handle, ttl_sec}` | Save handle for next reconnect (Issue #11) |
| `error` | `{code, message}` | Show message; pair with close code (Issue #12) |

### Client → Server WS messages

| Type | Payload | When |
|------|---------|------|
| `start` | `{type: "start"}` | First message after WS open. Required handshake. |
| Binary | raw PCM16 16kHz mono | Continuous mic stream while not muted (Issue #1) |
| `user_text` | `{text}` | Typed-input alternative |
| `audio_end` | — | End-of-utterance flush |
| `screen_state_v2` | full v2 payload (Issues #6, #8) | On focus change, debounced 200ms |
| `stop` | — | Graceful client close |

### REST endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/v1/onboarding/session` | Create session (sends schema + bootstrap inline). Returns `session_id`, `ws_url`, `expires_at`. |
| `GET` | `/v1/onboarding/session/{id}/state` | Read FormState |
| `PUT` | `/v1/onboarding/session/{id}/state` | Update FormState manually. **Returns 409 if WS is active** — close WS first. |
| `POST` | `/v1/onboarding/session/{id}/complete` | Finalise + fire webhook |

### WebSocket URL

```
wss://<host>:8083/ws/onboarding/{session_id}                     # fresh
wss://<host>:8083/ws/onboarding/{session_id}?resume=<handle>     # resume
```

---

## Audio Format Spec

| Direction | Encoding | Sample rate | Channels | Notes |
|-----------|----------|-------------|----------|-------|
| Mic → server | raw PCM16 little-endian | 16000 Hz | mono | MIME `audio/pcm;rate=16000` if you ever need it. Backend re-samples internally if your device produces a different rate, but native 16k is preferred. |
| Server → speaker | raw PCM16 little-endian | 24000 Hz | mono | Resample down to your device's native rate before playback if needed. Most modern Android/iOS support 24k natively. |

The voice is `Aoede` and the speech config language is `en-AU`.

---

## Final Checklist

- [ ] `flutter analyze` returns 0 warnings
- [ ] Echo loop fixed — Sena does not interrupt herself (Issue #1)
- [ ] Interruption cuts agent audio within 150 ms (Issue #1b)
- [ ] Schema declares all 16 personal-info fields in UI order (Issues #2, #3)
- [ ] Repeatable emergency contacts work — at least 1 required, agent offers "another?" (Issue #4)
- [ ] Multi-value answers ("English and Mandarin") populate ALL chips (Issue #10)
- [ ] Stop voice mid-step, restart — new session does NOT re-confirm prior voice values (Issue #5)
- [ ] `bootstrap` envelope sent on every session create with the right `mode` (Issue #7)
- [ ] Sessions longer than 10 minutes survive Gemini's automatic drop (Issue #11)
- [ ] Each WS close code shows distinct user-facing copy (Issue #12)
- [ ] Type an invalid phone, focus another field — agent re-asks with the validator message paraphrased (Issue #8)
- [ ] Say "add another emergency contact" — empty card appears, voice-fills it (Issue #9)
- [ ] Read-only fields visually disabled with lock icon when `bootstrap.readonly_paths` lists them (Issue #13)
- [ ] Low-confidence captures (`confidence < 0.6`) show a warning indicator (Issue #13)
- [ ] Tap a field mid-session — agent pivots to that field within ~1 sec (Issue #6)

---

## Where the backend lives

```
SENA_AI/sena-ai/services/onboarding/
├── src/onboarding/
│   ├── api/routes.py           # POST /v1/onboarding/session — accepts bootstrap
│   ├── api/ws_routes.py        # WSS /ws/onboarding/{session_id}?resume=
│   ├── models/
│   │   ├── schema_spec.py      # StepSchema, SectionSpec, FieldSpec, RepeatableConfig
│   │   ├── session_bootstrap.py  # SessionBootstrap (Issue #7)
│   │   └── form_state.py       # FormState
│   ├── services/
│   │   ├── tools.py            # update_field (now with `values` array), add_repeatable_row, advance_step
│   │   ├── screen_context.py   # ScreenStateV2 (with field_errors — Issues #6, #8)
│   │   ├── gemini_live.py      # Live API bridge — go_away, interrupt-recovery, silence watchdog
│   │   └── resumption.py       # issue_handle, redeem_handle (Issue #11)
│   └── prompts/onboarding_system.md  # Agent instructions — all 7 rules + voice protocols
└── test_harness.html           # In-browser smoke test — useful for verifying backend independently
```

Backend port: **8083**. Run with `uvicorn src.onboarding.main:create_app --factory --reload --port 8083`.

---

## Questions for backend team

If anything in this doc is unclear or you hit unexpected behaviour, drop a note with:
1. What you sent (paste the WS frame or the request body).
2. What you got back (paste the WS event or response JSON).
3. The session_id and approximate timestamp.

Backend logs four high-signal lines that confirm Flutter changes are landing:

| Log line | Confirms |
|----------|----------|
| `update_field REJECTED — field 'X' not in section 'Y'` | Schema is missing a field (Issue #3) |
| `update_field REJECTED readonly path=X` | Readonly enforcement worked (Issue #7) |
| `multi_value applied field=basics.preferred_languages count=2` | Array-value path worked (Issue #10) |
| `interrupt_intent preserved chars=N` | Interrupt-recovery is engaged (Issue #1b downstream) |

Tail those four during smoke testing and you'll see exactly what the backend received from Flutter.
