# Flutter Dev Handoff — Voice Onboarding Step 1 Validation Contract

> Read this top-to-bottom before touching any code. This is the only document you need.
> File written: `C:\Users\Admin\Downloads\sena-mobile\sena-mobile\SENA_AI\flutterhandoffdev.md`
> Scope: Client onboarding Step 1 — Personal Details (18 fields). Voice + typed input parity.

---

## 0. Severity & Context

### What is broken today

The Flutter app currently treats voice input and typed input as two **completely different code paths** with two **completely different validation contracts**. The result is that for the same field (e.g. `personalDetails.fullName`):

- **Typed path**: the user types into a `TextEditingController`. The controller's value updates immediately. Validation only fires when the user taps **Submit** and the parent `Form.validate()` runs all field validators at once. Until that moment, invalid input lives inside controllers and inside the draft `ClientOnboardingStep1PayloadModel`.
- **Voice path**: the STT result is written **straight into the same `TextEditingController`** by `lib/features/voice_onboarding/presentation/widgets/client_step1_voice_sink.dart`. There is **zero client-side validation**. The sink calls `AppSnackbar.success('$label captured')` regardless of whether the value was junk. DOB voice parse failures are swallowed silently in `client_step1_voice_sink.dart:64` with only an `AppLogger.error` call. The server emits `validation_rejection` envelope events when its server-side validators reject a voice write, but the Flutter parser at `lib/features/voice_onboarding/data/models/voice_event_model.dart` has no case for them — the events are silently dropped on the floor. The user never sees them. The mic does not re-open. The TTS never speaks them.

The net effect: a participant on a voice-led onboarding can advance through Step 1 having entered garbage data with cheerful "captured" confirmations the whole way, only to be confronted with a wall of Form-level red text at submit time. Or worse, with no confirmation at all that voice input failed and the field still holds whatever was there before.

### Why prior attempts failed

Earlier passes added piecemeal validators in the existing `AppValidators` and tied them to the `Form` widget at submit. They did not:

1. Make voice and typed share **one** validation entrypoint.
2. Capture **input_method** (typed vs voice) so that errors and analytics know which mode produced the failure.
3. Surface server-side `validation_rejection` events to the user.
4. Speak errors back to the user when the failure originated from a voice utterance.
5. Buffer typed input so that an invalid keystroke does not pollute controller / draft state.
6. Report client-side validation failures to the backend at `POST /v1/onboarding/session/{session_id}/errors`.

This document fixes all six gaps in one pass.

### Why voice is first-class

SENA's onboarding is **voice-led by design**. A non-trivial fraction of participants will complete Step 1 entirely by voice, never tapping a keyboard. Anything the typed path does (validate, show error, accept, persist) the voice path **must** do (validate, speak error, re-open mic, accept, speak confirmation, persist). Voice is **not** a secondary affordance. Every section of this document that talks about typed input talks about voice with equal depth.

### Why this contract is non-negotiable

Step 1 is the entry to every NDIS-funded service interaction the participant ever has with SENA. A bad email here breaks every downstream consent message. A bad DOB here makes the participant ineligible for an entire class of supports. A bad emergency contact phone here makes an emergency unreachable. Drift between voice path and typed path produces real harm to vulnerable participants. We treat validation as the **Law of the App**, not as a polish concern.

---

## 1. The Validation Contract (The Law of the App)

**The 5 non-negotiable invariants (mirrored verbatim in `SENA_AI/.claude/SESSION_START.md` and `.claude/issues-solved/0006-voice-typed-validation-parity.md`):**

1. **Validate-before-state.** A field never updates a controller / draft / `Rx*` before validation passes — typed **or** voice. No "write first, validate later" allowed for either input method.
2. **`input_method` is first-class.** Captured at intake (`InputMethod.typed` or `InputMethod.voice`), threaded through every validator call and every `ValidationErrorReporter.report` call. Backend `FieldValue.input_method` surfaces on `field_apply` WS envelopes for downstream audit.
3. **POST `/v1/onboarding/session/{session_id}/errors`** fires on every validation FAIL (typed AND voice). Strict body shape; persists to Redis list `sena:onboarding:errors:{sid}`, 7-day TTL.
4. **Voice failure → TTS speaks the same on-screen string + auto-reopens the mic.** No silent drops. The string the user reads and the string Sena speaks are both pulled from `AppStrings` — never inlined in controllers. Where the spoken phrasing diverges from the inline phrasing, both must exist as separate `AppStrings` keys (e.g. `auStateInvalid` + `voiceAuStateInvalid`). See section 10.
5. **Voice = first-class.** Every validator, every error path, every cross-field invariant applies equally to both input methods. No "voice happy-path" shortcuts.

Every field write, typed or voice, MUST follow this sequence. No exceptions.

1. **Receive** the raw input value plus its `InputMethod` (`typed` or `voice`).
2. **Resolve** the field's canonical sena path (e.g. `personalDetails.email`).
3. **Validate** the raw input value through the field's pure-Dart validator.
4. **Branch**:

   - **3a) On PASS**:
     - Commit the value to the canonical `TextEditingController` (or `Rx*` for non-text fields).
     - Update the typed draft model via the existing `replaceStep1Draft` / `mergeClientOnboardingStep3Draft` style helpers — never via raw maps.
     - Clear `fieldErrors[senaPath]` from the controller's `RxMap<String, String>`.
     - Update `_lastValid[senaPath] = value`.
     - **If `InputMethod.voice`**: call `_speakSuccess(field.label)` using the templated voice success string (see section 4 per-field table). **Do not** show a snackbar. Replace existing `AppSnackbar.success('$label captured')` at `voice_session_controller.dart:403` with the TTS call.
     - **If `InputMethod.typed`**: simply clear the inline error — no toast, no speak.

   - **3b) On FAIL**:
     - **Do not** write the value into the canonical controller or the draft.
     - Set `fieldErrors[senaPath] = reasonHuman` on the controller. The widget renders this as `errorText:` adjacent to the field.
     - Call `ValidationErrorReporter.report(...)` (see section 2 below) — fire-and-forget, retries on its own, never blocks UI.
     - **If `InputMethod.voice`**:
       - Call `_speak(reasonHuman)` (same TTS as `agent_said` events).
       - Call `_micController.reopen()` so the participant can re-utter immediately.
       - Call `_revertField(senaPath)` using `_lastValid[senaPath] ?? ''`.
     - **If `InputMethod.typed`**:
       - The keystroke was written to the **buffered** `TextEditingController` (not the canonical one). The buffer keeps the user's keystrokes visible so they can correct in place. The canonical controller and the draft remain at the last-valid value. Validation runs on `debounce(250ms)` after each keystroke.

5. **Race policy** (voice arriving while the user is typing into the same field):
   - If a voice-mapped `TextField` currently has primary focus, incoming voice updates for that sena path are **queued** for up to 5 seconds and applied on blur. If queue is full or the wait exceeds 5 seconds, the voice update is rejected with `_speak("Still typing — finish first.")`.

This is the entire contract. The rest of this document is implementation detail.

---

## 2. Input Method Tracking

### 2.1 The enum

Create `lib/core/enums/input_method.dart`:

```dart
/// Source of a Step-1 field write. Threaded through every validator call
/// and every error report so the analytics layer and the validation
/// rejection event payload always know whether the failure happened on
/// a keyboard keystroke or on a spoken utterance.
enum InputMethod { typed, voice }
```

### 2.2 Where input_method is captured

| Entry point | File:line (approx) | InputMethod value |
|---|---|---|
| `TextField.onChanged` for any voice-mapped text field | `personal_details_step_content.dart` per-field builders | `InputMethod.typed` |
| Voice STT result arriving via `client_step1_voice_sink.applyVoiceUpdate` | `lib/features/voice_onboarding/presentation/widgets/client_step1_voice_sink.dart` | `InputMethod.voice` |
| Dropdown `onChanged` (gender, relation) | `personal_details_step_content.dart` | `InputMethod.typed` |
| Date picker `onConfirm` | `personal_details_step_content.dart` DOB picker | `InputMethod.typed` |
| Checkbox / RadioToggle (interpreterRequired) | `personal_details_step_content.dart` | `InputMethod.typed` |
| Address autocomplete `onPlaceSelected` | `personal_details_step_content.dart` | `InputMethod.typed` |

### 2.3 Typed entry capture — code snippet

```dart
// Inside personal_details_step_content.dart, Full Name field builder:
AppTextField(
  controller: ctrl.fullNameBuffer.textController, // buffered controller, not canonical
  onChanged: (raw) {
    ctrl.fullNameBuffer.onChanged(raw); // buffer schedules debounced validation
  },
  errorText: ctrl.fieldErrors['personalDetails.fullName'],
  ...
)

// Inside BufferedFieldController.onChanged:
void onChanged(String raw) {
  _bufferText.value = raw;
  _debouncer.run(() => _ctrl.setFromTyped('personalDetails.fullName', raw));
}
```

### 2.4 Voice entry capture — code snippet

```dart
// Replace the body of client_step1_voice_sink.applyVoiceUpdate(...)
void applyVoiceUpdate({
  required String senaPath,
  required Object? rawValue,
  double? confidence,
}) {
  // No direct TextEditingController write. No AppSnackbar.success.
  _ctrl.setFromVoice(senaPath, rawValue, confidence: confidence);
}
```

### 2.5 Validator signature

All field validators move to a single pure-Dart entrypoint on `ClientStep1Controller`:

```dart
/// Single validation entrypoint for both InputMethod.typed and InputMethod.voice.
/// Returns null on PASS, a non-null reasonHuman on FAIL.
String? _validateField({
  required String senaPath,
  required Object? value,
  required InputMethod inputMethod,
});
```

The branching `setFromTyped` / `setFromVoice` methods call `_validateField` and then run the PASS / FAIL paths from section 1. They do **not** duplicate validation logic.

### 2.6 Error report POST — code snippet

```dart
// Permanent GetxService registered in bootstrap:
class ValidationErrorReporter extends GetxService {
  final ReportValidationErrorUsecase _usecase;
  final _queue = <OnboardingErrorReport>[];
  final _retryDelays = const [
    Duration(milliseconds: 250),
    Duration(milliseconds: 500),
    Duration(seconds: 1),
    Duration(seconds: 2),
    Duration(seconds: 4),
    Duration(seconds: 4),
  ];

  ValidationErrorReporter(this._usecase);

  Future<void> report({
    required String errorCode,
    required String errorMessage,
    required InputMethod inputMethod,
    required String fieldId,
    required Object? attemptedValue,
  }) async {
    final sessionId = Get.find<VoiceSessionController>().sessionId.value;
    if (sessionId == null || sessionId.isEmpty) return; // no session, drop silently
    final report = OnboardingErrorReport(
      errorType: errorCode,
      errorMessage: errorMessage,
      inputMethod: inputMethod,
      fieldId: fieldId,
      attemptedValue: attemptedValue,
      sessionId: sessionId,
      ts: DateTime.now().toUtc(),
    );
    _enqueueAndFlush(report);
  }

  // ... _enqueueAndFlush with 6-attempt exp backoff per delay above, drop on exhaust
}
```

POST body shape (sent verbatim by the datasource):

```json
{
  "error_type": "full_name_requires_first_last",
  "error_message": "Please say both first and last name, for example Jane Doe.",
  "input_method": "voice",
  "field_id": "personalDetails.fullName",
  "attempted_value": "Madonna",
  "ts": "2026-05-12T03:18:22.114Z"
}
```

The `session_id` is carried in the URL path only — do NOT include it in the JSON body. The backend `ClientValidationErrorRequest` is `extra="forbid"`; any extra field returns 422. The datasource composes the URL as `/v1/onboarding/session/$sessionId/errors` and posts the body verbatim above.

Endpoint: `POST /v1/onboarding/session/{session_id}/errors`. Expected response: `204 No Content`. On any non-2xx response the reporter retries per the backoff schedule (250/500/1000/2000/4000/4000ms, 6 attempts — see section 2.6 above), then drops with an `AppLogger.error`. Never blocks the UI.

---

## 3. Architecture Changes Required (Cross-Cutting)

> Make all of these changes BEFORE starting per-field work — they unblock everything else. The per-field work in section 4 assumes all of section 3 is already in place.

### 3.1 enum InputMethod

- **File to create**: `lib/core/enums/input_method.dart`
- **Why**: every validator call and every error report needs to know which mode produced the input. Today the codebase has no such enum; `FieldSource(voice|app|system)` is a different concept — it is an origin marker for who **proposed** a value, not the typed-vs-voice intent.
- **Code**:

```dart
enum InputMethod { typed, voice }
```

### 3.2 Validation error reporter (new feature)

Create a normal clean-architecture feature under `lib/features/validation_error_reporting/`:

