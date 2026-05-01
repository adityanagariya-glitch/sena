# Flutter Schema Order + Live Sync Fix

**Issue:** Voice agent asks fields in a different order than the UI form,
and only collects 5 of 15+ fields before closing the session.

**Root cause:** `lib/core/voice_schemas/step1_personal_info_schema.dart`
is hand-maintained, out of order vs the UI form, and missing 10+ fields.
The schema sent to the server IS what Gemini follows — there is no implicit
reorder, the server uses section/field order verbatim.

---

## Part 1 — REQUIRED: Reorder + complete the schema

The Flutter schema in `lib/core/voice_schemas/step1_personal_info_schema.dart`
**must mirror the UI form** in `personal_details_step_content.dart` exactly.

### Current UI form order (truth)

| # | UI label | Section | Voice field id | Type | Required |
|---|---|---|---|---|---|
| 1 | Full Name | basics | `full_name` | text | yes |
| 2 | Email Address | basics | `email` | email | yes (disabled in UI — pre-fill) |
| 3 | Phone Number | basics | `phone` | phone | yes |
| 4 | Date of Birth | basics | `date_of_birth` | date | yes |
| 5 | Gender | basics | `gender` | enum | yes |
| 6 | About Me | basics | `about_me` | textarea | yes |
| 7 | Preferred Language | basics | `preferred_languages` | multi_enum | yes |
| 8 | Interpreter Required | basics | `interpreter_required` | boolean | yes |
| 9 | Address | home_address | `address` | text | yes |
| 10 | State | home_address | `state` | text | yes |
| 11 | City | home_address | `city` | text | yes |
| 12 | Postcode | home_address | `zip_code` | text | yes |
| 13 | Service Address | service_address | `address` | text | optional |
| 14 | Service State | service_address | `state` | text | optional |
| 15 | Service City | service_address | `city` | text | optional |
| 16 | Service Postcode | service_address | `zip_code` | text | optional |
| 17 | Emergency Contacts | emergency_contacts | (repeatable: name, relation, email, phone) | — | min 1 |

### Replacement schema (paste into `step1_personal_info_schema.dart`)

```dart
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
            FieldSpec(id: 'full_name',           label: 'Full Name',           type: FieldType.text,        required: true),
            FieldSpec(id: 'email',               label: 'Email Address',       type: FieldType.email,       required: true),
            FieldSpec(id: 'phone',               label: 'Phone Number',        type: FieldType.phone,       required: true),
            FieldSpec(id: 'date_of_birth',       label: 'Date of Birth',       type: FieldType.date,        required: true),
            FieldSpec(id: 'gender',              label: 'Gender',              type: FieldType.choice,      required: true,
                      choices: ['Male', 'Female', 'Non-binary', 'Prefer not to say', 'Other']),
            FieldSpec(id: 'about_me',            label: 'About Me',            type: FieldType.longText,    required: true),
            FieldSpec(id: 'preferred_languages', label: 'Preferred Language',  type: FieldType.multiChoice, required: true,
                      choices: ['English', 'Mandarin', 'Cantonese', 'Arabic', 'Vietnamese', 'Greek', 'Italian', 'Other']),
            FieldSpec(id: 'interpreter_required',label: 'Interpreter Required',type: FieldType.choice,      required: true,
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
        // NOTE: emergency_contacts is repeatable. The current Flutter
        // StepSchema entity does not support a `repeatable` flag — extend it
        // first (see Part 1b) before adding this section.
      ],
    );
```

### Mapping table (also update — this is the bidirectional bridge)

```dart
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
  // emergency_contacts handled separately when repeatable support is added
};

// Inverse map mirrors this — generate it from _voiceToSena.
```

The `ClientStep1VoiceSink` must accept these new sena paths and route them to
the correct `TextEditingController` / Rx field on the controller.

---

## Part 1b — Add repeatable section support to `StepSchema`

`lib/features/voice_onboarding/domain/entities/step_schema.dart` currently has
no `repeatable` field. Add it:

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
}
```

And update `step_schema_model.dart` to serialize these correctly to the
backend's wire format (`item_fields`, `repeatable: { min, max }`).

Then add to the schema:

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

---

## Part 2 — RECOMMENDED: Live screen-state sync

After Part 1 the schema order matches the UI, but it's still **static** —
sent once at session creation. If the user scrolls or jumps to a specific
field, Gemini doesn't know.

The server already supports live `screen_state_v2` messages. Flutter just
needs to send them.

### What to send

Add to `voice_session_controller.dart`:

```dart
/// Send the current screen state to the server.
/// Call after each meaningful UI change: scroll, focus, field validation.
Future<void> sendScreenState({
  required String focusedSection,
  required String focusedField,
  required Map<String, String> fieldStatus, // 'filled' | 'empty' | 'invalid'
  Map<String, int>? repeatableRows,
}) async {
  if (_session == null) return;
  await _stream.sendScreenStateV2(
    sessionId: _session!.sessionId,
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

### When to send

In `personal_details_step_content.dart`, attach `FocusNode` listeners to each
field. On focus change, call `sendScreenState(...)` with:
- `focused_section` = section id of the focused field
- `focused_field`   = field id of the focused field
- `field_status`    = current state of every voice-mapped field
  - `filled` if controller has a value
  - `invalid` if validator returns an error
  - `empty` otherwise

Throttle/debounce to ~200ms to avoid flooding the WS.

### What the server does with it

The system prompt (`onboarding_system.md`) already instructs Gemini:
> "When you receive a [SCREEN] block, ... Focus (section/field the user is on),
> Filled (already captured), Empty (still needed), Invalid (re-ask these)...
> Prioritise Empty and Invalid fields in the current Focus section first,
> then loop back to confirm any Filled ones."

So once Flutter starts sending screen_state, Gemini will follow the user's
focus in real time instead of plowing through schema order.

---

## Validation checklist before testing

1. `flutter analyze` is 0 warnings.
2. Schema field order in `step1_personal_info_schema.dart` matches the UI
   widget order in `personal_details_step_content.dart` exactly.
3. Every voice field id has a `_voiceToSena` mapping AND the sink applies it
   correctly to the controller.
4. Voice session start, no user input — agent should ask `full_name` first
   (matches schema position 0, also UI position 1).
5. After answering `full_name`, agent asks `email` (position 1 in both).
6. Continue through all 16+ fields without skipping or reordering.
7. Emergency contacts: agent asks for at least one, then offers "would you
   like to add another?"

---

## Why the schema must match the UI 1:1

There is no Flutter→server→Gemini reorder layer. The schema JSON is the
single source of truth Gemini reads. If the schema says `[name, DOB, phone,
email]` but the UI shows `[name, email, phone, DOB]`, Gemini follows the
schema. The UI and schema are two views of the same form — keep them
locked together. A unit test that asserts the order match would prevent
this drift permanently.
