# SENA Voice Onboarding — Flutter Integration Fixes

This is the single, consolidated punch list of every Flutter-side change
required to make voice onboarding work end-to-end. Each issue lists the
symptom, the root cause, a backend reference (so you can verify the server
already does its half), and the exact code change.

**The backend code is correct as of this writing.** All remaining bugs are
in `lib/`. Apply the fixes in the order shown.

---

## TL;DR — proven root cause from `output.txt` transcript

**Symptom (user-reported):** "AI is being blocked from taking input. It says
'I can't record gender by voice', 'I can't record address by voice', then
ends the session after collecting only 5 fields. We never configured
anything to block fields."

**Diagnosis (from the actual transcript):**

The backend has zero filters. The schema sent FROM Flutter is what tells
Gemini which fields exist. `lib/core/voice_schemas/step1_personal_info_schema.dart`
declares exactly 5 fields in 1 section:

```
sections: [{ id: 'basics', fields: [full_name, date_of_birth, phone, email, about_me] }]
```

The file's own header says: *"Track-A scope: scalar text/date fields only.
Address, emergency contacts, and profile picture are intentionally omitted."*

When the user said `"my gender is male"`, Gemini called
`update_field(section='basics', field='gender', value='male')`. The backend
tool dispatcher (`tools.py::_update_field`) validates against the schema:
`section.all_fields()` does not contain `gender` → returns
`{"ok": false, "error": "field 'gender' not in section 'basics'"}`. Gemini
relays that to the user as "I can't record gender by voice."

Same for `preferred_language`, `interpreter_required`, `home_address.*`,
`service_address.*`, `emergency_contacts.*` — none declared in the schema,
all rejected.

**Why the user thought the AI was being blocked:** the schema's *omissions*
are the configuration. There is no deny-list — the schema's `fields[]` IS
the allow-list. Anything not declared is implicitly excluded.

**Server-side diagnostic added this round:** `tools.py::_update_field` now
logs a warning when a field is rejected, including the section's declared
fields. Look for `update_field REJECTED — field 'X' not in section 'Y'` in
the onboarding service stdout. This makes the rejection visible in future
debugging.

**Single fix:** apply Issue 3 (replace `Step1PersonalInfoSchema.schema`
with the 16-field version) + Issue 4 (extend `StepSchema` for repeatables)
below. Once the schema declares every field your UI shows, Gemini can fill
every field your UI shows. Until then, this is not fixable on the backend
because the backend never knew those fields existed.

**Verified clean on the backend:**
- `voice_coverage` cleared in `fixtures/schema_*.json` (was the previous
  whitelist that limited Gemini)