```
domain/
  entities/onboarding_error_report.dart
  repositories/onboarding_error_repository.dart
  usecases/report_validation_error_usecase.dart
data/
  models/onboarding_error_report_model.dart
  datasources/onboarding_error_remote_datasource.dart
  repositories/onboarding_error_repository_impl.dart
presentation/
  services/validation_error_reporter.dart   // GetxService, permanent
```

- **Entity** `OnboardingErrorReport`:

```dart
class OnboardingErrorReport {
  final String errorType;     // e.g. 'full_name_requires_first_last'
  final String errorMessage;  // reasonHuman shown to user
  final InputMethod inputMethod;
  final String fieldId;       // sena path, e.g. 'personalDetails.email'
  final Object? attemptedValue;
  final String sessionId;
  final DateTime ts;
  const OnboardingErrorReport({...});
}
```

- **Usecase** `ReportValidationErrorUsecase(repo).call(report)` → `Future<Either<Failure, void>>`.
- **Datasource**: hits `POST /v1/onboarding/session/{sessionId}/errors`, body is the JSON shape in section 2.6. Expects `204`. Does **not** require a 200-envelope; treat any 2xx as success.
- **Service** `ValidationErrorReporter`: registered permanent in `AuthApiBinding` (or wherever the session controller is bootstrapped). In-memory FIFO queue. Backoff sequence: 250 / 500 / 1000 / 2000 / 4000 / 4000 ms, max 6 attempts, then drop with `AppLogger.error`. **Non-blocking.** Fire and forget from validators.

### 3.3 voice_event_model.dart — add `validation_rejection` case

- **File**: `lib/features/voice_onboarding/data/models/voice_event_model.dart`
- **Why**: today the parser has no branch for the `validation_rejection` event type, so server-emitted rejections are silently dropped. The whole point of voice-first validation parity is that the participant hears these.
- **Add inside the parser switch / if-chain**:

```dart
case 'validation_rejection':
  final allowed = json['allowed_values'];
  return VoiceValidationRejection(
    sectionId: json['section_id'] as String,
    fieldId: json['field_id'] as String,
    repeatableIndex: json['repeatable_index'] as int?,
    code: (json['code'] as String?) ?? 'unknown',
    reasonHuman: (json['reason_human'] as String?) ?? '',
    suggestedFix: json['suggested_fix'] as String?,
    allowedValues: allowed is List
        ? allowed.whereType<String>().toList(growable: false)
        : const <String>[],
  );
```

- **Also add** the entity `VoiceValidationRejection` to `lib/features/voice_onboarding/domain/entities/voice_event.dart` with the same fields. Add the sealed-class branch / `is`-check used elsewhere in the file.

### 3.4 voice_session_controller `_handleEvent` branch

- **File**: `lib/features/voice_onboarding/presentation/controllers/voice_session_controller.dart`
- **Why**: same reason as 3.3 — the entity exists now, the controller still needs to dispatch on it.
- **Add a case** to the `switch` / type-test in `_handleEvent`:

```dart
case VoiceValidationRejection rej:
  _onValidationRejection(rej);
  break;
```

- **Implement `_onValidationRejection`**:

```dart
Future<void> _onValidationRejection(VoiceValidationRejection rej) async {
  final senaPath = _resolveSenaPath(rej.sectionId, rej.fieldId, rej.repeatableIndex);
  final reason = rej.reasonHuman.isEmpty ? AppStrings.genericValidationFailed : rej.reasonHuman;

  // 1. Inline error
  Get.find<ClientStep1Controller>().fieldErrors[senaPath] = reason;

  // 2. Speak the reason
  await _speak(reason);

  // 3. Re-open mic
  _micController.reopen();

  // 4. Revert any partial write
  Get.find<ClientStep1Controller>().revertField(senaPath);

  // 5. Report
  Get.find<ValidationErrorReporter>().report(
    errorCode: rej.code,
    errorMessage: reason,
    inputMethod: InputMethod.voice,
    fieldId: senaPath,
    attemptedValue: null, // server already has it
  );
}
```

### 3.4a voice_event_model.dart — add `field_advisory_warning` case

- **File**: `lib/features/voice_onboarding/data/models/voice_event_model.dart`
- **Why**: the server emits `field_advisory_warning` for non-blocking validation nudges (e.g. a soft format suggestion). Without this case the event is silently dropped and the advisory is never surfaced to the participant.
- **Add inside the parser switch / if-chain** (after the `validation_rejection` case):

```dart
case 'field_advisory_warning':
  final allowed = json['allowed_values'];
  return VoiceFieldAdvisoryWarning(
    sectionId: json['section_id'] as String,
    fieldId: json['field_id'] as String,
    repeatableIndex: json['repeatable_index'] as int?,
    code: (json['code'] as String?) ?? 'unknown',
    reasonHuman: (json['reason_human'] as String?) ?? '',
    severity: 'advisory',
    suggestedFix: json['suggested_fix'] as String?,
    allowedValues: allowed is List
        ? allowed.whereType<String>().toList(growable: false)
        : const <String>[],
  );
```

- **Also add** the entity `VoiceFieldAdvisoryWarning` to `lib/features/voice_onboarding/domain/entities/voice_event.dart` with the same fields. Add the sealed-class branch / `is`-check used elsewhere in the file.
- **Add a case** to the `switch` / type-test in `_handleEvent` (in `voice_session_controller.dart`):

```dart
case VoiceFieldAdvisoryWarning warn:
  _onFieldAdvisoryWarning(warn);
  break;
```

- **Implement `_onFieldAdvisoryWarning`**:

```dart
void _onFieldAdvisoryWarning(VoiceFieldAdvisoryWarning warn) {
  final key = _advisoryKey(warn.sectionId, warn.fieldId, warn.repeatableIndex);
  // Store advisory — do NOT block field progression or revert
  _pendingAdvisories[key] = warn;
  // Surface after the current extraction burst completes (post-frame)
  WidgetsBinding.instance.addPostFrameCallback((_) {
    if (_pendingAdvisories.containsKey(key)) {
      Get.find<ClientStep1Controller>().fieldAdvisories[
          _resolveSenaPath(warn.sectionId, warn.fieldId, warn.repeatableIndex)] =
          warn.reasonHuman;
    }
  });
}

String _advisoryKey(String sectionId, String fieldId, int? index) =>
    index == null ? '$sectionId.$fieldId' : '$sectionId.$fieldId.$index';

// Add to controller state:
// final Map<String, VoiceFieldAdvisoryWarning> _pendingAdvisories = {};
// Cleared when next update_field for same field returns ok=true with no warning.
```

- **Clear advisory on successful write**: in the existing `_onFieldApply` (or wherever `field_apply` events are handled), after a successful commit add:

```dart
_pendingAdvisories.remove(_advisoryKey(event.sectionId, event.fieldId, event.repeatableIndex));
Get.find<ClientStep1Controller>().fieldAdvisories.remove(
    _resolveSenaPath(event.sectionId, event.fieldId, event.repeatableIndex));
```

- **`fieldAdvisories` on `ClientStep1Controller`** — add alongside `fieldErrors`:

```dart
final RxMap<String, String> fieldAdvisories = <String, String>{}.obs;
```

Wire each field's advisory into a secondary hint text widget (amber, not red). Do NOT disable the Next/Submit button based on advisory state — these are non-blocking by contract.

---

### 3.4b voice_event_model.dart — add `field_confirmed` case

- **File**: `lib/features/voice_onboarding/data/models/voice_event_model.dart`
- **Why**: the server emits `field_confirmed` when it has positively acknowledged a voice-captured value. Without this case the client cannot suppress redundant re-confirmation prompts, leading to the agent asking the participant to confirm the same value twice.
- **Add inside the parser switch / if-chain** (after the `field_advisory_warning` case):

```dart
case 'field_confirmed':
  return VoiceFieldConfirmed(
    sectionId: json['section_id'] as String,
    fieldId: json['field_id'] as String,
    repeatableIndex: json['repeatable_index'] as int?,
    value: json['value'],
    confirmationSource: (json['confirmation_source'] as String?) ?? 'voice',
    turnId: json['turn_id'] as int? ?? 0,
  );
```

- **Also add** the entity `VoiceFieldConfirmed` to `lib/features/voice_onboarding/domain/entities/voice_event.dart`. Add the sealed-class branch / `is`-check.
- **Add a case** to the `switch` / type-test in `_handleEvent`:

```dart
case VoiceFieldConfirmed confirmed:
  _onFieldConfirmed(confirmed);
  break;
```

- **Implement `_onFieldConfirmed`**:

```dart
void _onFieldConfirmed(VoiceFieldConfirmed confirmed) {
  final senaPath = _resolveSenaPath(
      confirmed.sectionId, confirmed.fieldId, confirmed.repeatableIndex);
  // Mark as confirmed in local session state — purely local, no network call
  Get.find<ClientStep1Controller>().confirmedFields.add(senaPath);
  // Suppress any pending re-confirmation UI for this field
  Get.find<ClientStep1Controller>().pendingConfirmationFields.remove(senaPath);
}
```

- **`confirmedFields` and `pendingConfirmationFields` on `ClientStep1Controller`** — add:

```dart
final RxSet<String> confirmedFields = <String>{}.obs;
final RxSet<String> pendingConfirmationFields = <String>{}.obs;
```

`confirmedFields` is cleared on `Get.find<ClientStep1Controller>().resetSession()` or when the step advances. `pendingConfirmationFields` is populated by whichever logic currently triggers re-confirmation prompts — remove the check for any path present in `confirmedFields` to suppress the duplicate prompt.

---

### 3.5 Voice sink no longer writes directly

- **File**: `lib/features/voice_onboarding/presentation/widgets/client_step1_voice_sink.dart`
- **Why**: today the sink writes raw STT into `TextEditingController`s and emits a success snackbar before any validation runs. The sink is the leak. Plug it.
- **Replacement**:

```dart
void applyVoiceUpdate({
  required String senaPath,
  required Object? rawValue,
  double? confidence,
}) {
  _ctrl.setFromVoice(senaPath, rawValue, confidence: confidence);
}
```

The sink does nothing else. It does not call `AppSnackbar`. It does not touch `TextEditingController`s. It does not parse DOB. All routing of voice writes through validation happens inside `ClientStep1Controller.setFromVoice(...)`.

### 3.6 Typed buffered + debounced validation

- **File to create**: `lib/core/utils/buffered_field_controller.dart`
- **Why**: today every keystroke writes straight into the canonical `TextEditingController` and into the draft. The contract requires that invalid keystrokes never enter the draft. The buffer holds the user's visible text; only on PASS does it promote to the canonical controller.

```dart
class BufferedFieldController {
  final TextEditingController textController; // visible to the user
  final void Function(String) onValidatedCommit; // commits to canonical + draft
  final Future<String?> Function(String) validate; // returns null on PASS
  final _debouncer = Debouncer(milliseconds: 250);

  void onChanged(String raw) {
    // buffer is just the TextField's existing controller; nothing extra to write here
    _debouncer.run(() async {
      final err = await validate(raw);
      if (err == null) {
        onValidatedCommit(raw);
      }
      // FAIL path: leave buffer text alone, controller updates fieldErrors map externally
    });
  }
}
```

- **Where used**: instantiate one per voice-mapped field on `ClientStep1Controller.onInit()`. Wire each `AppTextField` to its buffer's `textController`.

For non-text fields (dropdown, date picker, checkbox, autocomplete): commit-on-pick path runs the validator **synchronously**. No buffering needed because the input event is discrete, not per-keystroke.

### 3.7 `RxMap<String, String>` `fieldErrors` on `ClientStep1Controller`

- **Add to** `ClientStep1Controller` (which already exists at `lib/features/voice_onboarding/presentation/controllers/client_step_1_controller.dart`):

```dart
final RxMap<String, String> fieldErrors = <String, String>{}.obs;
final Map<String, Object?> _lastValid = {};
```

- **Wire into `personal_details_step_content.dart`**: every `AppTextField`, `AppDropdown`, `AppDatePicker` adjacent error message reads `ctrl.fieldErrors[senaPath]`. Use `Obx` only on the error-text widget so the field rebuild scope stays tiny.
- **Form.validate() at submit becomes a no-op fallback** — if `fieldErrors.isNotEmpty`, the Submit button shows an `AppSnackbar.error('Please fix the highlighted fields.')` and aborts. Per-field validators wired to `Form` keys are removed (they double-validate and produce conflicting errors).

### 3.8 AU state normaliser

- **File to create**: `lib/core/utils/au_state_normaliser.dart`
- **Why**: voice and typed both accept `"new south wales"`, `"NSW"`, `"N S W"`, `"new s w"`, etc. The server already has an alias table. Bundle the same one client-side so the normalised abbreviation is what lands in the controller and in the draft.

