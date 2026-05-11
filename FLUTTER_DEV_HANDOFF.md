# Flutter Dev Handoff — SENA Voice Onboarding

**Audience:** Flutter developer integrating with the SENA voice onboarding backend.
**Updated:** 2026-05-07
**Backend status:** complete and tested. All remaining work is in `lib/`.

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
| `repeatable_section_entered` | `{section_id, row_index, intent}` | Scroll to section header, highlight row (Issue #14) |
| `repeatable_section_exited` | `{section_id}` | Collapse/finalise the active row card (Issue #14) |
| `field_skipped_warning` | `{missing_count, required_filled, required_total, missing_fields[]}` | Show inline "N fields still needed" notice; highlight fields in `missing_fields` (Issue #14) |
| `schema_drift_detected` | `{kind, attempted_section, attempted_field?, label?}` | Show "noted for team" inline notice (Issue #16) |
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
| `validation_failed` | `{section_id, field_id, repeatable_index?, reason_human, code?, attempted_value?}` | Immediately when frontend validator rejects a value (Issue #15) |
| `validation_cleared` | `{section_id, field_id, repeatable_index?}` | When a previously-failed field now passes validation (Issue #15) |
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

---

## Addendum (2026-05-06) — Cross-Screen Shared Context

**Status:** server-side complete and tested (89/89 unit tests pass). The Flutter app gets the friendlier-assistant behaviour automatically as long as **two existing fields** are sent correctly on every session create. Two additional changes harden security and unlock manual override.

### What this feature does (in plain language)

Today, when a participant moves from Screen 1 → Screen 2, the assistant has zero memory of Screen 1. It greets the participant cold every time. That's the bug.

After this change, when a participant finishes a step, the backend silently writes a structured summary of what they said into a per-`(tenant_id, participant_id)` Redis bucket. When the next step's voice session starts, the backend reads the bucket and injects the prior steps into the assistant's system prompt before the first word is spoken. The assistant on Step 3 will say things like "Hi Sarah — last time you mentioned wanting to keep gardening on weekends, does that come up here?" without you doing anything.

The bucket is keyed by the **participant being onboarded**, not by the operator. A support worker who takes over a participant's onboarding from a colleague will see the prior conversation. The bucket is tenant-prefixed; one tenant cannot read another tenant's bucket.

### What the Flutter app must do (HARD REQUIREMENTS)

For the feature to work at all, **both** of these fields must be sent on every `POST /v1/onboarding/session` body:

| Field | Type | Constraint | What happens if you skip it |
|---|---|---|---|
| `participant_id` | string | Same value across **all** steps for the same participant. Stable, durable, app-owned identifier (typically the participant's row UUID in your DB). | Bucket lookup is skipped — assistant starts cold every step. Feature appears broken. |
| `tenant_id` | string | Same value across all steps. Identifies the org/tenant the participant belongs to. | Bucket lookup is skipped — same broken-feature symptom. Tenant isolation also depends on this — do not make it up client-side. |

**The most common bug is generating a new `participant_id` per voice session.** Don't. The participant_id is the participant. Sessions are ephemeral; participants are not.

If your app currently treats `tenant_id` as optional and only sends it sometimes, you must change that — every session create must carry both. Look at your `CreateVoiceSessionParams` and confirm `tenantId` and `participantId` are both required, not optional.

### What you get back, automatically

When you create a session for a participant who has prior steps in the bucket, the response's `bootstrap.prior_pages` field is **auto-populated by the server**. You do not have to track previous summaries client-side. The backend reads Redis and stuffs them into the bootstrap envelope before returning.

The shape of `bootstrap.prior_pages` will look like this:

```json
{
  "step:1": {
    "name": "Sarah Chen",
    "dob": "1990-04-12",
    "gender": "female",
    "goals": ["independence at home", "rejoin choir"],
    "hobbies": ["gardening", "chess"],
    "interests": ["audiobooks"],
    "_compressed": "{\"ec\":[{\"n\":\"Mum\",\"p\":\"+61...\"}],\"addr\":{...}}",
    "_step_label": "Personal Details"
  },
  "step:2": {
    "name": "Sarah Chen",
    "goals": [...],
    "_compressed": "{...}",
    "_step_label": "Lifestyle"
  }
}
```

Two zones:

- **Top-level keys** (`name`, `dob`, `gender`, `goals`, `hobbies`, `interests`) are preserved **verbatim** — full original values, untouched. These are the high-signal fields chosen by the product owner because they matter most for tone and conversational continuity.
- **`_compressed`** is a deterministic, **lossless** key-aliased JSON string of every other populated field on that prior step (e.g. emergency contacts, address, medical history). It's compact (~30–60% token saving) but no information is lost — it round-trips byte-equivalent under decompression. You can usually ignore this on the Flutter side; it's there for the assistant's prompt.
- **`_step_label`** is the human label of the step (e.g. "Personal Details").

`bootstrap.mode` will be set to `"page_handoff"` automatically when prior_pages are populated, even if the client sent `mode: "new_user"`. This is intentional — the agent reads `mode` to decide whether to greet generically or by name.

### When the server skips bucket lookup

The auto-populate only runs when **all** of these are true:

1. `SENA_AI_ONBOARDING_CROSS_SCREEN_CONTEXT_ENABLED=true` (default true; rollback flag).
2. `req.tenant_id` is non-empty.
3. The client did NOT supply `bootstrap.prior_pages` already (client-supplied wins).
4. The Redis bucket for `(tenant_id, participant_id)` has at least one prior step.

Any miss → empty `prior_pages` → Step 2 starts cold. Logging on the server will tell you which condition failed.

### Manual override path (rarely needed)

If you want to send your own `prior_pages` (e.g. during local testing, or because the app has fresher data than Redis), set `bootstrap.prior_pages` in your request body. The server-supplied bucket is **completely ignored** when the client supplies its own. There is no merge; client wins entirely. Use this only when you know what you're doing.

### Two recommended Flutter changes (security hardening — non-breaking)

These are not required for the feature to work, but you should land them in the same sprint because they close a latent isolation gap that has been there since v1.

#### Change 1 — Add ownership headers to state endpoints

On `GET /v1/onboarding/session/{id}/state` and `PUT .../state`, send these headers:

```http
GET /v1/onboarding/session/abc-123/state
X-Tenant-Id: <current tenant_id>
X-Participant-Id: <current participant_id>
```

When both headers are present, the server validates that the session at `{id}` belongs to that tenant + participant and returns **HTTP 403** with `{"detail": "session does not belong to this participant"}` on mismatch. When the headers are absent, the server falls back to today's behaviour (no check). You should send them — without them, a malicious client that guesses a session_id can read another tenant's transcript.

The same headers are not yet required on `POST /v1/onboarding/session` (the create call) because tenant + participant come from the body there. Don't add them on POST — they'd be ignored.

#### Change 2 — Treat 403 like 404 on state endpoints

When you GET or PUT state and receive 403, do not retry, do not show a generic error. Treat it the same way you treat 404 today: show "Your session expired. Please start over." and navigate the user back to the step entry. A 403 here means either the headers were stale (user logged in as someone else) or the session_id was wrong — neither is recoverable in-place.

```dart
if (response.statusCode == 403 || response.statusCode == 404) {
  _showError('Your session expired. Please start over.');
  _navToStepStart();
  return;
}
```

### Edge cases & operational notes

| Situation | Behaviour |
|---|---|
| First-ever step for a participant | Bucket is empty → `prior_pages: {}` → assistant greets generically per `mode: "new_user"`. Working as intended. |
| Participant restarts onboarding 8+ days after their last step | Bucket TTL is 7 days. Older buckets have expired. Behaves like a first-ever step. If you need longer-horizon memory, your app backend (DB of record) must re-seed `prior_pages` manually on the create call — feature does not block this. |
| Same participant on a different device / different staff user | Same bucket — operator identity does not affect the key. Context follows the participant. |
| Participant switches tenants (rare) | Different bucket — tenant_id is part of the key. Context does not follow across tenants. By design. |
| Backend is down / Redis is down | Session create still works. Bucket lookup fails open: `prior_pages: {}`. Assistant starts cold. No client-visible error. |
| `SENA_AI_ONBOARDING_CROSS_SCREEN_CONTEXT_ENABLED=false` | Feature disabled server-side. No reads, no writes. Equivalent to v1 behaviour. No client change needed to handle this. |
| The same step is "completed" twice (via `/complete` then a clean WS close, or vice-versa) | Idempotent on `(participant_id, step_number)`. The second write overwrites the first; no duplicate, no race. |

### Optional UX you could add (no backend dependency)

If you want to surface the cross-screen context visually in the Flutter UI (not required, but a clear win):

- **"Continuing your onboarding" banner.** When `bootstrap.prior_pages` is non-empty on session create, show a small banner above the voice modal: "Picking up from where you left off — Sena remembers your last step." Helps the user understand why the assistant references prior info.
- **Prior-step summary chip row.** Render `_step_label` from each entry in `prior_pages` as a chip ("✓ Personal Details", "✓ Lifestyle"). Pure UI candy; data is already in your hands.
- **No work needed on the audio path.** The assistant's first words on Step 2 will reference Step 1 automatically because the prompt was rendered with that context. You don't need to inject anything into the audio stream client-side.

Skip all of these and the feature still works invisibly — the assistant just sounds smarter.

### Verifying it works end-to-end

1. Run a full Step 1 voice session for participant `P1` under tenant `T1`. Complete it (`POST /complete`).
2. Open Step 2 for the **same** `P1` + `T1`. Inspect the `POST /v1/onboarding/session` response. `bootstrap.prior_pages` should contain `step:1` with the verbatim block populated.
3. Connect WS. Sena's first turn should reference the participant's name and at least one prior detail.
4. Backend smoke command (run in dev environment): `redis-cli HGETALL sena:onboarding:user_ctx:T1:P1` — should print one field `step:1` and a JSON value.

If step 2's `prior_pages` is empty:
- Verify `participant_id` is identical across both create calls (most common bug).
- Verify `tenant_id` is sent and identical.
- Verify the server flag is on (`SENA_AI_ONBOARDING_CROSS_SCREEN_CONTEXT_ENABLED`).

### Rollback knob

A single env flag `SENA_AI_ONBOARDING_CROSS_SCREEN_CONTEXT_ENABLED=false` disables the bucket (no reads, no writes, no prompt injection, no session-id index updates). No Flutter change is required to back out — when the flag flips off, `prior_pages` is always empty and the app behaves exactly as it did before this addendum landed.

### What you do NOT need to change

Just to be explicit — these things are unaffected by this feature:

- WS protocol — no new events, no changed payloads.
- Existing `bootstrap.mode` semantics for `new_user` and `returning_same_page` — still work the same way.
- `field_updated` / `row_added` / `field_errors` handling — unchanged.
- Echo gating, interrupt flush, audio format — unchanged.
- Session expiry, resume handles, `go_away` behaviour — unchanged.
- Schema declaration — unchanged.

If you are mid-way through Issues #1–#13 above, this addendum does not change any of those tasks. It runs alongside.

### Where to escalate

If `bootstrap.prior_pages` is empty when you expected it populated, capture and send to the backend team:

1. The exact `tenant_id` and `participant_id` values used on the **first** create call.
2. The exact `tenant_id` and `participant_id` values used on the **second** create call (verify byte-for-byte identical to #1).
3. The session_ids returned from both calls.
4. The approximate timestamps.

Backend will run `redis-cli HGETALL sena:onboarding:user_ctx:<tenant_id>:<participant_id>` against the dev Redis to confirm whether the bucket exists. If the bucket exists but `prior_pages` came back empty, that's a server bug and we'll fix it. If the bucket is missing, the Step 1 `/complete` call did not fire — check your client-side flow.

### Final checklist (cross-screen-context-specific)

- [ ] Every `POST /v1/onboarding/session` body sends both `participant_id` and `tenant_id`.
- [ ] `participant_id` is stable across steps for the same participant (not regenerated per session).
- [ ] `tenant_id` is stable across steps for the same participant.
- [ ] `bootstrap.prior_pages` is read from the response and **not** overwritten by the client (unless you have a deliberate manual-override case).
- [ ] `X-Tenant-Id` and `X-Participant-Id` headers added to GET / PUT state endpoints (recommended, not blocking).
- [ ] 403 from state endpoints handled the same way as 404 (recommended, not blocking).
- [ ] Smoke-tested two consecutive steps for the same participant — second step's response has populated `prior_pages`.

---

## Addendum (2026-05-07) — Issues observed during cross-screen testing

These are PRODUCTION-FEEDBACK issues. They were caught by manually running the
voice flow end-to-end after the cross-screen feature shipped. Each one breaks
participant trust in a different way; each has a wire contract the Flutter app
must implement to fix it. Source PRD: `.planning/PRD-validation-sequencing-discovery.md`.

---

## Issue #14 — Sequencing strictness (CRITICAL, NEW)

### Symptom observed

Voice run on personal_information step:
- Assistant skipped a `*`-required field (it was never asked, the step still advanced).
- Assistant treated `emergency_contacts[0].name` and `basics.full_name` as the same field — when the participant said their own name during emergency-contact intake, it wrote it to the participant profile.
- Order of asked fields did not match the schema declaration order.

### Why this happens

Without explicit per-section pinning, Gemini's natural conversational flow lets it move freely between sections. The system prompt's "ask in order" guidance was advisory, not enforced. Repeatable sections share field names (`name`, `phone`) with the parent profile, so when the assistant calls `update_field` mid-conversation it inferred the wrong section.

### Server-side fix (already in plan)

- New `next_required_field` server-side hint computed from schema + current FormState. Rendered into `[LIVE_STATE_JSON]` block of the system prompt and refreshed on every `screen_state_v2` event.
- Dispatcher rejects `update_field` calls whose `section_id` does not match the focused-section hint, unless the assistant passes `cross_section_intent: true` (declared intent).
- New tools `enter_repeatable_section(section_id, intent: "first" | "next")` and `exit_repeatable_section()` pin the focus to a specific row index; subsequent `update_field` calls inherit that index.

### Flutter-side requirements

1. **Send the `current_section_id` and `focused_field` accurately on every `screen_state_v2` event.** The server uses `current_section_id` as ground truth for the cross-section guard; if the field you sent doesn't match what the user is actually on, the server may reject valid updates. Already required by Issue #6 — strengthen the focused-field tracking to be precise.

2. **Listen for a new event:**
   ```json
   { "type": "repeatable_section_entered", "section_id": "emergency_contacts", "row_index": 0, "intent": "first" }
   ```
   Fired when the assistant calls `enter_repeatable_section`. Use it to scroll to the section header and visually highlight which row the assistant is filling. Without this the participant sees the assistant filling row 0 but the UI still shows row 0 collapsed; visual confusion.

   A paired `repeatable_section_exited` fires when the assistant finishes a row:
   ```json
   { "type": "repeatable_section_exited", "section_id": "emergency_contacts" }
   ```
   Use it to collapse/finalize the row card.

3. **Listen for a new event:**
   ```json
   {
     "type": "field_skipped_warning",
     "missing_count": 2,
     "required_filled": 5,
     "required_total": 7,
     "missing_fields": [
       { "section_id": "basics", "field_id": "phone" },
       { "section_id": "emergency_contacts", "field_id": "name", "repeatable_index": 0 }
     ]
   }
   ```
   Fired when the server blocks `advance_step` because required fields are still unfilled. Render a non-blocking inline warning ("N required fields are still needed"). Optional UX; backend blocks the advance regardless. The `missing_fields` array enumerates exactly which required fields are empty — use it to highlight the relevant form cards. `repeatable_index` is present only for fields inside repeatable sections.

### Verify

- Run a voice session that asks for emergency contacts. After "let's add your first emergency contact," confirm the UI scrolls to the emergency contacts section and row 0 is visually highlighted.
- Try to make the assistant skip a required field (say "skip the gender question"). Server rejects the advance; UI does not move on.
- Say your own name during emergency-contact intake. Confirm the value lands on `emergency_contacts[0].name`, not on `basics.full_name`.

---

## Issue #15 — Validation awareness (CRITICAL, NEW)

> **Update 2026-05-07:** the server is now the **authoritative** validator and mirrors every rule in `lib/core/utils/validators.dart` byte-equivalent. Frontend `validation_failed` events are still consumed (defense in depth) and are still recommended — they catch the rare case where the user types into the field while voice is also active. But the assistant no longer **depends** on those events to reject bad data; it will refuse to write `phone="12"` regardless of whether the Flutter validator gets there first. This is a **scope reduction** for the Flutter side: implement the events when convenient, not as a launch blocker.

### Symptom observed

Participant gives obviously invalid data ("phone number is twelve", "DOB is January thirty-second", "name is asdfasdf"). Assistant accepts each, calls `update_field`, moves on. Frontend's existing validators would have caught all three, but the assistant never sees them. Form ends up with junk values; participant either has to fix manually or downstream processing fails.

### Why this happens

Validation is currently a one-way frontend concern. There is no wire path that surfaces validation failures back to Gemini in real time. The server has no soft-validator either, so even values the frontend hasn't typed yet (mid-voice) reach `update_field` unfiltered.

### Server-side fix (already in plan)

- A new `pending_validation_errors` block in `[LIVE_STATE_JSON]` mirrors any unresolved validation failures so even cold-start prompts include them.
- A "soft validator" runs server-side against well-defined types (phone shape, date sanity, email format) before `update_field` writes. Catches the cases where the frontend hasn't yet emitted its own validation result.
- Validation rejection is fed into Gemini's input stream as a structured text injection: `[VALIDATION_FAILED] field=basics.phone reason="needs 10 digits with no spaces"`. The system prompt instructs the assistant to immediately re-prompt with the human reason verbatim and clear the field.

### Flutter-side requirements

1. **MUST emit a new WS event whenever a frontend validator fails.** Send AS SOON as the validator returns the failure, not on form submit:
   ```json
   {
     "type": "validation_failed",
     "section_id": "basics",
     "field_id": "phone",
     "attempted_value": "12",
     "reason_human": "Phone number needs to be 10 digits with no spaces.",
     "reason_code": "phone_too_short",
     "suggested_fix": "Try saying the full number including the area code."
   }
   ```
   - `reason_human`: the SAME text your form would have shown the user if they were typing. Will be paraphrased verbatim by the assistant.
   - `reason_code`: a stable identifier for analytics (e.g. `phone_too_short`, `dob_in_future`, `email_no_at`). Never exposed to the user.
   - `suggested_fix`: optional plain-language hint. The assistant will use it in the re-ask if present.
2. **MUST emit a paired success event when validation now passes** (after a corrected re-entry):
   ```json
   { "type": "validation_cleared", "section_id": "basics", "field_id": "phone" }
   ```
   Without this, the assistant's `pending_validation_errors` block will keep listing the field as broken even after correction.
3. **DO NOT** include the regex pattern, the validator function name, or any internal error code text in `reason_human`. The string is read verbatim to the user.
4. **Locale**: emit in the user's selected locale (the same string you would have shown in the form). Server does not translate.

### Verify

- Type a 3-digit number into the phone field while voice is active. Within 500ms, the assistant should re-prompt with "Phone number needs to be 10 digits..." (your exact reason_human text).
- Correct the phone. Within 500ms, assistant moves on.
- Server logs show `validation_failed_injected` and `validation_cleared` lines.

---

## Issue #16 — Schema-drift discovery (HIGH, NEW)

### Symptom observed

- Participant said "actually I have two emergency contacts" → assistant added one row but UI didn't render the second; second contact's data was silently lost.
- Participant said "I'd like to add my evening routine" → assistant said "noted" and moved on; the request never reached the dev team. No metric, no log, no ticket.

The mobile dev team has no signal telling them which fields/sections participants are trying to give the assistant that the schema can't accommodate.

### Why this happens

The current contract:
- `add_repeatable_row` exists, but only for sections already declared as repeatable.
- Sections not in the schema have no surface at all — the assistant just declines.
- Unknown field paths (e.g. `personal_information.basics.middle_name` when the schema only has `first_name` and `last_name`) get rejected silently with no telemetry.

### Server-side fix (already in plan)

- Two new structured logs at INFO level:
  - `unknown_field_attempt` — fires whenever `update_field` targets a `(section, field)` pair the schema doesn't declare.
  - `unknown_section_request` — fires when the participant asks for a section that doesn't exist (assistant calls a new `request_unknown_section` tool).
- Both feed a daily digest aggregating by attempted name. Out of scope for v1; v1 just emits the logs.
- A new `repeatable_section_entered` event fires the moment the assistant enters a repeatable section, even before any row materialises.

### Flutter-side requirements

1. **Listen for two new server→client events:**
   ```json
   { "type": "schema_drift_detected", "kind": "unknown_field",
     "attempted_section": "basics", "attempted_field": "middle_name" }
   ```
   ```json
   { "type": "schema_drift_detected", "kind": "unknown_section",
     "attempted_section": "evening_routine", "label": "Evening routine" }
   ```
   When you receive either, render a small inline notice: "We've noted this for the team." Optional UX, backend logs regardless.

2. **Listen for `repeatable_section_entered` (already covered in Issue #4 / #9) but extend handling:** ensure the section header scrolls into view BEFORE the first `row_added` arrives, not after. Current code waits for the row.

3. **Strengthen the existing `row_added` handler:** if the assistant has called `add_repeatable_row` more than once in a single turn, you may receive multiple `row_added` events in rapid succession. Current code may render only one. Confirm your handler is queue-safe (apply each event in order, don't debounce).

4. **NEW: send a daily-summary endpoint hit on app startup** (recommended, not blocking):
   ```
   GET /v1/onboarding/_diag/schema-drift?tenant_id=<id>&days=7
   ```
   Returns the aggregated unknown attempts for the last 7 days. Use this to drive an in-app "Schema requests" panel in the dev-only build. Not required for production.

### Verify

- Run a session, ask for "evening routine." Server log: `unknown_section_request requested_section_label="evening routine"`. Mobile renders inline notice.
- Run a session, ask the assistant to fill `basics.middle_name` (not in schema). Server log: `unknown_field_attempt attempted_section=basics attempted_field=middle_name`. Mobile renders inline notice.
- Run a session with two emergency contacts. Confirm BOTH rows render in the UI with the correct data.

---

## Issue #17 — Discovery telemetry contract documentation (REFERENCE, NEW)

A consolidated table of EVERY new wire event introduced by Issues #14 / #15 / #16 so you can grep this section once instead of hunting across three issues.

### Server → Client (events the Flutter app must HANDLE)

| Event | Payload | Source issue | When it fires |
|-------|---------|--------------|---------------|
| `repeatable_section_entered` | `{section_id, row_index, intent}` | #14, #16 | Assistant called `enter_repeatable_section` — scroll to section header, highlight row |
| `repeatable_section_exited` | `{section_id}` | #14 | Assistant called `exit_repeatable_section` — collapse/finalise the row card |
| `field_skipped_warning` | `{missing_count, required_filled, required_total, missing_fields[]}` | #14 | `advance_step` blocked because required fields are unfilled; `missing_fields` enumerates exactly which |
| `schema_drift_detected` | `{kind: "unknown_field"\|"unknown_section", attempted_section, attempted_field?, label?}` | #16 | Assistant tried to use a field/section not in the schema |

### Client → Server (events the Flutter app must EMIT)

| Event | Payload | Source issue | When to emit |
|-------|---------|--------------|--------------|
| `validation_failed` | `{section_id, field_id, attempted_value, reason_human, reason_code, suggested_fix?}` | #15 | The frontend's validator just rejected a value |
| `validation_cleared` | `{section_id, field_id}` | #15 | A previously-failed field now passes validation |

### Endpoints

| Method | Path | Purpose | Issue |
|--------|------|---------|-------|
| GET | `/v1/onboarding/_diag/bucket?tenant_id=&participant_id=` | Inspect cross-screen bucket (dev only) | (cross-screen addendum) |
| GET | `/v1/onboarding/_diag/schema-drift?tenant_id=&days=` | Aggregate unknown attempts (dev only) | #16 |

### Final checklist for Issues #14–#17

- [ ] `current_section_id` and `focused_field` on `screen_state_v2` are precise (not stale).
- [ ] Listening for `repeatable_section_entered` (`{section_id, row_index, intent}`); scrolling section into view + highlighting the active row.
- [ ] Listening for `repeatable_section_exited` (`{section_id}`); collapsing/finalising the row card.
- [ ] Listening for `field_skipped_warning` (`{missing_count, required_filled, required_total, missing_fields[]}`); showing inline "N fields still needed" notice and highlighting the fields listed in `missing_fields`.
- [ ] Emitting `validation_failed` with full payload on every validator failure.
- [ ] Emitting `validation_cleared` when a field corrects.
- [ ] `reason_human` strings are user-facing only — no regex / no error codes.
- [ ] Listening for `schema_drift_detected`; rendering "noted for team" inline notice.
- [ ] `row_added` handler is queue-safe (handles multiple events in one turn).
- [ ] (Optional) dev-build polls `_diag/schema-drift` for an in-app schema requests panel.

---

## Addendum (2026-05-07) — Forensic Audit: 5 Missing Event Handlers + Schema-Drift Refresh

> **Source:** Forensic audit identified that 5 of 7 reported user-visible bugs are **Flutter consumer gaps**, not backend defects. The backend already emits the right events; `voice_event_model.dart` has no `case` for them, and they fall through `default → return null` silently.
>
> **Anti-pattern:** *Missing Consumer Subscription* (AP-1). Every server event without an explicit Flutter case is a silent UX regression waiting to happen.
>
> **Goal of this addendum:** wire 5 typed events end-to-end (entity → model parser → controller reaction → UI) so that every documented server emission has a visible UI consequence.

### Bugs this addendum fixes

| User-visible bug | Server event already emitted | Flutter gap |
|---|---|---|
| Email validation appears to do nothing | `validation_rejection` | No case in `VoiceEventModel.parse` switch |
| Vague "add more info" — user has no idea what's left | `field_skipped_warning` (with `missing_fields[]`) | No case |
| Agent uses field names not in the form, no UI signal | `schema_drift_detected` | No case |
| Repeatable rows feel chaotic — UI doesn't track agent focus | `repeatable_section_entered` / `repeatable_section_exited` | No case |
| Personalisation drops on new screens | `bootstrap.participant_display_name` (server-side) | Flutter doesn't read it for UI personalisation |

### Issue #18 — Wire `validation_rejection` event (CRITICAL, NEW)

**Symptom:** server-side validators (e.g. email regex, NDIS number, plan-date ordering) fire correctly; the model receives the rejection and re-asks. The user sees red on no field — no inline error string, no audible cue from the UI.

**Source of truth:** `services/tools.py::_update_field` returns `{"ok": false, "rejection": {code, reason_human, suggested_fix?}}` AND `_emit({"type": "validation_rejection", "section_id", "field_id", "rejection": {...}})` for non-cross-section rejections.

**Implementation steps (sequential):**

1. **Domain entity** — `lib/features/voice_onboarding/domain/entities/voice_event.dart`:
   ```dart
   class VoiceValidationRejection extends VoiceEvent {
     final String sectionId;
     final String fieldId;
     final int? repeatableIndex;
     final String code;          // e.g. "email_invalid"
     final String reasonHuman;   // server-authored, display VERBATIM
     const VoiceValidationRejection({
       required this.sectionId,
       required this.fieldId,
       required this.code,
       required this.reasonHuman,
       this.repeatableIndex,
     });
   }
   ```

2. **Parser case** — `lib/features/voice_onboarding/data/models/voice_event_model.dart`, in the switch:
   ```dart
   case 'validation_rejection':
     final r = (json['rejection'] as Map?)?.cast<String, dynamic>() ?? const {};
     return VoiceValidationRejection(
       sectionId: (json['section_id'] as String?) ?? '',
       fieldId: (json['field_id'] as String?) ?? '',
       repeatableIndex: json['repeatable_index'] as int?,
       code: (r['code'] as String?) ?? 'unknown',
       reasonHuman: (r['reason_human'] as String?) ?? '',
     );
   ```

3. **Controller reaction** — in `voice_session_controller.dart` event-handling switch:
   ```dart
   if (e is VoiceValidationRejection) {
     final key = _fieldKey(e.sectionId, e.fieldId, e.repeatableIndex);
     validationErrors[key] = e.reasonHuman;        // RxMap<String,String>
     AppSnackbar.error(message: e.reasonHuman);    // server copy, no rephrase
   }
   ```

4. **UI binding** — wherever the field's error helper is rendered (e.g. `AppTextField.errorText:`), read from `validationErrors[key]`. Clear the entry when the field re-submits successfully (drive on next `field_updated` for the same key).

5. **Verify** — voice-test an email like "not-an-email"; expect inline red copy with the server's `reason_human` string verbatim.

**Anti-recurrence rule:** copy is server-authored. Do NOT translate, paraphrase, or substitute UI strings.

---

### Issue #19 — Wire `field_skipped_warning` event (CRITICAL, NEW)

**Note:** Issue #14 above already documents the event payload. This issue is the *implementation contract* — what the controller and UI must do with it.

**Symptom:** assistant says "we still need a few things" but user has no visible indicator of what.

**Source of truth:** `services/tools.py::_advance_step` emits `{type, missing_count, required_filled, required_total, missing_fields:[{section_id, field_id, repeatable_index?}]}` whenever the model calls `advance_step` while required fields are still empty.

**Implementation steps:**

1. **Domain entity:**
   ```dart
   class VoiceFieldSkippedWarning extends VoiceEvent {
     final int missingCount;
     final int requiredFilled;
     final int requiredTotal;
     final List<Map<String, dynamic>> missingFields;
     const VoiceFieldSkippedWarning({
       required this.missingCount,
       required this.requiredFilled,
       required this.requiredTotal,
       required this.missingFields,
     });
   }
   ```

2. **Parser case:**
   ```dart
   case 'field_skipped_warning':
     final mfRaw = json['missing_fields'];
     final mf = (mfRaw is List)
         ? mfRaw.whereType<Map>().map((e) => e.cast<String, dynamic>()).toList(growable: false)
         : const <Map<String, dynamic>>[];
     return VoiceFieldSkippedWarning(
       missingCount: (json['missing_count'] as int?) ?? 0,
       requiredFilled: (json['required_filled'] as int?) ?? 0,
       requiredTotal: (json['required_total'] as int?) ?? 0,
       missingFields: mf,
     );
   ```

3. **Controller reaction:**
   ```dart
   if (e is VoiceFieldSkippedWarning) {
     remainingRequired.value = e.missingCount;
     requiredProgress.value = (e.requiredTotal == 0)
         ? 0.0 : e.requiredFilled / e.requiredTotal;
     pendingMissingFields.assignAll(e.missingFields);
     // Highlight the cards listed in missing_fields
     for (final mf in e.missingFields) {
       final key = _fieldKey(mf['section_id'], mf['field_id'], mf['repeatable_index']);
       missingHighlights.add(key);
     }
   }
   ```

4. **UI binding:**
   - Top-of-form banner: `"$missingCount fields still needed — $requiredFilled of $requiredTotal complete"`
   - Pulsing/highlighted border on each `missingHighlights` field card
   - Banner clears on next `field_updated` that fills one of the missing items (or on next `state` event when `required_filled` advances)

5. **Verify** — voice-test by saying "I'm done" before filling all required fields; expect banner + pulsing field highlights.

---

### Issue #20 — Wire `schema_drift_detected` event (HIGH, NEW)

**Symptom:** the agent receives a tool call for a field/section that does not exist in the schema (Gemini hallucinated, or the Flutter schema is genuinely out of date). Server logs the drift; UI is blind.

**Source of truth:** `services/tools.py` emits `{type, kind: "unknown_field"|"unknown_section", attempted_section, attempted_field?, label?}` from three sites: `_update_field` unknown-section branch, `_update_field` unknown-field branch, and `_request_unknown_section` handler.

**Implementation steps:**

1. **Domain entity:**
   ```dart
   class VoiceSchemaDriftDetected extends VoiceEvent {
     final String kind;             // "unknown_field" | "unknown_section"
     final String attemptedSection;
     final String? attemptedField;
     final String? label;
     const VoiceSchemaDriftDetected({
       required this.kind,
       required this.attemptedSection,
       this.attemptedField,
       this.label,
     });
   }
   ```

2. **Parser case:**
   ```dart
   case 'schema_drift_detected':
     return VoiceSchemaDriftDetected(
       kind: (json['kind'] as String?) ?? 'unknown',
       attemptedSection: (json['attempted_section'] as String?) ?? '',
       attemptedField: json['attempted_field'] as String?,
       label: json['label'] as String?,
     );
   ```

3. **Controller reaction (architectural choice — pick A unless during dictation):**

   **A. Auto-refetch schema (recommended for non-active state):**
   ```dart
   if (e is VoiceSchemaDriftDetected) {
     AppLogger.warn('VoiceCtrl', 'schema_drift kind=${e.kind} sec=${e.attemptedSection}');
     if (turnInProgress.value) {
       // Defer until turn_complete — never refresh mid-utterance
       _pendingSchemaRefresh = true;
     } else {
       await _refreshSchemaFromBackend();
     }
   }
   ```

   **B. Banner during active turn:**
   ```dart
   schemaDriftNotice.value = e.kind == 'unknown_section'
       ? "Noted — '${e.label ?? e.attemptedSection}' isn't part of this form. We've passed it on."
       : "Noted that field for the dev team.";
   ```

4. **UI binding:** show `schemaDriftNotice` as a dismissible inline notice (NOT snackbar — non-blocking). Auto-clear on next user turn.

5. **Verify** — voice-test "can you also note down my pet's name?" — expect inline notice with copy from §A above.

---

### Issue #21 — Wire `repeatable_section_entered` / `repeatable_section_exited` events (HIGH, NEW)

**Symptom:** when the agent collects emergency contacts, NDIS goals, or any repeatable section, multiple row cards appear but the user has no visual signal of which row the agent is currently filling. Compounds bug #19 because the user can't track progress per-row.

**Source of truth:**
- `tools.py::_enter_repeatable_section` emits `{type, section_id, row_index, intent}`
- `tools.py::_exit_repeatable_section` emits `{type, section_id}`

**Implementation steps:**

1. **Domain entities:**
   ```dart
   class VoiceRepeatableSectionEntered extends VoiceEvent {
     final String sectionId;
     final int rowIndex;
     final String intent;  // "first" | "next"
     const VoiceRepeatableSectionEntered({
       required this.sectionId,
       required this.rowIndex,
       required this.intent,
     });
   }

   class VoiceRepeatableSectionExited extends VoiceEvent {
     final String sectionId;
     const VoiceRepeatableSectionExited(this.sectionId);
   }
   ```

2. **Parser cases:**
   ```dart
   case 'repeatable_section_entered':
     return VoiceRepeatableSectionEntered(
       sectionId: (json['section_id'] as String?) ?? '',
       rowIndex: (json['row_index'] as int?) ?? 0,
       intent: (json['intent'] as String?) ?? 'first',
     );
   case 'repeatable_section_exited':
     return VoiceRepeatableSectionExited(
       (json['section_id'] as String?) ?? '',
     );
   ```

3. **Controller reaction:**
   ```dart
   if (e is VoiceRepeatableSectionEntered) {
     focusedSection.value = e.sectionId;
     focusedRowIndex.value = e.rowIndex;
     // Scroll the section header into view
     await _scrollSectionIntoView(e.sectionId);
   } else if (e is VoiceRepeatableSectionExited) {
     if (focusedSection.value == e.sectionId) {
       focusedSection.value = null;
       focusedRowIndex.value = null;
     }
   }
   ```

4. **UI binding:**
   - Section header gets a subtle "active" state (filled accent border) when `focusedSection.value == section.id`
   - Row card at `focusedRowIndex.value` gets a stronger highlight ("collecting now" pulse)
   - Card collapses to a finalised state when its row exits focus

5. **Verify** — voice-test adding two NDIS goals; expect first goal card to highlight while the agent collects, then collapse, then second card highlights.

---

### Issue #22 — Use `bootstrap.participant_display_name` for UI personalisation (LOW, NEW)

**Symptom:** the agent says "Hi Jane" via TTS, but the voice-session sheet header reads a generic "Voice Onboarding" title. UI doesn't pull from the bootstrap envelope the app itself sent in `POST /v1/onboarding/session`.

**Source of truth:** `bootstrap.participant_display_name` was sent by the Flutter app when creating the session. It's mirrored back in the `ready` event's `state` block — the app already has it locally and it's also visible in the FormState model.

**Implementation steps:**

1. **Controller exposes:** add `participantDisplayName.value = ...` populated when the bootstrap is constructed (or read from the local user profile cache that drove the bootstrap).

2. **UI binding:** in the voice-session sheet header, render:
   ```dart
   Text(
     ctrl.participantDisplayName.value.isNotEmpty
         ? AppStrings.voiceSheetGreeting(ctrl.participantDisplayName.value)
         : AppStrings.voiceSheetGreetingGeneric,
     style: AppText.h3,
   )
   ```

3. **AppStrings additions** (single source of truth — no inline text):
   ```dart
   static String voiceSheetGreeting(String name) => "Welcome back, $name";
   static const voiceSheetGreetingGeneric = "Welcome back";
   ```

4. **Verify** — open voice sheet on a returning-user step; expect "Welcome back, Jane" in header.

---

### Sequenced Implementation Plan (for Sonnet — follow in order)

| Step | Issue | Files | Verifier |
|------|-------|-------|----------|
| 1 | #18 `validation_rejection` | entity + parser + controller | manual: voice-test invalid email |
| 2 | #19 `field_skipped_warning` | entity + parser + controller + banner UI | manual: say "done" before filling required fields |
| 3 | #20 `schema_drift_detected` | entity + parser + controller + inline notice | manual: ask for an off-schema field |
| 4 | #21 `repeatable_section_entered/exited` | 2 entities + 2 parser cases + controller + section/row UI states | manual: add 2 NDIS goals back-to-back |
| 5 | #22 `participantDisplayName` UI | controller getter + sheet header + AppStrings | manual: visual check on returning-user step |

**After each step:**
- `flutter analyze` → 0 warnings
- Manual voice-test the verifier above before moving to the next step
- Commit atomically with conventional message: `feat(voice): wire <event> end-to-end`

**Anti-recurrence test (run after step 5):**
- Send `{"type": "an_event_that_does_not_exist"}` from a backend test stub
- Confirm: `VoiceEventModel.parse` returns `null` and a `WARN` log line is emitted (not silent)
- This guards AP-5 (Producer-Without-Schema-Contract) — future server events will surface as warnings until Flutter wires them.

### Final Audit Checklist (5 issues)

- [ ] Issue #18 — `validation_rejection` parsed → controller writes to `validationErrors[key]` → field shows server `reason_human` verbatim.
- [ ] Issue #19 — `field_skipped_warning` parsed → banner shows `N of M complete` + missing-field highlights drawn from `missing_fields[]`.
- [ ] Issue #20 — `schema_drift_detected` parsed → inline notice rendered (non-blocking); auto-refresh queued if turn in progress.
- [ ] Issue #21 — `repeatable_section_entered/exited` parsed → focused section + row visually distinguishable; scroll-into-view triggers on enter.
- [ ] Issue #22 — Voice-sheet header reads `participantDisplayName`; falls back to generic greeting when empty.
- [ ] Anti-recurrence — `default` arm of `VoiceEventModel.parse` logs a `WARN` instead of silent `null`.
- [ ] All `reason_human` and notice strings are server-authored — no Flutter-side rephrasing.

---

## Addendum (2026-05-08) — Bidirectional Sync Gaps: Manual UI Edits, Screen Boundaries, Cross-Screen Context

> **Source:** User-reported gaps after the 2026-05-07 forensic remediation shipped. Three new categories of bug, all symptoms of the same root cause: **the WS protocol is one-directional in practice.** Server emits typed events to client; client only sends raw audio + screen-state pings. So when the user does anything *with their hands* (taps "Add", types into a field, navigates Next), the assistant is blind to it.
>
> **Anti-pattern:** *Producer-Without-Consumer* (AP-1, server side) — but inverted. Now Flutter is the producer-without-consumer-on-the-server. The assistant has no schema-typed channel to react to user-driven UI changes.
>
> **Scope of this addendum:** five new issues (#23–#27). Add a typed **client → server** event channel, formalise step-boundary signalling, and verify cross-screen context actually loads when the user moves between steps mid-session.

### Bugs this addendum fixes

| User-visible bug | Root cause | Fix issue |
|---|---|---|
| User adds an emergency contact via the "+" UI button. Agent has no idea — keeps asking about the previous contact | No client→server "user added row" event | #23 |
| User types a value into a field manually. Agent re-asks for the same field on next turn | No client→server "user filled field" event | #24 |
| User taps Next / Back on the step header. Agent keeps asking step-1 questions on step 2 | Step boundary not signalled to backend | #25 |
| Returning user starts step 3 — assistant says "Hi, what's your name?" as if it never met them | Cross-screen context bucket either not written on step-1 completion or not read on step-3 session create | #26 |
| User adds a min-zero repeatable section row (Morning Routine) by hand. Agent says "you don't have a morning routine yet" | Same as #23 — no signal | #27 |

---

### Issue #23 — Wire `user_action` channel: client → server typed events (CRITICAL, NEW)

**Symptom.** The Flutter app supports manual UI edits in parallel with voice. Today, those manual actions are invisible to the agent — Gemini has no idea the user just added a contact, deleted a row, or finalised a section.

**Why this is a Flutter-side fix (and a tiny backend addition).** The backend currently has no inbound message type for "user did X with their finger". We need to add one, but the contract — what events to send and when — is owned by Flutter because Flutter is the only place that knows when the user touches the UI.

**Source of truth (backend addition).** `api/ws_routes.py` and `services/gemini_live.py` will accept a new client→server JSON frame type:
```json
{ "type": "user_action", "action": "<action_name>", "payload": { ... } }
```
Backend treats this exactly like a tool call from the model — it mutates `FormState`, fires the same `field_updated` / `row_added` / `repeatable_section_entered` events back to the client (so the agent's view and the UI stay aligned), and injects a one-line `[USER ACTION]` text turn into Gemini so the agent acknowledges it on the next turn.

**Action types Flutter must emit (v1):**

| `action` | When to emit | `payload` |
|---|---|---|
| `manual_field_set` | User typed into a field and the field blurred / form value committed | `{section_id, field_id, repeatable_index?, value}` |
| `manual_field_cleared` | User explicitly cleared a previously-filled field | `{section_id, field_id, repeatable_index?}` |
| `manual_row_added` | User tapped the "+" / "Add another contact" button in a repeatable section | `{section_id}` (server returns the new index in the echoed `row_added` event) |
| `manual_row_removed` | User tapped delete on a row card | `{section_id, repeatable_index}` |
| `manual_section_skipped` | User tapped "Skip" on a min-zero repeatable section | `{section_id}` |

**Implementation steps:**

1. **Outbound model** — `lib/features/voice_onboarding/data/models/user_action_model.dart` (new):
   ```dart
   class UserActionModel {
     final String action;             // 'manual_field_set' | 'manual_row_added' | ...
     final Map<String, dynamic> payload;
     const UserActionModel({required this.action, required this.payload});
     Map<String, dynamic> toJson() => {
       'type': 'user_action',
       'action': action,
       'payload': payload,
     };
   }
   ```

2. **Datasource send method** — `voice_session_datasource.dart`:
   ```dart
   Future<void> sendUserAction(UserActionModel action) async {
     final ws = _ws;
     if (ws == null) return;
     ws.add(jsonEncode(action.toJson()));
   }
   ```

3. **Controller convenience methods** — `voice_session_controller.dart`:
   ```dart
   Future<void> notifyManualFieldSet({
     required String section,
     required String field,
     int? row,
     required Object value,
   }) =>
       _ds.sendUserAction(UserActionModel(
         action: 'manual_field_set',
         payload: {
           'section_id': section,
           'field_id': field,
           if (row != null) 'repeatable_index': row,
           'value': value,
         },
       ));

   Future<void> notifyManualRowAdded(String sectionId) =>
       _ds.sendUserAction(UserActionModel(
         action: 'manual_row_added',
         payload: {'section_id': sectionId},
       ));
   // ... mirror for cleared / removed / skipped
   ```

4. **Wire into existing form widgets** — every form widget already has an onChanged or controller; on commit, call the matching `notifyManual*` method **only when** `voiceCtrl.isConnected.value == true`. (No-op when voice sheet is closed.) Examples:
   - `personal_details_step_content.dart` — text field commits → `notifyManualFieldSet`
   - Emergency-contact "+" button — `notifyManualRowAdded('emergency_contacts')`
   - Min-zero "Skip" button (Morning Routine) — `notifyManualSectionSkipped('morning_routine')`

5. **Echo handling.** The server will fire back the same `field_updated` / `row_added` / `repeatable_section_entered` events Flutter already handles. Do NOT separately update local state from the user_action — wait for the echo, so voice and manual paths converge through one consistent state-update pipeline. (Prevents double-write races.)

6. **Verify** — open the voice sheet, manually type into the email field. Within ~1s the agent should say something like "Got the email, thanks — phone next?" — proving the agent saw the user's typed input.

**Anti-recurrence:** every form widget that mutates `FormState` MUST emit a `user_action` when the voice session is connected. Add a Dart lint or PR-checklist item: "If you add a new field/section to a step, add a corresponding `notifyManual*` call."

---

### Issue #24 — `manual_field_set` debounce + value-equality guard (HIGH, NEW)

**Symptom (after #23 lands).** Without care, Flutter spams `manual_field_set` on every keystroke, flooding Gemini with "user typed J… Ja… Jan… Jane" and burning input tokens.

**Fix.** Debounce per-field with a 600ms trailing edge AND only emit when the value actually differs from the last emitted value for that key.

```dart
final _lastEmittedValue = <String, Object>{};   // key = "section.field[.row]"
final _debouncers = <String, Timer>{};

void scheduleManualFieldSet({
  required String section,
  required String field,
  int? row,
  required Object value,
}) {
  final key = '$section.$field${row != null ? '.$row' : ''}';
  _debouncers[key]?.cancel();
  _debouncers[key] = Timer(const Duration(milliseconds: 600), () {
    if (_lastEmittedValue[key] == value) return;     // unchanged — skip
    _lastEmittedValue[key] = value;
    notifyManualFieldSet(section: section, field: field, row: row, value: value);
  });
}
```

Use `scheduleManualFieldSet` from text-field `onChanged`; use the immediate `notifyManualFieldSet` from blur / form-submit events.

**Verify** — type a 12-character name slowly; expect exactly 1 `user_action` frame on the wire (use the WS inspector or backend log).

---

### Issue #25 — Step boundary: emit `step_changed` when the user navigates (CRITICAL, NEW)

**Symptom.** User completes step 1 in voice → taps Next → arrives on step 2's screen. Voice sheet stays open. Agent keeps asking "What's your full name?" because the agent's `[LIVE_STATE_JSON]` still says it's collecting `personal_information`.

**Why.** The server's WS session is bound 1:1 to a single step (by design — clean resumption semantics). When the user navigates between steps in the UI, the *correct* behaviour is to close the current voice WS and open a new one for the new step. Today, Flutter doesn't do that — it leaves the WS open and the agent drifts.

**Two contracts to implement (Flutter side):**

#### 25a. On step navigation while voice is connected — close + reopen

```dart
// In step navigation handler (Next / Back / direct step jump):
if (voiceCtrl.isConnected.value) {
  await voiceCtrl.disconnect(reason: 'step_changed');   // closes WS gracefully (code 4001)
  // ... allow the new step screen to mount and bootstrap
  await voiceCtrl.connect(stepId: newStepId, schema: newStepSchema);
}
```

Backend close code `4001` ("step_change") is reserved — server will skip the auto-resumption handle on this code (next session is intentionally fresh, not a resume).

#### 25b. Bootstrap envelope on the NEW session must include prior-step data

The new session's `POST /v1/onboarding/session` body must set `bootstrap.mode = "page_handoff"` and include `prior_pages` mapping each completed step's `step_id` to its key fields. Server then injects them into the new step's `[LIVE_STATE_JSON].prior_pages`.

```dart
final priorPages = <String, Map<String, dynamic>>{};
for (final completedStep in onboardingCtrl.completedSteps) {
  priorPages[completedStep.id] = completedStep.publicValuesForVoiceContext();
  // publicValuesForVoiceContext returns a flat map: {'full_name': 'Jane', 'phone': '+61...'}
}

final body = CreateVoiceSessionRequest(
  stepId: newStepId,
  schema: newStepSchema,
  bootstrap: BootstrapEnvelope(
    mode: priorPages.isEmpty ? 'new_user' : 'page_handoff',
    participantDisplayName: profile.displayName,
    priorPages: priorPages,
    // current_page_values: any pre-fills the user already saved on this step (often {})
    currentPageValues: stepCtrl.currentValues,
    readonlyPaths: stepCtrl.readonlyPaths,
  ),
);
```

This is what makes the agent say "Hi Jane, welcome to the next step — I've got your contact details from earlier." (Rule 2 in the system prompt.)

**Verify**:
1. Complete step 1 by voice, tap Next.
2. Tap the voice button on step 2.
3. First utterance MUST say "Hi {name}" + reference at least one value from step 1 (e.g. "your phone we have on file").
4. Agent must NOT re-ask any field that's in `prior_pages`.

---

### Issue #26 — Cross-screen context bucket: verify it actually loads (CRITICAL, NEW)

**Symptom.** Even after #25 lands, the user reports that the agent on a later step has no memory of earlier steps when they take a break and return the next day.

**Why this is separate from #25.** `bootstrap.prior_pages` covers the in-app, same-session handoff — Flutter has the data locally and ships it on session create. The cross-screen context bucket is for the cross-day case: data persists in Redis under `sena:onboarding:user_ctx:{tenant_id}:{participant_id}` for 7 days, refreshed on every write. The server reads it on `POST /v1/onboarding/session` AFTER applying `bootstrap.prior_pages`, so it can fill the gaps when Flutter doesn't have local data (e.g. the user uninstalled and reinstalled).

**Flutter contract (no new code, but verify):**

1. **`tenant_id` and `participant_id` MUST be set on every `CreateVoiceSessionRequest`.** Without them the server silently skips the bucket lookup. Confirm both fields are non-empty in the wire body for every session create. (See `api/routes.py` `_resolve_bootstrap_with_user_ctx` — it short-circuits when either is empty.)

2. **`mode` selection rule:**
   - Set `mode: "page_handoff"` when `priorPages` is non-empty OR when the local profile has any onboarding step marked as previously-completed-by-this-participant.
   - Set `mode: "new_user"` ONLY when the participant truly has zero history.
   - When in doubt, send `page_handoff` — the server's bucket lookup is harmless and additive.

3. **Diagnostic (dev builds only).** Hit `GET /v1/onboarding/_diag/bucket?tenant_id=...&participant_id=...` before opening the voice sheet — confirm `bucket_empty` reflects reality.

**Verify (cross-day scenario):**
1. Complete steps 1–2, fully close the app.
2. Wait 5 minutes (proves it's not session-cache).
3. Reopen, navigate to step 3, open voice sheet.
4. Agent's first utterance must reference at least one fact from step 1 OR 2 (name, NDIS goal, support frequency, anything).
5. If it doesn't, capture the server log line `session_create_resolved_bootstrap` — `prior_pages_keys` will tell you whether the bucket loaded; if not, `tenant_id` / `participant_id` mismatch is the most likely cause.

---

### Issue #27 — Min-zero repeatable: "Skip" button must emit `manual_section_skipped` (HIGH, NEW)

**Symptom.** Morning Routine, Evening Routine, Medical History etc. are repeatable sections with `min: 0`. The voice agent (post-Rule-9 fix) surfaces them and offers to skip. If the user taps the on-screen "Skip" button instead of saying "skip", the agent has no idea — keeps asking.

**Fix (Flutter):** the section's "Skip" button calls `notifyManualSectionSkipped(sectionId)` from #23. Server marks the section as user-declined in `state.declined_sections` (new field — backend addition required) and the agent stops surfacing it.

**Server-side addition (informational — not Flutter scope, but cite for clarity):**
- `FormState.declined_sections: list[str]` (default `[]`)
- `prompt_builder.py` excludes any section in `declined_sections` from `next_optional_field` enumeration
- `tools.py` accepts a new `manual_section_skipped` user_action handler

**Verify** — on the requirements step, tap "Skip" on Morning Routine. Within one turn the agent should NOT mention morning routine. If it does, capture the server log — `declined_sections` should contain `morning_routine`.

---

### Wire-Level Contract Summary (additions from this addendum)

#### Client → Server (NEW direction)

| Frame | Payload | Purpose |
|---|---|---|
| `{type: "user_action", action: "manual_field_set", payload: {section_id, field_id, repeatable_index?, value}}` | typed | User typed/picked a value with their finger |
| `{type: "user_action", action: "manual_field_cleared", payload: {section_id, field_id, repeatable_index?}}` | typed | User explicitly cleared a field |
| `{type: "user_action", action: "manual_row_added", payload: {section_id}}` | typed | User tapped "+" |
| `{type: "user_action", action: "manual_row_removed", payload: {section_id, repeatable_index}}` | typed | User tapped delete on a row |
| `{type: "user_action", action: "manual_section_skipped", payload: {section_id}}` | typed | User tapped "Skip" on a min-zero repeatable |

#### Server → Client (echo behaviour — existing events, new triggers)

| Echo event | Triggered by | Notes |
|---|---|---|
| `field_updated` | every successful `manual_field_set` | identical shape to voice-driven update |
| `state` | every `user_action` that mutates state | full snapshot |
| `row_added` | `manual_row_added` | `{section_id, new_index}` |
| `repeatable_section_entered` | `manual_row_added` (auto-pin focus) | `{section_id, intent: "next", row_index}` |
| `validation_rejection` | `manual_field_set` whose value fails server validators | identical handling to Issue #18 |

#### WS close codes (additions)

| Code | Meaning | Flutter response |
|---|---|---|
| `4001` | step_change (intentional) | Do NOT show error; expected during step navigation. Skip resume handle. |

---

### Sequenced Implementation Plan (Issues #23–#27)

| Step | Issue | Files | Verifier |
|------|-------|-------|----------|
| 1 | #23 `user_action` channel scaffold | `user_action_model.dart`, datasource send method, controller `notifyManual*` methods | unit: model `toJson` round-trips |
| 2 | #23 wire form widgets | each step's step_content widget | manual: type into a field, see `field_updated` echo within 1s |
| 3 | #24 debounce + dedup | controller `scheduleManualFieldSet` | manual: type 12-char string, observe exactly 1 frame |
| 4 | #25a step-change disconnect/reconnect | step navigation handler | manual: complete step 1 by voice, tap Next, voice sheet on step 2 references prior data |
| 5 | #25b `prior_pages` in bootstrap | `create_voice_session_usecase.dart` + `BootstrapEnvelope` model | manual: agent acknowledges name from step 1 on step 2 |
| 6 | #26 verify cross-screen bucket | NO Flutter code change — verify `tenant_id`/`participant_id` always set + diag endpoint check | cross-day scenario above |
| 7 | #27 min-zero Skip button | requirements step UI | manual: tap Skip on Morning Routine, agent stops asking |

**After each step:**
- `flutter analyze` → 0 warnings
- Manual voice-test the verifier above before moving on
- Conventional commit: `feat(voice): wire <action> client→server`

**Anti-recurrence test (run after step 7):**
- Open voice on step 2 with a populated step-1 history. Agent's first utterance MUST contain at least one value from step 1.
- Open voice on step 3 next day (force-quit + reopen). Agent's first utterance MUST contain at least one value from step 1 or 2.
- Tap "Skip" on Morning Routine — agent must not bring it up again that session.
- These three checks together prove that bidirectional sync (#23), step boundaries (#25), and cross-screen context (#26) are all functioning.

### Final Audit Checklist (Issues #23–#27)

- [ ] Issue #23 — `UserActionModel` + datasource send method + 5 `notifyManual*` controller methods exist; every form-widget mutation calls the matching method when `voiceCtrl.isConnected`.
- [ ] Issue #23 — Echo events (`field_updated`, `row_added`, `repeatable_section_entered`) handled identically whether triggered by voice or by `user_action`.
- [ ] Issue #24 — Per-key debounce (600ms) + value-equality guard implemented; manually typing a long string produces exactly one frame.
- [ ] Issue #25a — Step navigation while voice is connected closes WS with code 4001 and reopens with the new step's schema.
- [ ] Issue #25b — `BootstrapEnvelope.priorPages` populated from completed steps' `publicValuesForVoiceContext()`; `mode = "page_handoff"` when non-empty.
- [ ] Issue #26 — Every `CreateVoiceSessionRequest` includes non-empty `tenant_id` and `participant_id`; `mode` defaults to `page_handoff` whenever the participant has any prior step history.
- [ ] Issue #27 — Min-zero repeatable "Skip" buttons emit `manual_section_skipped`; server's `declined_sections` honoured.
- [ ] WS close code `4001` does NOT surface an error toast — silent expected-state handling.
- [ ] No Flutter-side rephrasing of server-authored strings.
- [ ] Anti-recurrence tests above all pass.

---

## Addendum 2026-05-08 — Issue #28: Section-copy auto-fill contract

### Symptom that prompted this fix

User filled `home_address` by voice on the personal-information step. The schema declares `service_same_as_home: true` by default. The four `service_address` fields stayed empty on the Flutter UI. Voice agent moved on. User saw a half-empty form.

### Backend behaviour (now live)

The schema's `copy_from_if_flagged` declaration is now load-bearing. When a section declares:

```json
{
  "id": "service_address",
  "copy_from_if_flagged": "home_address",
  "flag_field": {
    "id": "service_same_as_home",
    "type": "boolean",
    "default": true
  }
}
```

…the server mirrors every matching field id from the source section into the target section after every successful `update_field` call, IF the flag is `true` (or unset and `default: true`). The mirror is idempotent — it only writes when the source value differs from the current target value.

### New WS event payload field

Each auto-mirrored field is surfaced as an additional `field_updated` event with two extra keys the Flutter client must accept:

```jsonc
{
  "type": "field_updated",
  "section": "service_address",
  "field": "address",
  "value": "1 Example St",
  "repeatable_index": null,
  "confidence": 1.0,
  "turn_id": 7,
  "source": "app",                  // NEW: distinguish from voice captures
  "auto_copied_from": "home_address" // NEW: where the value came from
}
```

The base `field_updated` event for the user's voice-driven home_address write fires unchanged. The mirrored events fire AFTER it, before the trailing `state` snapshot.

### Flutter checklist

- [ ] `FieldUpdatedModel` parser accepts (and ignores if not interested) the new `source` and `auto_copied_from` keys without crashing.
- [ ] When `auto_copied_from` is non-null, the UI MAY show a subtle "auto-filled from <label>" hint next to the field — but the field MUST be populated either way.
- [ ] Toggling the `service_same_as_home` checkbox in the UI must emit the same `update_field` payload the voice path uses (`section: "service_address"`, `field: "service_same_as_home"`, `value: <bool>`, `cross_section_intent: true`). The server will fan out the four mirrored field events automatically.
- [ ] When user explicitly sets the flag to `false` mid-session, do NOT clear the previously-mirrored values — the schema's `visible_if: { service_same_as_home: false }` already hides the wrapped fields. Server keeps the values for round-trip safety.

### Cross-screen context flag note

`SENA_AI_ONBOARDING_CROSS_SCREEN_CONTEXT_ENABLED` now defaults to `true`. The bucket key is `sena:onboarding:user_ctx:{tenant_id}:{participant_id}` so cross-tenant isolation is structural — there is no flag-flip required to be safe. If the agent re-asks for the participant's name on a new screen, the cause is the client failing to send `tenant_id` + `participant_id` on `POST /v1/onboarding/session` (Issue #26), NOT the flag. Verify the request body before assuming a backend regression.