- `voice_coverage` not even sent in Flutter's wire format
  (`step_schema_model.dart::toWire()` doesn't emit the key)
- `prompt_builder._voice_coverage_section()` only emits the restriction
  block when the list is non-empty (it's empty)
- VAD: `END_SENSITIVITY_LOW` + `silence_duration_ms=1000` (patient)
- Echo flush hack `audio_stream_end=True` on `turn_start` removed (was
  corrupting Gemini's VAD state machine)
- Transcript no longer re-injected on plain WS reconnects (was making
  fresh sessions inherit prior conversation context)
- System prompt strict rule: agent NEVER mentions "the screen" without
  a `[SCREEN]` block

---

## Issue Index

| # | Issue | Severity | Effort |
|---|---|---|---|
| 1 | Echo loop — agent hears its own playback | CRITICAL | 5 min |
| 1b | Stale audio plays after `interrupted` — feels like agent ignores user | CRITICAL | 15 min |
| 2 | Schema field order doesn't match UI form order | CRITICAL | 5 min |
| 3 | Schema missing 10+ fields (gender, address, emergency contacts…) | CRITICAL | 30 min |
| 4 | `StepSchema` entity has no `repeatable` support | CRITICAL | 20 min |
| 5 | New session re-loads previously voice-captured values | HIGH | 5 min |
| 6 | No live screen-state sync — schema is static | RECOMMENDED | 1 h |

---

## Files you'll edit

```
lib/features/voice_onboarding/presentation/controllers/voice_session_controller.dart
lib/features/voice_onboarding/domain/entities/step_schema.dart
lib/features/voice_onboarding/data/models/step_schema_model.dart
lib/core/voice_schemas/step1_personal_info_schema.dart
lib/features/voice_onboarding/presentation/widgets/client_step1_voice_sink.dart
lib/features/client/presentation/dashboard/home/client_onboarding/steps/step_content/personal_details_step_content.dart
```

---

## Issue 1 — Echo loop (CRITICAL)

### Symptom
Sena speaks → phone speaker plays back → mic picks it up → server transcribes
the agent's own speech as `USER_SAID` → Gemini "hears itself" and either
interrupts or responds to itself in a loop.

### Root cause
Hardware AEC (`echoCancel: true` already set in `RecordConfig`) only works
with fixed-latency playback. Server PCM streams over WebSocket have
unpredictable buffering, so AEC loses its reference and lets echo through.

### Backend reference
Server-side mitigation is **impossible** — mic audio originates on the
phone. The previous attempted fix (`audio_stream_end=True` on `turn_start`
in `gemini_live.py`) misused the Gemini API and corrupted VAD. That hack
has been **removed** from `gemini_live.py`. The fix MUST be in Flutter.

The server emits these WS events for the client to gate against:
- `{"type":"turn_start"}` — agent began speaking
- `{"type":"turn_complete"}` — agent finished speaking
- `{"type":"interrupted"}` — agent was interrupted

These already arrive in `VoiceSessionController._handleEvent()`.

### Fix — `voice_session_controller.dart`

**Step 1.** Add an `_agentSpeaking` flag near the other `_micSub` declaration
(around line 87):

```dart
// True while Gemini is speaking — mic chunks are suppressed to prevent the
// assistant's own playback audio from looping back as user input.
bool _agentSpeaking = false;
```

**Step 2.** Replace the no-op turn handlers in `_handleEvent` (around line 288):

```dart
// BEFORE
case VoiceTurnStart():
case VoiceTurnComplete():
case VoiceInterrupted():
  // No-op for Track A.
  break;

// AFTER
case VoiceTurnStart():
  _agentSpeaking = true;
  break;
case VoiceTurnComplete():
case VoiceInterrupted():
  _agentSpeaking = false;
  break;
```

**Step 3.** Gate mic chunks in `_startMic` (around line 325):

```dart
// BEFORE
_micSub = stream.listen(
  (chunk) => _sendAudio(chunk),
  onError: (Object e) =>
      AppLogger.error('VoiceCtrl', 'mic stream error: $e'),
);

// AFTER
_micSub = stream.listen(
  (chunk) {
    if (!_agentSpeaking) _sendAudio(chunk);
  },
  onError: (Object e) =>
      AppLogger.error('VoiceCtrl', 'mic stream error: $e'),
);
```

### Why this is safe (won't break VAD)
The banned server-side `_agent_speaking` gate fails because Gemini sends
turn N+1 audio *before* `turn_complete` of turn N arrives at the server,
keeping the gate closed when the user tries to speak. The Flutter gate
has no such race: `turn_start`/`turn_complete` are received on the client
in strict order. The server keeps forwarding audio unconditionally; it
just receives zero chunks during playback, which VAD treats as normal
silence.

### Test
1. Start session, let Sena greet. Sena should NOT interrupt itself.
2. After `turn_complete`, speak. Sena should respond to you, not itself.
3. Interrupt Sena mid-sentence. Confirm mic resumes after interruption.
4. Long session (>5 turns). Mic still works.

---

## Issue 1b — Stale audio plays after interruption (CRITICAL)

### Symptom
User starts speaking → Gemini detects activity → Gemini cancels generation
and sends `interrupted` to client. But the user keeps hearing the agent
speak for another 1-3 seconds because audio chunks scheduled in the
playback queue keep playing. Feels like "interruption doesn't work — the
agent just keeps talking over me."

### Root cause
The audio player schedules each PCM chunk at a future time so playback is
gap-free. Once a chunk is scheduled, it WILL play unless explicitly stopped.
On `interrupted`, the client must cancel every queued chunk immediately.

This is a per-Gemini-Live-spec requirement (per official docs):
> "Flush Audio Buffers: The server sends a server_content message with
> "interrupted": true when an interruption occurs. Clear the local playback
> audio buffer immediately to prevent the user from hearing the model's
> 'stale' audio."

### Backend reference
Server already handles this correctly:
- `gemini_live.py` — `if sc.interrupted:` branch sends
  `{"type":"interrupted"}` to client
- New diagnostic log: `interrupted turn=N chunks_before=M session=...`
  appears in server stdout when Gemini self-interrupts

The client's responsibility is to clear playback the moment it sees that
event.

### Fix — `voice_audio_player.dart` (or wherever PCM playback happens)

The exact API depends on which audio package is used. The pattern:

1. Track every active audio source (chunk player, buffer source, etc).
2. Add a public `Future<void> flush()` method that:
   - Stops every active source
   - Clears the internal queue
   - Resets the playback head to "now"
3. Wire `flush()` to `VoiceInterrupted` in `VoiceSessionController._handleEvent`.

Example pattern — adapt to your audio backend (`flutter_pcm_player`,
`audioplayers`, raw `audio_session`, etc):

```dart
class VoiceAudioPlayer {
  final List<_PendingChunk> _queue = [];
  AudioSource? _activeSource;

  Future<void> feed(Uint8List pcm) async {
    final chunk = _PendingChunk(pcm);
    _queue.add(chunk);
    _drainQueue(); // schedule playback
  }

  /// Cancel every queued chunk and stop the active source.
  /// Called on `VoiceInterrupted` so the user doesn't hear stale agent audio.
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
case VoiceTurnStart():
  _agentSpeaking = true;
  break;
case VoiceTurnComplete():
  _agentSpeaking = false;
  break;
case VoiceInterrupted():
  _agentSpeaking = false;
  await _player.flush();   // ← NEW — cancel stale playback
  break;
```

### Test
1. Start session, let Sena begin a long sentence ("I'm here to help you...").
2. Speak over Sena while she's talking ("Stop, wait!").
3. Sena's audio should cut within ~150 ms — not finish her sentence.
4. Server log should show `interrupted turn=N chunks_before=M`.

---

## Issue 2 — Schema order out of sync with UI

### Symptom
Voice agent asks `name → date_of_birth` but the UI form shows
`name → email → phone → date_of_birth`. Gemini follows the schema; the
schema is wrong.

### Root cause
`Step1PersonalInfoSchema.schema` and `personal_details_step_content.dart`
are two hand-maintained views of the same form. They've drifted apart.

### Backend reference
There is **no implicit reorder layer**. The server passes `schema.sections`
verbatim to Gemini (`prompt_builder.py` → `__SCHEMA_JSON__` placeholder).
The system prompt in `onboarding_system.md` says:

> "You MUST go through EVERY field in the SCHEMA, in section order then
> field order."

So whatever order Flutter sends, Gemini follows. The UI form is the truth;
the schema must mirror it.

### Fix — covered together with Issue 3 below.

---

## Issue 3 — Schema missing 10+ fields

### Symptom
Gemini collects ~5 fields and calls `advance_step` because the schema's
required count is satisfied. The remaining 10+ visible fields (gender,
languages, interpreter, address, emergency contacts) are never collected
by voice — the participant has to type them manually.

### Root cause
`Step1PersonalInfoSchema` was scoped as "Track-A MVP — scalar text/date
fields only" per the comment at the top. Track A is over.

### Fix — `step1_personal_info_schema.dart` (full replacement)

Replace the entire `Step1PersonalInfoSchema` class with this. The order is
the **exact** UI order from `personal_details_step_content.dart`.

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
          // emergency_contacts goes here — see Issue 4 (repeatable support)
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

  static const Map<String, ({String section, String field})> _senaToVoice = {
    'personalDetails.fullName':             (section: 'basics',          field: 'full_name'),
    'personalDetails.email':                (section: 'basics',          field: 'email'),
    'personalDetails.phone':                (section: 'basics',          field: 'phone'),
    'personalDetails.dateOfBirth':          (section: 'basics',          field: 'date_of_birth'),
    'personalDetails.gender':               (section: 'basics',          field: 'gender'),
    'personalDetails.aboutMe':              (section: 'basics',          field: 'about_me'),
    'personalDetails.preferredLanguages':   (section: 'basics',          field: 'preferred_languages'),
    'personalDetails.interpreterRequired':  (section: 'basics',          field: 'interpreter_required'),
    'personalDetails.address':              (section: 'home_address',    field: 'address'),
    'personalDetails.state':                (section: 'home_address',    field: 'state'),
    'personalDetails.city':                 (section: 'home_address',    field: 'city'),
    'personalDetails.zipCode':              (section: 'home_address',    field: 'zip_code'),
    'personalDetails.serviceAddress':       (section: 'service_address', field: 'address'),
    'personalDetails.serviceState':         (section: 'service_address', field: 'state'),
    'personalDetails.serviceCity':          (section: 'service_address', field: 'city'),
    'personalDetails.serviceZipCode':       (section: 'service_address', field: 'zip_code'),
  };

  static const Map<String, String> _labels = {
    'basics.full_name':             'Full Name',
    'basics.email':                 'Email Address',
    'basics.phone':                 'Phone Number',
    'basics.date_of_birth':         'Date of Birth',
    'basics.gender':                'Gender',
    'basics.about_me':              'About Me',
    'basics.preferred_languages':   'Preferred Language',
    'basics.interpreter_required':  'Interpreter Required',
    'home_address.address':         'Street Address',
    'home_address.state':           'State',
    'home_address.city':            'City',
    'home_address.zip_code':        'Postcode',
    'service_address.address':      'Service Street Address',
    'service_address.state':        'Service State',
    'service_address.city':         'Service City',
    'service_address.zip_code':     'Service Postcode',
  };

  @override
  String? toSenaPath(String section, String field) =>
      _voiceToSena['$section.$field'];

  @override
  ({String section, String field})? toVoicePath(String senaPath) =>
      _senaToVoice[senaPath];

  @override
  String labelFor(String section, String field) =>
      _labels['$section.$field'] ?? field;
}
```

### Update `ClientStep1VoiceSink`
The sink needs to route every new sena path to the right controller field on
`ClientStep1Controller`. Add cases for `gender`, `preferredLanguages`,
`interpreterRequired`, `address`, `state`, `city`, `zipCode`,
`serviceAddress`, `serviceState`, `serviceCity`, `serviceZipCode`.

For enums (gender, languages), apply the value as the option's value
string. Booleans (`interpreterRequired`) should accept "Yes"/"No" or
true/false from voice.

---

## Issue 4 — Add repeatable section support

### Symptom
Emergency contacts (and any future repeatable section) cannot be added by
voice because the Flutter `StepSchema` entity has no `repeatable` field.

### Backend reference
The server's `models/schema_spec.py` defines `RepeatableConfig` and a
`item_fields` list. Tools include `add_repeatable_row` (see `tools.py`)
which Gemini calls to extend the row count.

### Fix — `step_schema.dart`

Add `RepeatableConfig` and update `SectionSpec`:

```dart
class RepeatableConfig {
  final int min;
  final int max;
  const RepeatableConfig({this.min = 0, this.max = 10});
}

class SectionSpec {
  final String id;
  final String title;
  final List<FieldSpec> fields;          // for non-repeatable
  final List<FieldSpec>? itemFields;     // for repeatable
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

Update `SectionSpecModel.toJson()` to emit:

```json
{
  "id": "emergency_contacts",
  "label": "Emergency Contacts",
  "repeatable": { "min": 1, "max": 5 },
  "item_fields": [ /* ... */ ]
}
```

Also add `voice_repeatable_sections: ["emergency_contacts"]` to the
`StepSchemaModel.toJson()` output. The backend uses this list to gate
the `add_repeatable_row` tool.

### Fix — add the section to `Step1PersonalInfoSchema`

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

The voice→sena mapping for repeatables uses indexed paths, e.g.
`personalDetails.emergencyContacts[0].name`. Wire that into the sink so
each indexed update lands on the right `ClientOnboardingEmergencyContactRow`.

---

## Issue 5 — New session re-loads previously voice-captured values

### Symptom
User completes a voice session, voice values get applied to the form, user
restarts voice. The new session sees those values as `initial_state` and
"confirms" them, instead of starting fresh.

### Root cause
`VoiceSessionController._buildInitialState()` reads everything from
`_sink.readMappableValues()`, including values that came from the previous
voice session.

### Backend reference
The server applies `initial_state` to FormState as `source: app` (see
`routes.py` `_build_initial_values()`) and the system prompt instructs
Gemini to "briefly confirm pre-filled values" — fine for genuine
manually-typed pre-fill, wrong for stale voice data.

### Fix — option A (simplest)

For brand new sessions (not resumes), pass `initialState: null` so Gemini
collects from scratch:

```dart
// In voice_session_controller.dart, inside start():
final result = await _create(CreateVoiceSessionParams(
  participantId: _participantId,
  tenantId: _tenantId,
  locale: _locale,
  schema: _stepConfig.schema,
  initialState: null,  // was: initial — let Gemini collect everything fresh
));
```

### Fix — option B (preserves manual entries)

Track which controller fields were manually typed vs voice-captured. Only
include manually-typed fields in `_buildInitialState()`. Requires adding a
`Set<String> _manuallyEnteredPaths` to the controller and updating it on
every keyboard `onChanged` event. More work, but lets users mix typing and
voice in one onboarding session.

Recommendation: ship Option A for now, plan Option B later.

---

## Issue 6 — RECOMMENDED: Live screen-state sync

### Why
After Issues 2-4, the schema is correct AND complete. But it's still sent
**once** at session start. If the user scrolls or taps a field mid-session,
Gemini doesn't know — it'll keep working through schema order regardless.

### Backend reference
The server already handles `screen_state_v2` end-to-end:
- `ws_routes.py` accepts `{"type":"screen_state_v2","data":{...}}`
- `screen_context.py` validates and renders the payload as a `[SCREEN]` block
- `gemini_live.py` injects the block as a Gemini text turn
- `onboarding_system.md` instructs Gemini:
  > "When you receive a [SCREEN] block, ... Prioritise Empty and Invalid
  > fields in the current Focus section first, then loop back to confirm
  > any Filled ones."

So once Flutter starts emitting these messages, real-time follow-the-cursor
works automatically.

### Fix — `voice_session_controller.dart`

Add a method to send screen state:

```dart
/// Forwards the current UI focus + field status to Gemini so it follows
/// the user's gaze in real time.
Future<void> sendScreenState({
  required String focusedSection,
  required String focusedField,
  required Map<String, String> fieldStatus, // 'filled' | 'empty' | 'invalid'
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
      'repeatable_rows': repeatableRows ?? {},
      'ui_flags': {},
    },
  );
}
```

### Exact JSON wire format (what gets sent over the WebSocket)

The WS frame is a **text** frame (not binary). The backend validates against
`ScreenStateV2Message` in `screen_context.py`.

```json
{
  "type": "screen_state_v2",
  "data": {
    "step_id": "personal_information",
    "focused_section": "basics",
    "focused_field": "full_name",
    "field_status": {
      "basics.full_name":            "filled",
      "basics.email":                "empty",
      "basics.phone":                "empty",
      "basics.date_of_birth":        "empty",
      "basics.gender":               "empty",
      "basics.about_me":             "empty",
      "basics.preferred_languages":  "empty",
      "basics.interpreter_required": "empty",
      "home_address.address":        "empty",
      "home_address.state":          "empty",
      "home_address.city":           "empty",
      "home_address.zip_code":       "empty",
      "service_address.address":     "empty",
      "service_address.state":       "empty",
      "service_address.city":        "empty",
      "service_address.zip_code":    "empty"
    },
    "repeatable_rows": {
      "emergency_contacts": 0
    },
    "ui_flags": {}
  }
}
```

**Key rules for `field_status`:**
- Keys use dotted path `section_id.field_id` — exactly as declared in the schema
- Values are exactly one of: `"filled"` | `"empty"` | `"invalid"`
- A field is `"filled"` if it has a non-empty, non-null value that passes validation
- A field is `"invalid"` if it has a value but fails validation (wrong format, etc.)
- Always send ALL fields — not just the focused one. Backend renders the full picture to Gemini.
- `repeatable_rows` maps section id → current row count (0 if none added yet)

### Datasource implementation

Add `sendScreenStateV2` to your voice WS datasource:

```dart
/// Sends a screen_state_v2 JSON text frame on the active WebSocket.
Future<void> sendScreenStateV2(Map<String, dynamic> payload) async {
  final frame = jsonEncode({
    'type': 'screen_state_v2',
    'data': payload,
  });
  _channel.sink.add(frame); // same sink used for audio_end, stop, etc.
}
```

Wire it up through the usecase to the controller's `sendScreenState` method.

### Fix — wire `FocusNode`s in the form

In `personal_details_step_content.dart`, attach a `FocusNode` to each input,
and on `addListener` fire:

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

`_currentFieldStatus()` returns a map of every voice-mapped path to one of
`filled` / `empty` / `invalid` based on controller text + validator result.

Debounce 200ms to avoid flooding the WS when a user tabs through fields
rapidly.

### Test
1. Start voice. Without speaking, tap the `Email` field on the form.
2. Within ~1 second Gemini should pivot: "I see you're on the email field —
   what's your email address?" instead of asking for `full_name` first.
3. Tap a Filled field. Gemini should confirm its value: "I see your name
   is John — is that correct?"

---

## Validation Checklist (run before declaring done)

- [ ] `flutter analyze` returns 0 warnings
- [ ] Voice session starts, no echo loop. Sena does not interrupt itself.
- [ ] Sena asks fields in the **exact** order: `full_name → email → phone →
      date_of_birth → gender → about_me → preferred_languages →
      interpreter_required → home_address.* → service_address.* →
      emergency_contacts (repeatable)`
- [ ] Every field captured by voice updates the matching UI input.
- [ ] At least 1 emergency contact required; agent offers "another?" before
      moving on.
- [ ] Stop voice mid-step, restart. New session does NOT pre-fill values
      from the previous session (Issue 5 fix).
- [ ] Tap a different field on the form mid-session — Gemini pivots to it
      (only after Issue 6 is implemented).

---

## Backend Reference Map (where to look on the server)

| What | File |
|---|---|
| WS protocol & event types | `services/onboarding/src/onboarding/api/ws_routes.py` |
| Session creation & state | `services/onboarding/src/onboarding/api/routes.py` |
| Gemini Live bridge (audio + tools) | `services/onboarding/src/onboarding/services/gemini_live.py` |
| System prompt template | `services/onboarding/src/onboarding/prompts/onboarding_system.md` |
| Tool dispatch (update_field, advance_step, add_repeatable_row) | `services/onboarding/src/onboarding/services/tools.py` |
| Schema spec (Pydantic) | `services/onboarding/src/onboarding/models/schema_spec.py` |
| Screen state v2 validation | `services/onboarding/src/onboarding/services/screen_context.py` |
| Test harness HTML | `services/onboarding/test_harness.html` |

---

## Why all these fixes are Flutter-side, not backend-side

The backend cannot:
- Mute the phone microphone (Issue 1)
- Reorder a schema it didn't author (Issue 2)
- Invent fields the client didn't send (Issue 3)
- Track repeatable rows without a section spec for them (Issue 4)
- Distinguish app-fill from voice-fill in `initial_state` (Issue 5)
- Know what's on screen without being told (Issue 6)

All of these require client-side authority. The server is correct; the
schema and the WS messages are the single source of truth, and Flutter
owns both.