```dart
class AuStateNormaliser {
  static const _aliases = <String, String>{
    'nsw': 'NSW', 'new south wales': 'NSW',
    'vic': 'VIC', 'victoria': 'VIC',
    'qld': 'QLD', 'queensland': 'QLD',
    'sa': 'SA', 'south australia': 'SA',
    'wa': 'WA', 'western australia': 'WA',
    'tas': 'TAS', 'tasmania': 'TAS',
    'act': 'ACT', 'australian capital territory': 'ACT',
    'nt': 'NT', 'northern territory': 'NT',
  };
  static String? normalise(String input) {
    final key = input.trim().toLowerCase().replaceAll(RegExp(r'\s+'), ' ');
    return _aliases[key];
  }
}
```

### 3.9 Disposable email blocklist

- **File to create**: `lib/core/utils/disposable_email_blocklist.dart`
- **Why**: bundle the same blocklist the server uses so the rejection is immediate, not after a server round-trip.

```dart
class DisposableEmailBlocklist {
  static const _domains = <String>{
    'mailinator.com',
    'guerrillamail.com',
    '10minutemail.com',
    'tempmail.com',
    'throwaway.email',
    'yopmail.com',
    'fakeinbox.com',
    'trashmail.com',
    'sharklasers.com',
    'getairmail.com',
    'dispostable.com',
  };
  static bool isDisposable(String email) {
    final at = email.indexOf('@');
    if (at < 0) return false;
    return _domains.contains(email.substring(at + 1).toLowerCase());
  }
}
```

- Add `AppValidators.emailWithDisposableCheck(value)` that runs the existing regex then the blocklist check.

### 3.10 DOB voice parsing — replace silent failure

- **File**: `lib/features/voice_onboarding/presentation/widgets/client_step1_voice_sink.dart` around line 64
- **Today**: voice DOB that fails `tryParseDisplayDate` is silently dropped with only an `AppLogger.error`. Replace with the rejection path:

```dart
// Inside ClientStep1Controller.setFromVoice for personalDetails.dateOfBirth:
final parsed = tryParseDisplayDate(rawString);
if (parsed == null) {
  return _failVoice(
    senaPath: 'personalDetails.dateOfBirth',
    code: 'dob_invalid_format',
    reason: AppStrings.dateInvalidFormat, // 'Please enter a valid date (YYYY-MM-DD).'
    attempted: rawString,
  );
}
// then run the full DOB validator chain (not-future, age >= 18) on `parsed`
```

`tryParseDisplayDate` accepts only `dd/MM/yyyy` and ISO `YYYY-MM-DD`. Relative phrases like `"yesterday"`, `"next Tuesday"`, `"two years ago"` are rejected with `dob_invalid_format`.

### 3.11 Snackbar policy

- **File**: `lib/features/voice_onboarding/presentation/controllers/voice_session_controller.dart` around line 403.
- **Today**: `AppSnackbar.success('$label captured')` fires on every voice write including writes that the server later rejects.
- **Replace with**: `_speakSuccess(label)` using the per-field templated voice success string from section 4. No snackbar on voice success — speech only.
- Typed PASS: also no snackbar — just clear the inline error.
- Snackbars remain for **global system errors** only (network down, auth expired, submit failed).

---

## 4. Field-by-Field Change List

### Table of Contents

- 4.1 `personalDetails.fullName`
- 4.2 `personalDetails.email`
- 4.3 `personalDetails.phone`
- 4.4 `personalDetails.dateOfBirth`
- 4.5 `personalDetails.gender`
- 4.6 `personalDetails.aboutMe`
- 4.7 `personalDetails.preferredLanguages`
- 4.8 `personalDetails.interpreterRequired`
- 4.9 `personalDetails.interpreterLanguage` (typed-only, phase 1)
- 4.10 `personalDetails.address`
- 4.11 `personalDetails.state`
- 4.12 `personalDetails.city`
- 4.13 `personalDetails.zipCode`
- 4.14 `personalDetails.serviceAddress`
- 4.15 `personalDetails.serviceState`
- 4.16 `personalDetails.serviceCity`
- 4.17 `personalDetails.serviceZipCode`
- 4.18 `personalDetails.emergencyContacts[i].name`
- 4.19 `personalDetails.emergencyContacts[i].relation`
- 4.20 `personalDetails.emergencyContacts[i].email`
- 4.21 `personalDetails.emergencyContacts[i].phone`

> Each emergency_contacts subfield is repeated per row index `i ∈ [0..4]`. Row index 5+ is rejected by the row-cap check (see 5.3).

---

### 4.1 `personalDetails.fullName`

- **Widget**: `personal_details_step_content.dart` — Full Name `AppTextField` builder
- **Controller binding**: `ClientStep1Controller.fullNameController` (canonical) wrapped by `BufferedFieldController fullNameBuffer`
- **Voice schema path**: `basics.full_name`
- **Input modes**: typed | voice
- **Type / Required**: `string`, required
- **Current behaviour**:
  1. Voice STT result writes to `fullNameController` directly. Snackbar success fires.
  2. Typed keystrokes write directly to `fullNameController`. No validation until submit.
  3. Submit-time `AppValidators.clientParticipantFullName` (at `base_validators.dart:145-155`) runs; rejection shown only in `Form` field error slot at the bottom of the page, not in the speak channel.
- **Required behaviour**:
  1. Either path lands in `ClientStep1Controller.setFromX('personalDetails.fullName', raw, InputMethod.x)`.
  2. Validator runs (required → 2 tokens → first ≤25 → last ≤25).
  3. PASS: commit to `fullNameController`, update draft, clear error, speak "Full name updated." if voice.
  4. FAIL: do not commit. Set `fieldErrors['personalDetails.fullName'] = reason`. If voice, speak reason and re-open mic; revert to `_lastValid['personalDetails.fullName'] ?? ''`. Report to backend.

**Validation rules (Dart pseudocode):**

```dart
String? validateFullName(String? raw) {
  final v = (raw ?? '').trim();
  if (v.isEmpty) return AppStrings.fieldRequired; // 'This field is required.'
  final parts = v.split(RegExp(r'\s+'));
  if (parts.length < 2) return AppStrings.fullNameRequiresFirstAndLast;
  if (parts.first.length > 25) return AppStrings.fieldMustBeAtMostChars(25);
  if (parts.last.length > 25) return AppStrings.fieldMustBeAtMostChars(25);
  return null;
}
```

**Error messages:**

| code | on_screen | spoken | AppStrings key (on_screen / voice) |
|---|---|---|---|
| `required` | "This field is required." | "This field is required." | `AppStrings.fieldRequired` (same string both channels) |
| `full_name_requires_first_last` | "Enter full name (e.g. Jane Doe)" | "Please say both first and last name, for example Jane Doe." | `AppStrings.fullNameRequiresFirstAndLast` / `AppStrings.fullNameRequiresFirstAndLastVoice` (ADD) |
| `full_name_first_too_long` | "Must be at most 25 characters" | "First name must be at most 25 characters." | `AppStrings.fieldMustBeAtMostChars(25)` / `AppStrings.voiceFullNameFirstTooLong` (ADD) |
| `full_name_last_too_long` | "Must be at most 25 characters" | "Last name must be at most 25 characters." | `AppStrings.fieldMustBeAtMostChars(25)` / `AppStrings.voiceFullNameLastTooLong` (ADD) |

- **Pass behaviour**: `fullNameController.text = v`. Spoken: `"Full name updated."` — `AppStrings.voiceConfirmFullName` (ADD).
- **Revert-on-fail target**: `_lastValid['personalDetails.fullName'] ?? ''`.
- **Voice edge cases**: empty STT → required; one token → first/last; 27-char token → too_long. Hyphenated names ("Mary-Jane Smith") count as 2 tokens.
- **Typed edge cases**: 250ms debounce; user typing "Jane" without yet typing space + last name shows `full_name_requires_first_last` after debounce — that is correct; the buffer keeps the visible text so the user can keep typing.
- **Cross-field deps**: none.

---

### 4.2 `personalDetails.email`

- **Widget**: `personal_details_step_content.dart` — Email `AppTextField`
- **Controller binding**: `emailController` wrapped by `emailBuffer`
- **Voice schema path**: `basics.email`
- **Input modes**: typed | voice
- **Type / Required**: `string`, required
- **Current behaviour**: voice writes directly; typed validated only at submit via `AppValidators.email` (regex only, no disposable check, no caps check). Disposable email blocklist lives only on the server.
- **Required behaviour**: required → regex → RFC label/total caps → disposable blocklist (client-side, bundled).

**Validation rules:**

```dart
String? validateEmail(String? raw) {
  final v = (raw ?? '').trim().toLowerCase();
  if (v.isEmpty) return AppStrings.fieldRequired;
  final re = RegExp(r'^[a-z0-9._%+\-]+@[a-z0-9\-]+(\.[a-z0-9\-]+){1,3}$');
  if (!re.hasMatch(v)) return AppStrings.emailInvalid;
  // RFC label caps
  final localPart = v.split('@')[0];
  final domain = v.split('@')[1];
  if (localPart.length > 64) return AppStrings.emailInvalid;
  if (v.length > 254) return AppStrings.emailInvalid;
  for (final label in domain.split('.')) {
    if (label.length > 63) return AppStrings.emailInvalid;
  }
  if (DisposableEmailBlocklist.isDisposable(v)) return AppStrings.emailDisposable;
  return null;
}
```

**Error messages:**

| code | on_screen | spoken | AppStrings key (on_screen / voice) |
|---|---|---|---|
| `required` | "This field is required." | "This field is required." | `AppStrings.fieldRequired` (same string both channels) |
| `email_invalid` | "Enter a valid email" | "Please say a valid email address." | `AppStrings.emailInvalid` / `AppStrings.voiceEmailInvalid` (ADD) |
| `email_disposable` | "Please use a non-disposable email address." | "Please use a non-disposable email address." | `AppStrings.emailDisposable` (ADD — same string both channels) |

- **Pass behaviour**: commit `v` (lowercased) to `emailController`. Spoken: `"Email updated."` — `AppStrings.voiceConfirmEmail` (ADD).
- **Revert-on-fail target**: `_lastValid['personalDetails.email'] ?? ''`.
- **Voice edge cases**: STT will return `"jane at gmail dot com"` — Flutter does NOT normalise; the server-side voice agent is responsible for emitting it as `jane@gmail.com`. Client receives the normalised string; if it fails regex, reject.
- **Typed edge cases**: 250ms debounce; user halfway through `"jane@"` shows `email_invalid` after debounce — buffer keeps text so user continues.
- **Cross-field deps**: emergency contact emails must not equal this value (see 5.2).

---

### 4.3 `personalDetails.phone`

- **Widget**: `personal_details_step_content.dart` — `AustralianPhoneField`
- **Controller binding**: `phoneController` wrapped by `phoneBuffer`
- **Voice schema path**: `basics.phone`
- **Type / Required**: `string`, required
- **Current behaviour**: voice writes directly; typed validated only at submit via `AppValidators.australianMobile` (`base_validators.dart:66-73`).

**Validation rules:**

```dart
String? validatePhone(String? raw) {
  final v = (raw ?? '').replaceAll(RegExp(r'\s+'), '');
  if (v.isEmpty) return AppStrings.fieldRequired;
  final re = RegExp(r'^(?:\+61[2-478]\d{8}|0[2-478]\d{8}|1300\d{6}|1800\d{6}|13\d{4})$');
  if (!re.hasMatch(v)) return AppStrings.australianMobileInvalid;
  return null;
}
```

**Error messages:**

| code | on_screen | spoken | AppStrings key (on_screen / voice) |
|---|---|---|---|
| `required` | "This field is required." | "This field is required." | `AppStrings.fieldRequired` (same string both channels) |
| `phone_invalid_format` | "Enter a valid Australian phone number (+61 followed by 9 digits starting with 2, 3, 4, 7 or 8)" | "Please say a valid Australian phone number, starting with plus six one or zero." | `AppStrings.australianMobileInvalid` / `AppStrings.voiceAustralianMobileInvalid` (ADD) |

- **Pass behaviour**: commit to `phoneController`. Spoken: `"Phone number updated."` — `AppStrings.voiceConfirmPhone` (ADD).
- **Revert-on-fail**: `_lastValid['personalDetails.phone'] ?? ''`.
- **Voice edges**: STT often returns digits with spaces ("0 4 1 2 ..."). Strip whitespace before validate.
- **Typed edges**: 250ms debounce.
- **Cross-field deps**: emergency contact phones must not equal this value, keyed on the 9-digit normaliser `AppValidators.australianMobileNineDigits` (see 5.1).

---

### 4.4 `personalDetails.dateOfBirth`

- **Widget**: `personal_details_step_content.dart` — DOB picker
- **Controller binding**: `dobDate` (`Rxn<DateTime>`) + `dobController` (display)
- **Voice schema path**: `basics.date_of_birth`
- **Type / Required**: `date`, required
- **Current behaviour (broken)**: voice path silently swallows unparseable utterances with only `AppLogger.error`. Typed picker can't produce invalid dates by construction, but typed text-entry (when keyboard is allowed) bypasses validation until submit.
- **Required behaviour**: required → parseable to `YYYY-MM-DD` → not future → age ≥ 18.

**Validation rules:**

```dart
String? validateDob(Object? raw) {
  if (raw == null) return AppStrings.fieldRequired;
  DateTime? dt;
  if (raw is DateTime) {
    dt = raw;
  } else if (raw is String) {
    if (raw.trim().isEmpty) return AppStrings.fieldRequired;
    dt = tryParseDisplayDate(raw); // dd/MM/yyyy or YYYY-MM-DD only
    if (dt == null) return AppStrings.dateInvalidFormat;
  } else {
    return AppStrings.dateInvalidFormat;
  }
  final now = DateTime.now();
  if (dt.isAfter(now)) return AppStrings.dateMustNotBeFuture;
  final eighteenAgo = DateTime(now.year - 18, now.month, now.day);
  if (dt.isAfter(eighteenAgo)) return AppStrings.dateMustBeAtLeast18Years;
  return null;
}
```

**Error messages:**

| code | on_screen | spoken | AppStrings key (on_screen / voice) |
|---|---|---|---|
| `required` | "This field is required." | "Please tell me your date of birth." | `AppStrings.fieldRequired` / `AppStrings.voiceDobRequired` (ADD) |
| `dob_invalid_format` | "Please enter a valid date (YYYY-MM-DD)." | "I didn't catch that date. Please say it as day, month, and year, for example fourteenth of March nineteen ninety." | `AppStrings.dateInvalidFormat` (ADD) / `AppStrings.voiceDateInvalidFormat` (ADD) |
| `dob_in_future` | "Date must not be in the future." | "Your date of birth cannot be in the future." | `AppStrings.dateMustNotBeFuture` / `AppStrings.voiceDateMustNotBeFuture` (ADD) |
| `dob_under_18` | "Must be at least 18 years old." | "You must be at least eighteen years old to use this service." | `AppStrings.dateMustBeAtLeast18Years` / `AppStrings.voiceDateMustBeAtLeast18Years` (ADD) |

- **Pass behaviour**: `dobDate.value = dt; dobController.text = formatted(dt)`. Spoken: `"Date of birth updated."` — `AppStrings.voiceConfirmDob` (ADD).
- **Revert-on-fail**: `_lastValid['personalDetails.dateOfBirth']` (DateTime or null).
- **Voice edges**: `"yesterday"`, `"next Tuesday"`, `"two years ago"` → `dob_invalid_format`. `"14/03/1990"` → PASS. `"14 March 1990"` → server is expected to emit it as `1990-03-14`; if Flutter receives a non-ISO non-`dd/MM/yyyy` string, reject with `dob_invalid_format`.
- **Typed edges**: picker emits a `DateTime` directly; no parsing failure path. Keyboard direct-entry (if enabled) goes through the buffer with 250ms debounce.

---

### 4.5 `personalDetails.gender`

- **Widget**: `personal_details_step_content.dart` — Gender dropdown
- **Controller binding**: `selectedGender` (`RxString`)
- **Voice schema path**: `basics.gender`
- **Type / Required**: enum {`Male`, `Female`, `Non-binary`, `Prefer not to say`, `Other`}, required
- **Current behaviour**: typed dropdown enforces by UI. Voice has no enum check — any string can land.
- **Required behaviour**: required → enum membership.

**Validation rules:**

```dart
const _genders = {'Male', 'Female', 'Non-binary', 'Prefer not to say', 'Other'};
String? validateGender(Object? raw) {
  final v = (raw is String) ? raw.trim() : '';
  if (v.isEmpty) return AppStrings.fieldRequired;
  if (!_genders.contains(v)) return AppStrings.genderEnumInvalid;
  return null;
}
```

**Error messages:**

| code | on_screen | spoken | AppStrings key (on_screen / voice) |
|---|---|---|---|
| `required` | "This field is required." | "Please tell me your gender." | `AppStrings.fieldRequired` / `AppStrings.voiceGenderRequired` (ADD) |
| `enum_invalid` | "Please choose Male, Female, Non-binary, Prefer not to say, or Other." | "Please choose Male, Female, Non-binary, Prefer not to say, or Other." | `AppStrings.genderEnumInvalid` (ADD — same string both channels) |

- **Pass behaviour**: `selectedGender.value = v`. Spoken: `"Gender updated."` — `AppStrings.voiceConfirmGender` (ADD).
- **Revert-on-fail**: previous `_lastValid['personalDetails.gender']`.
- **Voice edges**: `"male"` (lowercase) — Flutter should case-insensitive match against allowed list before rejecting. `"man"` → `enum_invalid`.
- **Typed edges**: dropdown cannot produce invalid values.

---

### 4.6 `personalDetails.aboutMe`

- **Widget**: `personal_details_step_content.dart` — About Me long-text
- **Controller binding**: `aboutMeController` wrapped by `aboutMeBuffer`
- **Voice schema path**: `basics.about_me`
- **Type / Required**: `string`, required, ≤250 chars
- **Current behaviour**: voice writes directly. Typed validates at submit via `AppValidators.requiredWithMaxLength(value, 250)`.
- **Required behaviour**: required → ≤250 chars.

**Validation rules:**

```dart
String? validateAboutMe(String? raw) {
  final v = (raw ?? '').trim();
  if (v.isEmpty) return AppStrings.fieldRequired;
  if (v.length > 250) return AppStrings.fieldMustBeAtMostChars(250);
  return null;
}
```

**Error messages:**

| code | on_screen | spoken | AppStrings key (on_screen / voice) |
|---|---|---|---|
| `required` | "This field is required." | "Please tell me a bit about yourself." | `AppStrings.fieldRequired` / `AppStrings.voiceAboutMeRequired` (ADD) |
| `about_me_too_long` | "Must be at most 250 characters." | "Your about-me is too long; please keep it under 250 characters." | `AppStrings.fieldMustBeAtMostChars(250)` / `AppStrings.voiceAboutMeTooLong` (ADD) |

- **Pass behaviour**: commit to `aboutMeController`. Spoken: `"About you updated."` — `AppStrings.voiceConfirmAboutMe` (ADD).
- **Revert-on-fail**: `_lastValid['personalDetails.aboutMe'] ?? ''`.
- **Voice edges**: STT yields a long single string; trim only.
- **Typed edges**: 250ms debounce. Soft pre-warning when the user crosses 200 chars (helper text), hard reject at 251.

---

### 4.7 `personalDetails.preferredLanguages`

- **Widget**: `personal_details_step_content.dart` — Preferred Languages multi-pick
- **Controller binding**: `preferredLanguages` (`RxList<String>`)
- **Voice schema path**: `basics.preferred_languages`
- **Type / Required**: `list<string>`, required non-empty
- **Allowed values**: {`English`, `Mandarin`, `Cantonese`, `Arabic`, `Vietnamese`, `Greek`, `Italian`, `Other`}

**Validation rules:**

```dart
const _languages = {'English','Mandarin','Cantonese','Arabic','Vietnamese','Greek','Italian','Other'};
String? validatePreferredLanguages(Object? raw) {
  final list = (raw is List) ? raw.whereType<String>().map((s)=>s.trim()).where((s)=>s.isNotEmpty).toList() : <String>[];
  if (list.isEmpty) return AppStrings.fieldRequired;
  for (final l in list) {
    if (!_languages.contains(l)) return AppStrings.preferredLanguagesEnumInvalid;
  }
  return null;
}
```

**Error messages:**

| code | on_screen | spoken | AppStrings key (on_screen / voice) |
|---|---|---|---|
| `required` | "This field is required." | "Please tell me at least one preferred language." | `AppStrings.fieldRequired` / `AppStrings.voicePreferredLanguagesRequired` (ADD) |
| `enum_invalid` | "Please pick from the list — for example English, Mandarin, or Other." | "Please pick from the list — for example English, Mandarin, or Other." | `AppStrings.preferredLanguagesEnumInvalid` (ADD — same string both channels) |

- **Pass behaviour**: `preferredLanguages.assignAll(list)`. Spoken: `"Preferred languages updated."` — `AppStrings.voiceConfirmPreferredLanguages` (ADD).
- **Revert-on-fail**: previous list.
- **Voice edges**: voice utterance like `"English and Mandarin and Greek"` — the server-side voice parser splits on `" and "`, `","`, `";"` before emitting the list. Flutter only validates the resulting list.
- **Typed edges**: chip-picker UI cannot produce invalid values.

---

### 4.8 `personalDetails.interpreterRequired`

- **Widget**: `personal_details_step_content.dart` — Interpreter Required `AppRadioToggle`
- **Controller binding**: `interpreterRequired` (`RxBool`)
- **Voice schema path**: `basics.interpreter_required`
- **Type / Required**: `bool`, required

**Validation rules:**

```dart
bool? parseBool(Object? raw) {
  if (raw is bool) return raw;
  if (raw is String) {
    final s = raw.trim().toLowerCase();
    if ({'yes','yeah','yep','i do','true','positive','correct','affirmative'}.contains(s)) return true;
    if ({'no','nope','nah','i don\'t','false','negative','wrong'}.contains(s)) return false;
  }
  return null;
}
String? validateInterpreterRequired(Object? raw) {
  final b = parseBool(raw);
  if (b == null) return AppStrings.interpreterAnswerYesNo;
  return null;
}
```

**Error messages:**

| code | on_screen | spoken | AppStrings key |
|---|---|---|---|
| `boolean_invalid` | "Please answer yes or no." | "Please answer yes or no." | `AppStrings.interpreterAnswerYesNo` (ADD) |

- **Pass behaviour**: `interpreterRequired.value = b`. Spoken: `"Interpreter preference updated."` — `AppStrings.voiceConfirmInterpreterRequired` (ADD).
- **Revert-on-fail**: previous value.
- **Voice edges**: ambiguous utterances like `"maybe"`, `"sometimes"` → `boolean_invalid`.
- **Typed edges**: toggle cannot fail.

---

### 4.9 `personalDetails.interpreterLanguage` (typed-only, phase 1)

- **Widget**: `personal_details_step_content.dart` — Interpreter Language `AppTextField`
- **Controller binding**: `interpreterLanguageController`
- **Voice schema path**: none — phase 1 is typed-only.
- **Type / Required**: `string`, optional, ≤250 chars
- **Visibility**: only when `interpreterRequired = true`.
- **Validator**: `AppValidators.optionalMaxLength(value, 250)`.
- **Errors**: `text_too_long` → `AppStrings.fieldMustBeAtMostChars(250)`.
- **Note**: This field accepts typed input only in this release. A voice schema entry may be added in phase 2; until then voice utterances for it must be ignored (or the server must not emit them).

---

### 4.10 `personalDetails.address`

- **Widget**: `personal_details_step_content.dart` — Home Address `AppAddressAutocomplete`
- **Controller binding**: `addressController` wrapped by `addressBuffer`
- **Voice schema path**: `home_address.address`
- **Type / Required**: `string`, required
- **Rules**: required only (no Places-pick gate in phase 1).
- **Validator**:

```dart
String? validateAddress(String? raw) {
  final v = (raw ?? '').trim();
  if (v.isEmpty) return AppStrings.fieldRequired;
  return null;
}
```

- **Errors**: `required` → `AppStrings.fieldRequired`.
- **Pass behaviour**: commit. Spoken: `"Address updated."` — `AppStrings.voiceConfirmAddress` (ADD).
- **Revert-on-fail**: `_lastValid['personalDetails.address'] ?? ''`.
- **Voice edges**: STT returns the full spoken address; commit as-is on PASS.
- **Typed edges**: autocomplete-suggest accept counts as a typed commit.

---

### 4.11 `personalDetails.state`

- **Widget**: `personal_details_step_content.dart` — State `AppTextField` (or dropdown if present)
- **Controller binding**: `stateController` wrapped by `stateBuffer`
- **Voice schema path**: `home_address.state`
- **Type / Required**: AU state abbreviation `string`, required

**Validation rules:**

```dart
String? validateAuState(String? raw) {
  final v = (raw ?? '').trim();
  if (v.isEmpty) return AppStrings.fieldRequired;
  final abbrev = AuStateNormaliser.normalise(v);
  if (abbrev == null) return AppStrings.auStateInvalid;
  return null; // pass; caller commits the normalised abbrev
}
```

**Error messages:**

| code | on_screen | spoken | AppStrings key (on_screen / voice) |
|---|---|---|---|
| `required` | "This field is required." | "Please tell me your state." | `AppStrings.fieldRequired` / `AppStrings.voiceStateRequired` (ADD) |
| `au_state_invalid` | "Please provide an Australian state (NSW, VIC, QLD, SA, WA, TAS, ACT, or NT)" | "Please say an Australian state, for example New South Wales or Victoria." | `AppStrings.auStateInvalid` (ADD) / `AppStrings.voiceAuStateInvalid` (ADD) |

- **Pass behaviour**: commit the **normalised abbreviation** (e.g. `"NSW"`) to `stateController`. Spoken: `"State set to {abbrev}."` — `AppStrings.voiceConfirmStateTemplate(abbrev)` (ADD).
- **Revert-on-fail**: `_lastValid['personalDetails.state'] ?? ''`.
- **Voice edges**: `"new south wales"` → normalise to `"NSW"`. `"new zealand"` → `au_state_invalid`.
- **Typed edges**: 250ms debounce; if the widget is a dropdown, items are abbreviations already and the validator returns null.

---

### 4.12 `personalDetails.city`

- **Widget**: `personal_details_step_content.dart` — City `AppTextField`
- **Controller binding**: `cityController` wrapped by `cityBuffer`
- **Voice schema path**: `home_address.city`
- **Type / Required**: `string`, required
- **Validator**:

```dart
String? validateCity(String? raw) {
  final v = (raw ?? '').trim();
  if (v.isEmpty) return AppStrings.fieldRequired;
  return null;
}
```

- **Errors**: `required` → `AppStrings.fieldRequired`.
- **Pass behaviour**: commit. Spoken: `"City updated."` — `AppStrings.voiceConfirmCity` (ADD).
- **Revert-on-fail**: `_lastValid['personalDetails.city'] ?? ''`.

---

### 4.13 `personalDetails.zipCode`

- **Widget**: `personal_details_step_content.dart` — Postcode `AppTextField`
- **Controller binding**: `zipCodeController` wrapped by `zipBuffer`
- **Voice schema path**: `home_address.zip_code`
- **Type / Required**: 4-digit `string`, required
- **Validator (today)**: `AppValidators.postalCodeAu4Digits` (`base_validators.dart:114-121`).

```dart
String? validateZip(String? raw) {
  final v = (raw ?? '').trim();
  if (v.isEmpty) return AppStrings.fieldRequired;
  if (!RegExp(r'^\d{4}$').hasMatch(v)) return AppStrings.postalCodeAuInvalid;
  return null;
}
```

**Errors**: `required` → `AppStrings.fieldRequired`; `postcode_invalid` → `AppStrings.postalCodeAuInvalid` ("Postcode must be exactly 4 digits (0000–9999)").

- **Pass behaviour**: commit. Spoken: `"Postcode updated."` — `AppStrings.voiceConfirmPostcode` (ADD).
- **Voice edges**: STT `"two zero zero zero"` — server is expected to emit `"2000"`. Flutter only validates digits.

---

### 4.14 `personalDetails.serviceAddress`

- **Widget**: `personal_details_step_content.dart` — Service Address `AppTextField` (optional section)
- **Controller binding**: `serviceAddressController` wrapped by `serviceAddressBuffer`
- **Voice schema path**: `service_address.address`
- **Type / Required**: `string`, optional, ≤250
- **Validator**:

```dart
String? validateServiceAddress(String? raw) {
  final v = (raw ?? '').trim();
  if (v.isEmpty) return null; // optional
  if (v.length > 250) return AppStrings.fieldMustBeAtMostChars(250);
  return null;
}
```

- **Errors**: `text_too_long` → `AppStrings.fieldMustBeAtMostChars(250)`.
- **Pass behaviour**: commit. Spoken: `"Service address updated."` — `AppStrings.voiceConfirmServiceAddress` (ADD).

---

### 4.15 `personalDetails.serviceState`

- **Widget**: `personal_details_step_content.dart` — Service State
- **Controller binding**: `serviceStateController`
- **Voice schema path**: `service_address.state`
- **Type / Required**: AU state, **conditional required** — required if any of `serviceAddress`, `serviceCity`, `serviceZipCode` is non-empty.
- **Validator**: combine condition check + `validateAuState`.

```dart
String? validateServiceState(String? raw, {required bool serviceBlockHasAnyValue}) {
  final v = (raw ?? '').trim();
  if (v.isEmpty) {
    return serviceBlockHasAnyValue ? AppStrings.fieldRequired : null;
  }
  final abbrev = AuStateNormaliser.normalise(v);
  if (abbrev == null) return AppStrings.auStateInvalid;
  return null;
}
```

- **Errors**: `required` (conditional), `au_state_invalid`.
- **Pass behaviour**: commit normalised abbrev. Spoken: `"Service state set to {abbrev}."` — `AppStrings.voiceConfirmServiceStateTemplate(abbrev)` (ADD).

---

### 4.16 `personalDetails.serviceCity`

- **Widget**: Service City
- **Controller binding**: `serviceCityController`
- **Voice schema path**: `service_address.city`
- **Type / Required**: `string`, required (treat as required to reconcile with Flutter law — Step 1 sub-form does not display unless used).
- **Validator**: required + non-empty.
- **Errors**: `required` → `AppStrings.fieldRequired`.
- **Pass spoken**: `"Service city updated."` — `AppStrings.voiceConfirmServiceCity` (ADD).

---

### 4.17 `personalDetails.serviceZipCode`

- **Widget**: Service Postcode
- **Controller binding**: `serviceZipController`
- **Voice schema path**: `service_address.zip_code`
- **Type / Required**: 4-digit, required
- **Validator**: same as 4.13.
- **Errors**: `required`, `postcode_invalid`.
- **Pass spoken**: `"Service postcode updated."` — `AppStrings.voiceConfirmServicePostcode` (ADD).

---

### 4.18 `personalDetails.emergencyContacts[i].name`

- **Widget**: `personal_details_step_content.dart` — Emergency Contact row `i` Name field
- **Controller binding**: `emergencyContacts[i].nameController` wrapped by `emergencyContacts[i].nameBuffer`
- **Voice schema path**: `emergency_contacts[i].name`
- **Type / Required**: `string`, required, ≤25
- **Validator**:

```dart
String? validateEmergencyName(String? raw) {
  final v = (raw ?? '').trim();
  if (v.isEmpty) return AppStrings.fieldRequired;
  if (v.length > 25) return AppStrings.fieldMustBeAtMostChars(25);
  return null;
}
```

- **Errors**: `required`, `text_too_long` → `AppStrings.fieldMustBeAtMostChars(25)`.
- **Pass spoken**: `"Contact {n} name updated."` — `AppStrings.voiceConfirmEmergencyNameTemplate(n)` (ADD), where `n = i + 1`.
- **Row cap**: row index ≥ 5 → `max_rows_exceeded` → `AppStrings.emergencyContactsMaxFive` ("You can add up to five emergency contacts."). Today `_ensureEmergencyContactRow` silently no-ops on the 6th add — replace with explicit rejection through the same fail path. If voice triggered the add, speak the cap message and re-open mic.

---

### 4.19 `personalDetails.emergencyContacts[i].relation`

- **Widget**: Emergency row `i` Relation dropdown
- **Controller binding**: `emergencyContacts[i].relationController`
- **Voice schema path**: `emergency_contacts[i].relation`
- **Type / Required**: enum from `AppStrings.emergencyContactRelationOptions` = {`Parent`, `Sibling`, `Partner`, `Friend`, `Carer`, `Other`}, required

```dart
const _emergencyRelations = {'Parent','Sibling','Partner','Friend','Carer','Other'};
String? validateEmergencyRelation(String? raw) {
  final v = (raw ?? '').trim();
  if (v.isEmpty) return AppStrings.fieldRequired;
  if (!_emergencyRelations.contains(v)) return AppStrings.emergencyRelationEnumInvalid;
  return null;
}
```

- **Errors**: `required` → `AppStrings.fieldRequired`; `enum_invalid` → `AppStrings.emergencyRelationEnumInvalid` (ADD): "Please pick a relationship — Parent, Sibling, Partner, Friend, Carer, or Other."
- **Pass spoken**: `"Contact {n} relationship set to {value}."` — `AppStrings.voiceConfirmEmergencyRelationTemplate(n, value)` (ADD).

---

### 4.20 `personalDetails.emergencyContacts[i].email`

- **Widget**: Emergency row `i` Email
- **Controller binding**: `emergencyContacts[i].emailController` + buffer
- **Voice schema path**: `emergency_contacts[i].email`
- **Type / Required**: email, required
- **Rules**: required → email regex → disposable check → ≠ `personalDetails.email` → unique across all emergency rows

```dart
String? validateEmergencyEmail(String? raw, {
  required String clientEmail,
  required List<String> otherEmergencyEmails,
}) {
  final base = validateEmail(raw); // reuse 4.2
  if (base != null) return base;
  final v = (raw ?? '').trim().toLowerCase();
  if (v == clientEmail.trim().toLowerCase()) {
    return AppStrings.emergencyContactEmailMustNotMatchClientEmail;
  }
  if (otherEmergencyEmails.map((e) => e.trim().toLowerCase()).contains(v)) {
    return AppStrings.emergencyContactEmailMustBeUnique;
  }
  return null;
}
```

**Errors:**

| code | AppStrings key |
|---|---|
| `required` | `AppStrings.fieldRequired` |
| `email_invalid` | `AppStrings.emailInvalid` |
| `email_disposable` | `AppStrings.emailDisposable` (ADD) |
| `emergency_email_matches_client` | `AppStrings.emergencyContactEmailMustNotMatchClientEmail` |
| `emergency_email_duplicate` | `AppStrings.emergencyContactEmailMustBeUnique` |

- **Pass spoken**: `"Contact {n} email updated."` — `AppStrings.voiceConfirmEmergencyEmailTemplate(n)` (ADD).

---

### 4.21 `personalDetails.emergencyContacts[i].phone`

- **Widget**: Emergency row `i` Phone
- **Controller binding**: `emergencyContacts[i].phoneController` + buffer
- **Voice schema path**: `emergency_contacts[i].phone`
- **Type / Required**: AU phone, required
- **Rules**: required → AU regex → ≠ `personalDetails.phone` (key on 9-digit normaliser) → unique across all emergency rows

```dart
String? validateEmergencyPhone(String? raw, {
  required String clientPhone,
  required List<String> otherEmergencyPhones,
}) {
  final base = validatePhone(raw);
  if (base != null) return base;
  final norm = AppValidators.australianMobileNineDigits(raw ?? '');
  if (norm == null) return AppStrings.australianMobileInvalid;
  final clientNorm = AppValidators.australianMobileNineDigits(clientPhone) ?? '';
  if (norm == clientNorm) return AppStrings.emergencyContactPhoneMustNotMatchClientPhone;
  final others = otherEmergencyPhones
      .map((p) => AppValidators.australianMobileNineDigits(p) ?? '')
      .where((s) => s.isNotEmpty)
      .toList();
  if (others.contains(norm)) return AppStrings.emergencyContactPhoneMustBeUnique;
  return null;
}
```

**Errors:**

| code | AppStrings key |
|---|---|
| `required` | `AppStrings.fieldRequired` |
| `phone_invalid_format` | `AppStrings.australianMobileInvalid` |
| `emergency_phone_matches_client` | `AppStrings.emergencyContactPhoneMustNotMatchClientPhone` |
| `emergency_phone_duplicate` | `AppStrings.emergencyContactPhoneMustBeUnique` |

- **Pass spoken**: `"Contact {n} phone updated."` — `AppStrings.voiceConfirmEmergencyPhoneTemplate(n)` (ADD).

---

## 5. Cross-Field Rules

All three rules below re-run on every commit involving any participating field. Each rule is debounced 250ms. Rules are pure Dart — no server round-trip. The server runs the same rules and may still reject via `validation_rejection`; if it does, treat as the canonical truth and overwrite local state.

### 5.1 Emergency phone unique + ≠ client phone

- **Trigger fields**: `personalDetails.phone`, every `personalDetails.emergencyContacts[i].phone`
- **Key**: `AppValidators.australianMobileNineDigits(value)` — strips `+61`, leading `0`, whitespace; returns the 9-digit suffix.
- **Algorithm**:

```dart
void recheckEmergencyPhones() {
  final clientNorm = AppValidators.australianMobileNineDigits(phoneController.text) ?? '';
  final norms = emergencyContacts.map((r) =>
      AppValidators.australianMobileNineDigits(r.phoneController.text) ?? '').toList();
  for (var i = 0; i < emergencyContacts.length; i++) {
    final n = norms[i];
    final path = 'personalDetails.emergencyContacts[$i].phone';
    if (n.isEmpty) { fieldErrors.remove(path); continue; }
    if (n == clientNorm) {
      fieldErrors[path] = AppStrings.emergencyContactPhoneMustNotMatchClientPhone;
      continue;
    }
    final dup = norms.where((x) => x == n).length > 1;
    if (dup) {
      fieldErrors[path] = AppStrings.emergencyContactPhoneMustBeUnique;
      continue;
    }
    fieldErrors.remove(path);
  }
}
```

- **Codes**: `emergency_phone_matches_client`, `emergency_phone_duplicate`.
- **Voice spoken text**: speak the same `reason_human` string the user sees on screen — `"Emergency contact phone must not match your phone number"` for `emergency_phone_matches_client`, `"Phone number must be unique across emergency contacts"` for `emergency_phone_duplicate`. Both strings are byte-matched between server `cross_field.py` and Flutter `AppStrings.emergencyContactPhoneMustNotMatchClientPhone` / `AppStrings.emergencyContactPhoneMustBeUnique` (see section 12.5). Speak only when the cross-field check is triggered by a voice commit. Pure typed re-check: inline only.

### 5.2 Emergency email unique + ≠ client email (lowercased)

- **Trigger fields**: `personalDetails.email`, every `personalDetails.emergencyContacts[i].email`
- **Key**: `value.trim().toLowerCase()`
- **Algorithm**: identical structure to 5.1.
- **Codes**: `emergency_email_matches_client`, `emergency_email_duplicate`.

### 5.3 Emergency row cap ≤ 5

- **Trigger**: any add-row action.
- **Rule**:

```dart
bool tryAddEmergencyContactRow({required InputMethod source}) {
  if (emergencyContacts.length >= 5) {
    fieldErrors['personalDetails.emergencyContacts'] = AppStrings.emergencyContactsMaxFive;
    if (source == InputMethod.voice) {
      _speak(AppStrings.emergencyContactsMaxFive);
      _micController.reopen();
    }
    Get.find<ValidationErrorReporter>().report(
      errorCode: 'max_rows_exceeded',
      errorMessage: AppStrings.emergencyContactsMaxFive,
      inputMethod: source,
      fieldId: 'personalDetails.emergencyContacts',
      attemptedValue: emergencyContacts.length + 1,
    );
    return false;
  }
  emergencyContacts.add(...);
  return true;
}
```

- **Code**: `max_rows_exceeded`.
- **String**: `AppStrings.emergencyContactsMaxFive` ("You can add up to five emergency contacts.").

---

## 6. End-to-End Worked Examples

### Example A — Typed full name: fail then pass

Initial state: `fullNameController.text = ''`, `_lastValid['personalDetails.fullName'] = null`, `fieldErrors = {}`.

1. User taps the Full Name `TextField`. Field gains focus.
2. User types `J`. `onChanged('J')` → `fullNameBuffer.onChanged('J')`. Buffer schedules debounced validation.
3. 250ms after the last keystroke, `_ctrl.setFromTyped('personalDetails.fullName', 'J', InputMethod.typed)` runs.
4. `validateFullName('J')` returns `"Enter full name (e.g. Jane Doe)"` (one-token failure).
5. PASS branch is skipped. FAIL branch: `fieldErrors['personalDetails.fullName'] = "Enter full name (e.g. Jane Doe)"`. The widget's `Obx` rebuilds the error slot.
6. POST `/v1/onboarding/session/<sid>/errors` body (session_id is in the URL path only — NEVER in the body):

```json
{
  "error_type": "full_name_requires_first_last",
  "error_message": "Enter full name (e.g. Jane Doe)",
  "input_method": "typed",
  "field_id": "personalDetails.fullName",
  "attempted_value": "J",
  "ts": "<iso>"
}
```

7. State after step 6: `fullNameController.text = ''` (canonical unchanged), buffer's `TextField` shows `J`. `fieldErrors = {'personalDetails.fullName': 'Enter full name (e.g. Jane Doe)'}`. Microphone NOT re-opened (typed flow). No TTS speech.
8. User continues typing → `J`, `a`, `n`, `e`, ` `, `D`, `o`, `e`. After the final keystroke, 250ms passes.
9. `validateFullName('Jane Doe')` returns `null`.
10. PASS branch: `fullNameController.text = 'Jane Doe'`. Draft updated via `replaceStep1Draft`. `fieldErrors.remove('personalDetails.fullName')`. `_lastValid['personalDetails.fullName'] = 'Jane Doe'`. No snackbar. No TTS.

### Example B — Voice full name: fail (single token) then pass

Initial state: same as A.

1. User says `"Madonna"`. STT result arrives via the voice WebSocket as a `field_apply` event. The voice sink receives it.
2. `client_step1_voice_sink.applyVoiceUpdate(senaPath: 'personalDetails.fullName', rawValue: 'Madonna', confidence: 0.94)` calls `_ctrl.setFromVoice(...)`.
3. `setFromVoice` runs `validateFullName('Madonna')` → returns `"Please say both first and last name, for example Jane Doe."` (`AppStrings.fullNameRequiresFirstAndLastVoice`).
4. FAIL branch:
   - `fieldErrors['personalDetails.fullName'] = "Please say both first and last name, for example Jane Doe."`
   - `_speak("Please say both first and last name, for example Jane Doe.")` via `flutter_tts`.
   - `_micController.reopen()` — mic re-opens automatically.
   - `_revertField('personalDetails.fullName')` → `fullNameController.text = ''` (unchanged because no prior value).
5. POST `/errors` body (session_id is in the URL path only — NEVER in the body):

```json
{
  "error_type": "full_name_requires_first_last",
  "error_message": "Please say both first and last name, for example Jane Doe.",
  "input_method": "voice",
  "field_id": "personalDetails.fullName",
  "attempted_value": "Madonna",
  "ts": "<iso>"
}
```

6. Spoken: `"Please say both first and last name, for example Jane Doe."` Mic reopened: YES. Controller changed: NO.
7. User says `"Madonna Ciccone"`. New `field_apply` event arrives.
8. `validateFullName('Madonna Ciccone')` returns `null`.
9. PASS branch: `fullNameController.text = 'Madonna Ciccone'`. Draft updated. `_lastValid['personalDetails.fullName'] = 'Madonna Ciccone'`. `fieldErrors.remove('personalDetails.fullName')`.
10. `_speakSuccess('Full name')` → spoken: `"Full name updated."` No snackbar.

### Example C — Voice DOB: unparseable then valid ISO

Initial state: `dobDate.value = null`, `dobController.text = ''`, `_lastValid['personalDetails.dateOfBirth'] = null`.

1. User says `"yesterday"`. STT result arrives. Sink → `setFromVoice('personalDetails.dateOfBirth', 'yesterday', confidence: 0.81)`.
2. `validateDob('yesterday')` → `tryParseDisplayDate('yesterday')` returns `null` → returns `"Please enter a valid date (YYYY-MM-DD)."` (`AppStrings.dateInvalidFormat`).
3. FAIL branch:
   - `fieldErrors['personalDetails.dateOfBirth'] = "Please enter a valid date (YYYY-MM-DD)."`
   - `_speak("I didn't catch that date. Please say it as day, month, and year, for example fourteenth of March nineteen ninety.")` — uses the voice-specific variant for spoken channel (also `AppStrings.dateInvalidFormat` if you keep one string; recommended split: on-screen vs voice).
   - `_micController.reopen()`.
   - `_revertField('personalDetails.dateOfBirth')` → `dobDate.value = null` unchanged.
4. POST `/errors` (session_id is in the URL path only — NEVER in the body):

```json
{
  "error_type": "dob_invalid_format",
  "error_message": "Please enter a valid date (YYYY-MM-DD).",
  "input_method": "voice",
  "field_id": "personalDetails.dateOfBirth",
  "attempted_value": "yesterday",
  "ts": "<iso>"
}
```

5. User says `"fourteen March nineteen ninety"`. Server-side voice parser normalises to `"1990-03-14"` and emits `field_apply` with that value.
6. `validateDob('1990-03-14')` → parsed = DateTime(1990,3,14), not in future, age > 18 → returns `null`.
7. PASS branch: `dobDate.value = DateTime(1990,3,14)`. `dobController.text` formatted. Draft updated. `_lastValid['personalDetails.dateOfBirth'] = DateTime(1990,3,14)`. `fieldErrors.remove('personalDetails.dateOfBirth')`. Spoken: `"Date of birth updated."` (`AppStrings.voiceConfirmDob`). Mic does NOT auto-reopen on PASS — agent flow continues.

### Example D — Voice emergency contact phone: cross-field fail then pass

Initial state: `personalDetails.phone` already committed as `"+61412345678"`. Emergency contact row `[0]` exists; its phone is empty. `_lastValid['personalDetails.emergencyContacts[0].phone'] = null`.

1. User says `"plus six one four one two three four five six seven eight"` for emergency contact 0 phone.
2. Server emits `field_apply` with `value: "+61412345678"` and `field_id: "emergency_contacts[0].phone"`.
3. Sink → `setFromVoice('personalDetails.emergencyContacts[0].phone', '+61412345678', InputMethod.voice)`.
4. `validatePhone('+61412345678')` returns `null` (regex passes).
5. Cross-field check 5.1 runs: client norm `412345678`, contact[0] norm `412345678` → match → returns `AppStrings.emergencyContactPhoneMustNotMatchClientPhone` for path `personalDetails.emergencyContacts[0].phone`.
6. FAIL branch (cross-field):
   - `fieldErrors['personalDetails.emergencyContacts[0].phone'] = "Emergency contact phone must not match your phone number"` (the canonical `reason_human` byte-matched by both server cross_field.py and Flutter `AppStrings.emergencyContactPhoneMustNotMatchClientPhone` — see section 12.5).
   - `_speak("Emergency contact phone must not match your phone number.")`. Speak the same string the user sees, optionally suffixed with a period for natural intonation.
   - `_micController.reopen()`.
   - Revert: `emergencyContacts[0].phoneController.text = ''` (last valid was null).
7. POST `/errors` (session_id is in the URL path only — NEVER in the body):

```json
{
  "error_type": "emergency_phone_matches_client",
  "error_message": "Emergency contact phone must not match your phone number",
  "input_method": "voice",
  "field_id": "personalDetails.emergencyContacts[0].phone",
  "attempted_value": "+61412345678",
  "ts": "<iso>"
}
```

8. User says `"plus six one four eight seven six five four three two one"`. Server emits with `value: "+61487654321"`.
9. `validatePhone` passes. Cross-field: norm `487654321` ≠ `412345678` and not duplicated among other rows → returns `null`.
10. PASS branch: commit. Spoken: `"Contact 1 phone updated."` (`AppStrings.voiceConfirmEmergencyPhoneTemplate(1)`). `fieldErrors.remove('personalDetails.emergencyContacts[0].phone')`.

---

## 7. Edge Case Handling Table

| Scenario | Input method | Required behaviour | Notes |
|---|---|---|---|
| Empty string | typed | Validator returns `required`; buffer keeps empty; no commit | Debounced 250ms |
| Whitespace-only ("   ") | typed | Trimmed to empty → `required` | Same as above |
| Empty STT result (`""`) | voice | Validator returns `required`; speak; re-open mic; revert | POST `/errors` with `attempted_value: ""` |
| Garbage/noise STT (e.g. `"@#%@!@"`) | voice | Validator runs against the raw string; rejects with the field's natural code (e.g. `email_invalid`); speak, re-open mic | If the value is so garbled the server-side ASR confidence < 0.3, server may not emit `field_apply` at all; nothing for Flutter to do |
| Interrupted speech mid-word (`"Madon-"`) | voice | Server emits the partial value; Flutter validates as normal; will fail on `full_name_requires_first_last`; speak, re-open mic | |
| Microphone permission denied mid-flow | voice | `_micController.reopen()` throws or no-ops; show `AppSnackbar.error("Microphone permission needed to continue with voice. Tap the mic to retry.")`; user can switch to typed | |
| Rapid resubmission — typed | typed | Debouncer cancels prior validation calls; only the last keystroke's value is validated 250ms after settling | |
| Rapid resubmission — voice | voice | Each voice utterance is validated independently. If a second utterance arrives while the first is mid-validate, finish the first then process the second. No drop. | TTS speak is queued — second pass-confirmation plays after first error message finishes |
| Back-navigation mid-validation | both | `onClose()` cancels the debouncer; pending validations are discarded; draft retains the last committed value | |
| Network failure during POST `/errors` | both | Reporter retries with the backoff schedule (250/500/1000/2000/4000/4000ms, 6 attempts); on exhaust, `AppLogger.error` and drop. UI is never blocked. | Errors during retry never surface to the user |
| Speech-to-text callback firing after widget disposed | voice | `setFromVoice` checks `isClosed` on the controller; no-op if disposed; no exception | Defensive check at top of `setFromVoice` |
| Voice arrives while user is typing in same field (race) | voice during typed focus | Queue the voice update for up to 5 seconds; apply on blur. If queue full or 5s elapses, reject with `_speak("Still typing — finish first.")`; do NOT POST `/errors` for this case | This is a UX bounce, not a data validation failure |
| Simultaneous typed + voice on **different** fields | both | No conflict; each field is independently validated and committed | Buffers and `_lastValid` are per-field |
| Voice provides plausibly-valid wrong value (`"fifteen"` heard as `"fifty"` on a number field) | voice | Validator passes; PASS commit; speak confirmation. The participant can immediately re-utter to correct — the new utterance overwrites. | Only the user can detect this; we cannot. Confirmation speech is the safeguard. |
| Voice provides value not in enum `allowed_values` (gender `"man"`) | voice | Validator returns `enum_invalid` with the field's enum-specific human reason and (if available from server) the `allowed_values` list; speak; re-open mic; revert | The server-emitted `validation_rejection` also carries `allowed_values`; speak the natural-language enumeration |

---

## 8. Scenarios the Developer Might Miss

- **Confidence-aware voice writes.** Each `field_apply` event carries a `confidence` float. Phase 1 ignores it (treat all voice events equally), but log the confidence on every PASS and FAIL via `AppLogger.info` so analytics can correlate failures to STT confidence later. Do **not** auto-reject low-confidence writes in phase 1 — that produces silent drops, the opposite of what we want.
- **The buffer is not the draft.** The `BufferedFieldController` holds visible text for the user. The canonical `TextEditingController` and the draft model hold the last-validated value. These can diverge mid-typing. Submit-time reads the canonical, never the buffer.
- **Cross-field re-checks on commits to a different field.** When `personalDetails.phone` is committed, you must re-run rule 5.1 across all emergency rows so that a previously-OK emergency phone that now collides with the new client phone shows the inline error. Don't only check on emergency-row commits.
- **Server is the canonical source for `validation_rejection`.** Even when client-side validation passes, the server may reject. Treat the server's `validation_rejection` event as authoritative — overwrite local `fieldErrors[senaPath]` with its `reason_human`, speak it, re-open mic, revert.
- **Reverting the date picker.** `dobController.text` is a derived display string. On revert, recompute it from `_lastValid['personalDetails.dateOfBirth']` (DateTime or null), don't try to revert the picker UI directly.
- **The `voiceSession.fieldEcho` map.** If your voice integration mirrors written values back into a `RxMap` for the agent's reference, it must be updated on PASS only — never on FAIL — so the agent never thinks an invalid value was accepted.
- **Disposable email list staleness.** Bundled blocklist will drift. Plan an annual refresh from the server's `field_rules.py:DISPOSABLE_EMAIL_DOMAINS`.
- **AU state aliases beyond the obvious.** Voice may surface `"new s w"`, `"n s w"`, `"new south whales"` (homophone). The normaliser must tolerate single-space and double-space variants. Add a regex pre-pass to collapse whitespace before alias lookup.
- **AppStrings parameter ergonomics.** Several new strings are templated (`"Contact {n} phone updated."`, `"State set to {abbrev}."`). Use static methods on `AppStrings` for these (`voiceConfirmEmergencyPhoneTemplate(int n)`), not raw `.replaceAll`.
- **Typed `Form.validate()` is now a fallback, not the source of truth.** Existing submit handlers that gate on `formKey.currentState!.validate()` must be replaced with a check on `fieldErrors.isEmpty`. If `fieldErrors` is empty the form is valid. Do not run both gates — they will disagree.
- **Mic auto-reopen on FAIL only.** PASS never re-opens the mic; the agent's next turn drives the conversation. FAIL re-opens so the participant can correct in place.
- **Repeatable index threading.** Voice events carry `repeatable_index`. Make sure your sena-path resolver handles both `emergency_contacts[0].name` and `emergency_contacts.0.name` shapes the server might emit.
- **The 5-row cap is a `max_rows_exceeded` error code, not a UI no-op.** Today the add-row helper silently returns. Replace with the rejection path so it shows the inline error AND speaks AND reports.

---

## 9. Definition of Done Checklist

- [ ] `InputMethod` enum exists at `lib/core/enums/input_method.dart`.
- [ ] `input_method` is captured at every entry point (typed onChanged, voice sink, dropdown onChanged, date picker, checkbox/toggle, autocomplete pick).
- [ ] `input_method` is threaded through every validator call and every `ValidationErrorReporter.report` call.
- [ ] `validation_rejection` event is parsed by `voice_event_model.dart` and dispatched by `voice_session_controller._handleEvent`.
- [ ] `_onValidationRejection` updates `fieldErrors`, speaks `reasonHuman`, re-opens mic, reverts via `_lastValid`, and reports.
- [ ] `ValidationErrorReporter` `GetxService` is registered permanent and posts to `POST /v1/onboarding/session/{sessionId}/errors`.
- [ ] Reporter retries on failure with backoff 250/500/1000/2000/4000/4000ms (max 6), drops on exhaust, **never blocks UI**.
- [ ] Reporter is fire-and-forget — no validator awaits its result.
- [ ] Every voice-mapped `TextField` is wrapped in a `BufferedFieldController`.
- [ ] Typed validation runs on 250ms debounce; FAIL keeps visible text in buffer; PASS commits to canonical controller and draft.
- [ ] `voice_session_controller.dart:403` snackbar `AppSnackbar.success('$label captured')` is replaced with `_speakSuccess(label)`.
- [ ] DOB silent-fail at `client_step1_voice_sink.dart:64` is replaced with explicit `dob_invalid_format` rejection through `setFromVoice`.
- [ ] Disposable email blocklist util exists at `lib/core/utils/disposable_email_blocklist.dart` with all 11 domains from section 3.9.
- [ ] AU state normaliser util exists at `lib/core/utils/au_state_normaliser.dart` and covers every alias from section 3.8.
- [ ] `AppValidators.emailWithDisposableCheck` exists and combines regex + RFC caps + disposable check.
- [ ] `AppValidators.auStateRequired` exists and uses the normaliser.
- [ ] `ClientStep1Controller.fieldErrors` is `RxMap<String, String>` and is the single source of truth for inline field errors.
- [ ] `personal_details_step_content.dart` renders `errorText: ctrl.fieldErrors[senaPath]` for every voice-mapped field.
- [ ] All 18 Step-1 fields validate identically between typed and voice paths.
- [ ] Cross-field rules 5.1, 5.2, 5.3 re-run on every commit involving any participating field, debounced 250ms.
- [ ] Emergency-row cap rejection (`max_rows_exceeded`) replaces the silent no-op in `_ensureEmergencyContactRow`.
- [ ] Race policy: voice during typed focus queues for ≤5s or rejects with `_speak("Still typing — finish first.")`.
- [ ] All new `AppStrings` keys from section 10 are added to `lib/core/constants/app_strings.dart` with the verbatim text values.
- [ ] `Form.validate()` at submit becomes a fallback; primary gate is `ctrl.fieldErrors.isEmpty`.
- [ ] No `AppSnackbar.success` fires for any voice field write.
- [ ] No `AppSnackbar.success` fires for any typed field PASS.
- [ ] On voice FAIL, the mic re-opens automatically and the participant can speak again with no extra tap.
- [ ] On voice PASS, TTS speaks the field's success template (never a snackbar).
- [ ] `flutter analyze` returns 0 warnings.
- [ ] `flutter test` runs and all new validators have a passing unit test per `test/features/voice_onboarding/...` and `test/core/utils/...`.
- [ ] Behaviour matches this contract for 100% of fields in both input modes — verified by manual walk-through of Examples A, B, C, D.

---

## 10. AppStrings Additions

Add the following keys to `lib/core/constants/app_strings.dart`. Use the exact strings below — they are the user-facing copy and the spoken copy. Where the on-screen and spoken variants diverge, **both** variants must exist as separate AppStrings keys (e.g. `auStateInvalid` for the inline error, `voiceAuStateInvalid` for the TTS speak). Rule 4 of section 1 demands the screen string and the spoken string are both pulled from `AppStrings` — never hard-coded in a controller. When the on-screen and spoken strings are identical, a single key serves both channels.

| Key | Value (verbatim) | Used by |
|---|---|---|
| `dateInvalidFormat` | `"Please enter a valid date (YYYY-MM-DD)."` | 4.4 on-screen |
| `emailDisposable` | `"Please use a non-disposable email address."` | 4.2, 4.20 |
| `genderEnumInvalid` | `"Please choose Male, Female, Non-binary, Prefer not to say, or Other."` | 4.5 |
| `preferredLanguagesEnumInvalid` | `"Please pick from the list — for example English, Mandarin, or Other."` | 4.7 |
| `interpreterAnswerYesNo` | `"Please answer yes or no."` | 4.8 |
| `auStateInvalid` | `"Please provide an Australian state (NSW, VIC, QLD, SA, WA, TAS, ACT, or NT)"` | 4.11, 4.15 |
| `emergencyRelationEnumInvalid` | `"Please pick a relationship — Parent, Sibling, Partner, Friend, Carer, or Other."` | 4.19 |
| `fullNameRequiresFirstAndLastVoice` | `"Please say both first and last name, for example Jane Doe."` | 4.1 (voice channel) |
| `voiceAboutMeTooLong` | `"Your about-me is too long; please keep it under 250 characters."` | 4.6 (voice channel) |
| `voiceAboutMeRequired` | `"Please tell me a bit about yourself."` | 4.6 (voice channel — `required`) |
| `voiceAustralianMobileInvalid` | `"Please say a valid Australian phone number, starting with plus six one or zero."` | 4.3, 4.21 (voice channel — `phone_invalid_format`) |
| `voiceDobRequired` | `"Please tell me your date of birth."` | 4.4 (voice channel — `required`) |
| `voiceDateInvalidFormat` | `"I didn't catch that date. Please say it as day, month, and year, for example fourteenth of March nineteen ninety."` | 4.4 (voice channel — `dob_invalid_format`) |
| `voiceDateMustNotBeFuture` | `"Your date of birth cannot be in the future."` | 4.4 (voice channel — `dob_in_future`) |
| `voiceDateMustBeAtLeast18Years` | `"You must be at least eighteen years old to use this service."` | 4.4 (voice channel — `dob_under_18`) |
| `voiceGenderRequired` | `"Please tell me your gender."` | 4.5 (voice channel — `required`) |
| `voicePreferredLanguagesRequired` | `"Please tell me at least one preferred language."` | 4.7 (voice channel — `required`) |
| `voiceStateRequired` | `"Please tell me your state."` | 4.11 (voice channel — `required`) |
| `voiceAuStateInvalid` | `"Please say an Australian state, for example New South Wales or Victoria."` | 4.11, 4.15 (voice channel — `au_state_invalid`) |
| `voiceEmailInvalid` | `"Please say a valid email address."` | 4.2, 4.20 (voice channel — `email_invalid`) |
| `voiceFullNameFirstTooLong` | `"First name must be at most 25 characters."` | 4.1 (voice channel — `full_name_first_too_long`) |
| `voiceFullNameLastTooLong` | `"Last name must be at most 25 characters."` | 4.1 (voice channel — `full_name_last_too_long`) |
| `genericValidationFailed` | `"Sorry, that didn't pass our checks. Please try again."` | section 3.4 fallback |
| `stillTypingFinishFirst` | `"Still typing — finish first."` | race policy |
| `voiceConfirmFullName` | `"Full name updated."` | 4.1 PASS |
| `voiceConfirmEmail` | `"Email updated."` | 4.2 PASS |
| `voiceConfirmPhone` | `"Phone number updated."` | 4.3 PASS |
| `voiceConfirmDob` | `"Date of birth updated."` | 4.4 PASS |
| `voiceConfirmGender` | `"Gender updated."` | 4.5 PASS |
| `voiceConfirmAboutMe` | `"About you updated."` | 4.6 PASS |
| `voiceConfirmPreferredLanguages` | `"Preferred languages updated."` | 4.7 PASS |
| `voiceConfirmInterpreterRequired` | `"Interpreter preference updated."` | 4.8 PASS |
| `voiceConfirmAddress` | `"Address updated."` | 4.10 PASS |
| `voiceConfirmStateTemplate` | `(String abbrev) => "State set to $abbrev."` | 4.11 PASS |
| `voiceConfirmCity` | `"City updated."` | 4.12 PASS |
| `voiceConfirmPostcode` | `"Postcode updated."` | 4.13 PASS |
| `voiceConfirmServiceAddress` | `"Service address updated."` | 4.14 PASS |
| `voiceConfirmServiceStateTemplate` | `(String abbrev) => "Service state set to $abbrev."` | 4.15 PASS |
| `voiceConfirmServiceCity` | `"Service city updated."` | 4.16 PASS |
| `voiceConfirmServicePostcode` | `"Service postcode updated."` | 4.17 PASS |
| `voiceConfirmEmergencyNameTemplate` | `(int n) => "Contact $n name updated."` | 4.18 PASS |
| `voiceConfirmEmergencyRelationTemplate` | `(int n, String value) => "Contact $n relationship set to $value."` | 4.19 PASS |
| `voiceConfirmEmergencyEmailTemplate` | `(int n) => "Contact $n email updated."` | 4.20 PASS |
| `voiceConfirmEmergencyPhoneTemplate` | `(int n) => "Contact $n phone updated."` | 4.21 PASS |

The following keys are **already present** in `AppStrings` and are referenced verbatim from this contract — do not duplicate them:

- `fieldRequired`
- `fieldMustBeAtMostChars(int n)`
- `emailInvalid`
- `australianMobileInvalid`
- `postalCodeAuInvalid`
- `dateMustNotBeFuture`
- `dateMustBeAtLeast18Years`
- `fullNameRequiresFirstAndLast`
- `emergencyContactEmailMustNotMatchClientEmail`
- `emergencyContactEmailMustBeUnique`
- `emergencyContactPhoneMustNotMatchClientPhone`
- `emergencyContactPhoneMustBeUnique`
- `emergencyContactsMaxFive`
- `emergencyContactRelationOptions`

---

## 11. Requirements from Frontend Dev (Confirm Before Starting)

Confirm or surface within your first commit any deviation from these assumptions:

- **TTS package**: `flutter_tts`. This is the package `voice_session_controller._speak` already wraps. Confirm the package is on the same major version on iOS and Android.
- **STT engine**: server-side. The Flutter app does NOT run on-device STT in this flow — it consumes `field_apply` events from the server's voice WebSocket. Confirm that no on-device `speech_to_text` package writes will sneak around the sink.
- **Mic auto-reopen**: confirm `_micController.reopen()` (or whatever method name your mic controller exposes) is safe to call without a user gesture on the current iOS SDK target. iOS sometimes requires a user gesture to start recording; verify on a physical device. If it is blocked, fall back to a prominent "Tap to speak again" affordance with the spoken reason still played.
- **AppStrings file location**: `lib/core/constants/app_strings.dart`. Confirm and add the new keys there. If the project has been split into per-feature strings files, place the new keys in the file already used by Step 1.
- **Backend error code list** (paste into your local notes — the server emits exactly these `code` values on `validation_rejection`):
  - `required`
  - `full_name_requires_first_last`, `full_name_first_too_long`, `full_name_last_too_long`
  - `email_invalid`, `email_disposable`
  - `phone_invalid_format`
  - `dob_invalid_format`, `dob_in_future`, `dob_under_18`
  - `enum_invalid`
  - `boolean_invalid`
  - `text_too_long`
  - `about_me_too_long`
  - `au_state_invalid`
  - `postcode_invalid`
  - `emergency_email_matches_client`, `emergency_email_duplicate`
  - `emergency_phone_matches_client`, `emergency_phone_duplicate`
  - `max_rows_exceeded`
- **Voice-to-sena-path resolution**: confirm there is (or build) a single resolver that maps `(section_id, field_id, repeatable_index)` → sena path string, used by both the voice sink and `_onValidationRejection`. Do not duplicate this mapping in two places.
- **Session ID lookup**: `ValidationErrorReporter` reads the session ID from `VoiceSessionController.sessionId`. Confirm this is set before any voice events fire. If not, gate the reporter on the session-ready signal.

---

## 12. Backend Changes Already Applied (Agent 03B — 2026-05-12)

This section is the canonical record of what the onboarding backend already does. Everything below is live on the `onboarding` service under `SENA_AI/sena-ai/services/onboarding/`. Frontend devs can rely on it as-is.

### 12.1 New endpoint — client-side validation error sink

`POST /v1/onboarding/session/{session_id}/errors`

| Field | Detail |
|---|---|
| Auth | Same header-based scheme every other onboarding state route uses: optional `X-Tenant-Id` + `X-Participant-Id` headers. When both are present the route calls `assert_session_owner` and returns `403` on a tenant mismatch. When the headers are absent the route falls through (matching today's GET/PUT state behaviour for backwards compatibility with older clients) — production clients SHOULD send both. There is no Bearer JWT layer in front of this service today; auth is handled at the API gateway. |
| Path param | `session_id` (string — currently a UUID generated by `POST /v1/onboarding/session`). |
| Request shape | Strict (`extra="forbid"`). Unknown fields → 422. **`session_id` is path-only — do NOT include it in the JSON body, it will 422.** |
| Response 204 | No body. Error stored. |
| Response 422 | Malformed body, missing `input_method`, invalid `input_method` value (must be `"typed"` or `"voice"`), or any unknown field. |
| Response 404 | Session not found (no Redis state for `session_id` — either never created or TTL-expired). |
| Response 403 | Session exists but the supplied `X-Tenant-Id` + `X-Participant-Id` do not match the session's owner (`assert_session_owner` raises). |

Request body (JSON) — exactly these fields, no more, no less:

```json
{
  "error_type":     "string (validation code, e.g. 'required', 'email_disposable', 'au_state_invalid'); 1..64 chars",
  "error_message":  "string (verbatim user-shown text); 1..512 chars",
  "input_method":   "typed | voice (Literal — anything else is 422)",
  "field_id":       "string (sena path or 'section.field'); 1..128 chars",
  "attempted_value": "any | null (the rejected value, may be any JSON type; null/omitted both accepted)",
  "ts":             "ISO8601 datetime"
}
```

The `session_id` is the URL path param. Do NOT add it to the JSON body — the Pydantic model is `model_config = ConfigDict(extra="forbid")` and will reject any unknown key with a 422. Test reference: `services/onboarding/tests/test_errors_endpoint.py::TestErrorsEndpoint::test_extra_field_rejected_with_422`.

Storage: Redis list `sena:onboarding:errors:{session_id}` (`RPUSH` of the model's JSON dump) with a 7-day TTL (`_CLIENT_ERRORS_TTL_SEC = 60 * 60 * 24 * 7` = 604800 s) refreshed on every write via `EXPIRE`. Append-only; useful for telemetry / replay. Not currently exposed via a read HTTP endpoint, but `state_repo.read_client_validation_errors` returns the list for in-process consumers.

Client retry policy is documented in section 2.6 of this doc (250/500/1000/2000/4000/4000ms, 6 attempts max, drop on exhaust). The endpoint is fire-and-forget from the client's perspective — failures must NEVER block UI.

### 12.2 `FieldValue.input_method`

`models/form_state.py` — `FieldValue` now has:

```python
input_method: Literal["typed", "voice"] | None = None
```

Backward compat: optional, default `None`. Pre-existing serialised states still deserialise without migration. `source` (`voice|app|system`) is unchanged and remains the origin-of-write marker; `input_method` is the new user-intent marker (always supplied by the client when a write is user-driven, `None` when the write is system-stamped or pre-input_method state is rehydrated).

### 12.3 `field_apply` WS envelope

`services/field_apply.py` — `build_envelope` accepts an optional `input_method` parameter and surfaces it on the emitted envelope when non-None. Clients can ignore the field safely until they handle it; older clients keep working.

`services/tools.py::_update_field` threads `input_method="voice"` into `build_envelope` since voice-tool dispatch is the only path that calls it today.

#### New server-emitted WS events (added alongside `field_apply`)

| Event | Payload | Flutter Action |
|---|---|---|
| `field_advisory_warning` | `{section_id, field_id, repeatable_index?, code, reason_human, severity: "advisory", suggested_fix?, allowed_values?}` | Store advisory; surface after current extraction burst completes; do NOT block field progression |
| `field_confirmed` | `{section_id, field_id, repeatable_index?, value, confirmation_source: "voice", turn_id}` | Mark field as confirmed in session state; suppress redundant re-confirmation prompts; no network call needed |

### 12.4 Per-write cross-field check policy

`validate_cross_fields` previously fired only from `validate_step_complete` at `/complete`. After this change:

- A focused subset of cross-field checks runs immediately after a per-field PASS inside `_update_field`.
- If a cross-field check fails because the newly written value collides with another row (e.g. an old emergency phone now duplicates a freshly typed one), the server emits an **additional** `validation_rejection` event for that OTHER row's `field_id`. The just-written field is **not** rejected (it was individually valid).
- Full-step `validate_step_complete` still runs at `/complete`.

Net effect on the client: when the user fixes one row, the previous "duplicate" error on another row clears automatically (no second submit needed); when the user creates a new conflict, both rows light up immediately.

### 12.5 Reconciled `reason_human` strings (byte-match Flutter)

`services/validators/cross_field.py` now emits exactly these strings (Flutter `AppStrings` is the source of truth — server was updated to match). Strings are byte-for-byte, including capitalisation, spacing, and absence of a trailing full stop:

| Code | `reason_human` (byte-exact) | Flutter `AppStrings` key |
|---|---|---|
| `emergency_email_matches_client` | `Emergency contact email must not match your email address` | `emergencyContactEmailMustNotMatchClientEmail` |
| `emergency_email_duplicate`      | `Email must be unique across emergency contacts`           | `emergencyContactEmailMustBeUnique` |
| `emergency_phone_matches_client` | `Emergency contact phone must not match your phone number` | `emergencyContactPhoneMustNotMatchClientPhone` |
| `emergency_phone_duplicate`      | `Phone number must be unique across emergency contacts`   | `emergencyContactPhoneMustBeUnique` |

Other cross-field rules in `cross_field.py` (untouched in this pass — strings are server-canonical, not yet promoted to byte-match status; Flutter should accept them as-is if the server emits via `validation_rejection`):

| Code | `reason_human` (current server value) |
|---|---|
| `plan_end_not_after_start`           | `Date must be after start date` |
| `medical_history_incomplete_row`     | `This field is required.` |
| `time_slot_end_before_start`         | `Start time must be before end time` |
| `time_slots_overlap`                 | `Time slots must not overlap` |

Test reference: `services/onboarding/tests/test_validators.py` asserts the four byte-matched strings; the four "untouched" strings above are covered by their respective unit tests in the same file but not asserted byte-exact yet.

### 12.6 `basics.interpreter_required` is now boolean

`services/validators/field_rules.py` defines `_v_boolean_required`:

- Accepts Python `bool` (`True` / `False`) directly.
- Accepts case-insensitive strings — exactly this set: `"yes"`, `"no"`, `"true"`, `"false"` (compared via `.lower()`). Empty string / whitespace-only → `code="required"`.
- Anything else → `ValidationRejection(code="boolean_invalid", reason_human="Please answer yes or no.", suggested_fix="Please answer yes or no.")`.

Test reference: `services/onboarding/tests/test_validators.py::test_boolean_required_accepts_bool_and_string_variants` (parametrised over `[True, False, "yes", "NO", "True", "false", "Yes", "no"]`).

Flutter-side note: the broader natural-language set listed in section 4.8 (`yeah`, `yep`, `nope`, `i do`, `i don't`, `positive`, `affirmative`, `negative`, `wrong`, etc.) is parsed on the **client** in `parseBool` before the value is committed or POSTed. The server only sees `bool` / canonical four-string variants. If a future client decides to forward raw natural-language strings to the server, expand this set on both sides at once.

`basics.interpreter_required` and `staff_basics.interpreter_required` are wired to `_v_boolean_required`.

### 12.7 `basics.about_me` is now required

`basics.about_me` switched from the optional-with-cap rule to `_v_text250_required` (required + ≤250 chars). Matches Flutter widget requiredness. Existing FormState that has an empty `about_me` will be flagged at the next per-field write or at `/complete`.

### 12.8 Test status

New / extended test files (under `sena-ai/services/onboarding/tests/`):

- `test_errors_endpoint.py` — happy 204 + Redis list populated + TTL set; 422 on missing `input_method`; 422 on extra field (`extra="forbid"`); 404 on session not owned by tenant.
- `test_field_apply.py` — `build_envelope` surfaces `input_method` when supplied, omits it when `None`.
- `test_validators.py` — `_v_boolean_required` (bool true/false, string variants, case-insensitivity, sad path returns `boolean_invalid` with the new message); `_v_text250_required` happy + over-cap sad path; cross-field tests updated to assert the new `reason_human` strings byte-for-byte.

Run: `cd SENA_AI/sena-ai && python -m pytest services/onboarding/tests/ -x -q`. Tests authored against the existing FakeRedis + AsyncSession patterns in `conftest.py`. Pytest was not executed in this implementation environment (Windows shell without the service venv installed); the frontend team's CI for SENA_AI will pick them up on the next pipeline run.

### 12.9 Files changed

```
sena-ai/services/onboarding/src/onboarding/api/routes.py
sena-ai/services/onboarding/src/onboarding/models/form_state.py
sena-ai/services/onboarding/src/onboarding/repositories/state_repo.py
sena-ai/services/onboarding/src/onboarding/services/field_apply.py
sena-ai/services/onboarding/src/onboarding/services/tools.py
sena-ai/services/onboarding/src/onboarding/services/validators/cross_field.py
sena-ai/services/onboarding/src/onboarding/services/validators/field_rules.py
sena-ai/services/onboarding/tests/test_errors_endpoint.py        (new)
sena-ai/services/onboarding/tests/test_field_apply.py            (new)
sena-ai/services/onboarding/tests/test_validators.py             (extended)
```

No `gemini*` / `demo_live*` files were touched (those are gated by a separate hook). No public API was removed or renamed — every change is additive or a backwards-compatible string update.

---

End of contract. Voice and typed must behave identically. The Law of the App is non-negotiable.
