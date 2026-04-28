# SENA Voice Onboarding — Architecture Q&A (Q5–Q18)

Answers informed by live backend implementation at `sena-ai/services/onboarding/`.
All backend references are current code, not speculation.

---

## Q5 — Pre-fill behavior on session start

**Pick: A — Always pre-fill, but do it at POST /session, not PUT /state.**

The backend already supports this. `POST /v1/onboarding/session` accepts `initial_state` in the body:

```python
# routes.py — already live
state = FormState(
    session_id=session_id,
    step_id=req.step,
    participant_id=req.participant_id,
    values=_build_initial_values(req.initial_state),  # ← pre-fill here
)
state.recompute_completion(req.schema)
```

Flutter flow on mic button tap:
1. Read existing `step1Draft` values from controller.
2. Build `initial_state` map using the mapping table (`basics.full_name` ← `step1Draft.personalDetails.fullName`).
3. Send in `POST /session` body. Backend initialises FormState with those values.
4. Open WS — agent receives system prompt with pre-filled fields already marked as filled.
5. Agent naturally skips filled required fields; only asks for missing ones.

**Why not PUT /state before WS open (as written in option A)?**
Unnecessary round-trip. `POST /session` + `initial_state` achieves the same result in one call. `PUT /state` is for app-side edits *between* sessions, not pre-fill at start.

**Why not B (never pre-fill)?**
Re-asking already-answered questions is hostile UX on long onboarding forms. NDIS onboarding can have 30+ fields per step — the user already typed some.

**Why not C (required-empty only)?**
Optional fields still have value. A phone number already entered should not be re-asked. Pre-fill everything; the agent will confirm with the user naturally.

---

## Q6 — Field update conflict resolution

**Pick: B — User wins within N=5 seconds of last keystroke, voice wins otherwise.**

Architecture:
```dart
// In voice_cubit or field controller
DateTime? _lastManualEditAt;

void onFieldUpdated(VoiceFieldUpdate event) {
  final field = _getField(event.section, event.field);
  final sinceEdit = _lastManualEditAt == null
      ? Duration.zero
      : DateTime.now().difference(_lastManualEditAt!);
  
  if (sinceEdit < const Duration(seconds: 5)) {
    // User was just typing — ignore voice update, emit conflict log
    _logConflict(event);
    return;
  }
  // Safe to apply voice value
  field.value = event.value;
  _emitFieldFlash(event.field); // animate per Q8
}

void onUserTyped(String fieldId, String value) {
  _lastManualEditAt = DateTime.now();
  _applyUserValue(fieldId, value);
}
```

**Why not A (voice always wins)?**
Voice overwrites user's active typing = infuriating. Confidence from Gemini can be wrong — user may be correcting it.

**Why not C (last-write-wins)?**
Timestamp comparison across WS events and local edits is unreliable on mobile (clock skew, buffering).

**Why not D (toast for every conflict)?**
Toast fatigue. Onboarding forms fill fast — showing confirmations on every field update slows the flow. Reserve D for a specific edge case: if voice captures a value that *differs from* a user-typed value and the field already has content. That's the one toast worth showing.

**Backend note:** `FieldValue` carries `confidence` score. If `confidence < 0.6`, consider always deferring to user-typed value regardless of recency.

---

## Q7 — Voice button placement & state

**Pick: B — FAB launcher → expands to bottom sheet.**

State machine:
```
IDLE:    FAB visible, mic icon, bottom-right
ACTIVE:  FAB becomes X (close), bottom sheet slides up with:
           • live waveform (audio level from WS binary frames)
           • agent_said / user_said transcript bubbles
           • "End session" button
           • completion progress bar (from state events)
CLOSING: Bottom sheet slides down, FAB spins briefly, disappears
```

**Why not A (FAB only)?**
No channel for transcript or agent responses. User doesn't know if voice is working or what the agent said — accessibility failure on a medical onboarding form.

**Why not C (persistent bottom bar when active)?**
Bottom bars on mobile are navigation chrome. A persistent bar competes with the form itself. Bottom sheet (B) is overlay — dismissable, doesn't reflow the form layout.

**Technical:** Bottom sheet height = 40% screen. WS emits `user_said` and `agent_said` JSON events — pump them into a `ListView.builder` inside the sheet. No separate audio playback widget needed; waveform is driven by mic amplitude from the `record` package stream.

---

## Q8 — Transcript / live feedback UI

**Pick: B + D — snackbar per field_updated AND inline field flash.**

- **D (inline flash):** On `field_updated` WS event, the mapped form field briefly highlights (border color → green, 600ms animation, then back to default). User sees exactly which field changed. Zero cognitive load.
- **B (snackbar):** Show a concise snackbar: `"✓ Full Name captured"`. Auto-dismiss after 2s. Gives verbal confirmation without requiring user to look at the field.

**Do not use C (full transcript bottom sheet) as default.** Transcript is inside the bottom sheet (Q7) — only visible when the user taps to expand. During active filling, the user should be looking at the form, not a chat log.

**Implementation:**
```dart
// In WS event handler
case 'field_updated':
  final update = VoiceFieldUpdate.fromJson(event);
  _flashField(update.field);                          // D — animate form field
  _showSnackbar('✓ ${update.fieldLabel} captured');  // B — snackbar
  break;

case 'agent_said':
  _appendTranscript(event['text'], speaker: 'agent'); // feeds bottom sheet only
  break;
```

**Why not A (silent)?**
Voice fills fields the user may not be watching. Silent updates = user wonders if voice is working.

---

## Q9 — Permission denial flow

**Pick: A first, then C on permanent denial.**

```dart
Future<void> onMicFabTapped() async {
  final status = await Permission.microphone.status;
  
  if (status.isGranted) {
    _startVoiceSession();
    return;
  }
  
  if (status.isPermanentlyDenied) {
    // C — hide FAB, show banner
    _setFabVisible(false);
    _showSettingsBanner('Enable microphone in Settings to use voice');
    return;
  }
  
  // First denial or not-yet-asked → A — snackbar + settings button
  final result = await Permission.microphone.request();
  if (result.isPermanentlyDenied) {
    _setFabVisible(false);
    _showSettingsBanner('Enable microphone in Settings to use voice');
  } else if (!result.isGranted) {
    _showSnackbar('Microphone permission needed', action: 'Settings', onTap: openAppSettings);
  }
}
```

**Why not B (modal re-request)?**
iOS: second `request()` call after denial does nothing — OS returns `denied` immediately without showing dialog. Android 13+: same behavior after second denial. Modal is pointless at that point.

---

## Q10 — Network/WS failure UX

**Pick: A — auto-reconnect silently up to 3 times using resumption_handle.**

This is exactly what Phase E (not yet built) will enable on the server. Flutter should implement optimistically now.

```dart
int _reconnectAttempts = 0;
static const _maxReconnects = 3;
String? _resumptionHandle; // received from WS 'resumption_handle' event

Future<void> _onWsDisconnected() async {
  if (_reconnectAttempts >= _maxReconnects) {
    _showSnackbar('Voice disconnected', action: 'Retry', onTap: _manualReconnect);
    return;
  }
  
  _reconnectAttempts++;
  await Future.delayed(Duration(seconds: _reconnectAttempts)); // 1s, 2s, 3s backoff
  
  // If resumption_handle available → server restores Gemini context
  // If not (Phase E not built yet) → new WS + FormState already pre-filled in Redis
  await _openWs(resumptionHandle: _resumptionHandle);
}

void _onWsResumed() {
  _reconnectAttempts = 0;
  // No UI feedback for silent recovery — user doesn't need to know
}
```

**Backend guarantee:** Even without handle, Redis holds `FormState` for the full session TTL. New WS open re-injects current state into Gemini system prompt. User loses conversational context but not form data.

**Why not B (user-initiated only)?**
Mobile networks drop constantly (tunnel, elevator, handoff). Silent auto-reconnect = standard expectation. Surfacing a toast for every 2-second blip = poor UX.

---

## Q11 — Session lifecycle on screen exit

**Pick: B for intentional navigation; A for OS-forced background.**

```dart
// WillPopScope or Navigator observer
Future<bool> onWillPop() async {
  if (!_voiceActive) return true; // no voice → allow back
  
  // B — confirm dialog
  final confirmed = await showDialog<bool>(
    context: context,
    builder: (_) => AlertDialog(
      title: Text('End voice session?'),
      content: Text('Voice is active. Ending will save progress so far.'),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context, false), child: Text('Stay')),
        TextButton(onPressed: () => Navigator.pop(context, true),  child: Text('End & Leave')),
      ],
    ),
  );
  
  if (confirmed == true) {
    await _stopVoiceSession(); // closes WS, POSTs /complete
  }
  return confirmed ?? false;
}

// AppLifecycleListener
void onBackground() {
  if (_voiceActive) _stopVoiceSession(); // A — auto-stop
}
```

**Why not C (keep alive in background)?**
iOS terminates network connections aggressively in background. Android may allow it briefly but it's unreliable. Do not design for a behavior the OS won't guarantee. Also: Gemini Live session has a wall-clock time limit — keeping it alive burns quota.

---

## Q12 — Escalation handling (self-harm/abuse flag)

**Pick: B — stop voice, full-screen crisis resources, log to backend.**

Server emits:
```json
{"type": "escalated", "reason": "self_harm", "transcript_excerpt": "..."}
```

Flutter response:
```dart
case 'escalated':
  await _stopVoiceSession(postComplete: false); // close WS immediately
  _logEscalationLocally(event);
  _navigateToEscalationScreen(
    reason: event['reason'],
    excerpt: event['transcript_excerpt'],
  );
  break;
```

Escalation screen (full-screen modal, not dismissable with back button):
- Crisis line: **13 11 14** (Lifeline Australia)
- Disability crisis: **1800 800 110** (NDIS Commission)
- Support email from tenant config
- "Return to form" button only appears after 10s (prevents accidental dismiss)

**Why not A (voice continues)?**
Continuing voice in background while showing crisis resources is a tone-deaf UX choice. A support worker reading out a self-harm disclosure shouldn't hear Gemini still asking about Medicare numbers.

**Why not C (silent log)?**
Real-time crisis needs real-time response. Silent logging to admin view is too slow for a human safety trigger. NDIS Code of Conduct §2.3 requires providers to act on disclosure of risk. Silent log does not satisfy this.

**Backend note:** `escalate_incident` tool continues the session server-side (session stays open, escalation logged). Flutter must close WS client-side and ignore any further server events. The escalation record is preserved in FormState for audit.

---

## Q13 — Voice service base URL

**Pick: C (dart-define) + B (derive from existing host).**

```dart
// lib/core/config/app_config.dart
class AppConfig {
  static const String _apiHost = String.fromEnvironment(
    'API_HOST',
    defaultValue: 'localhost',
  );
  
  static String get voiceServiceBaseUrl => 'http://$_apiHost:8083';
  static String get voiceServiceWsUrl   => 'ws://$_apiHost:8083';
  static String get senaApiBaseUrl      => 'http://$_apiHost:8082'; // existing
}
```

```bash
# Dev
flutter run --dart-define=API_HOST=localhost

# Staging
flutter build apk --dart-define=API_HOST=staging.sena.com.au

# Prod
flutter build apk --dart-define=API_HOST=api.sena.com.au
```

**Why not A (new constant AppStrings.voiceServiceBaseUrl)?**
Hardcoded constants need rebuilds per environment. Fragile. Staging/prod URLs should never be in source.

**Why not B (derive from apiBaseUrl string manipulation)?**
Port stripping/injection via string parsing is brittle. If the SENA API ever moves to a standard port (443), the derivation logic breaks.

---

## Q14 — Auth on voice service

**Pick: B — send Bearer token anyway.**

```dart
// In VoiceApiClient
Future<CreateSessionResponse> createSession(CreateSessionRequest req) async {
  final token = await _authService.getToken(); // already have this
  final response = await _dio.post(
    '/v1/onboarding/session',
    data: req.toJson(),
    options: Options(headers: {
      if (token != null) 'Authorization': 'Bearer $token',
    }),
  );
  return CreateSessionResponse.fromJson(response.data);
}
```

**Why not A (no auth headers)?**
When the service flips to `AUTH_MODE=jwt` (post-MVP), Flutter needs a code change + release. Sending the token now is zero-cost and future-proof. The backend ignores unknown/unvalidated headers in `dev_header` mode — it won't error.

**Why not C (tenant_id + participant_id headers only)?**
`participant_id` already goes in the POST body — duplication. `tenant_id` without a token is unauthenticated multi-tenant data access — worse than no auth. The backend derives tenant from the JWT claim, not a header you can spoof.

---

## Q15 — Audio playback strategy (PCM16 24kHz from server)

**Pick: A — `flutter_pcm_player`.**

```dart
final _player = FlutterPcmPlayer();

// On WS binary frame (server → client audio)
_wsChannel.stream.listen((data) {
  if (data is Uint8List) {
    _player.feed(data); // raw PCM16 24kHz chunks
  }
});

// On session start
await _player.setup(sampleRate: 24000, channelCount: 1);
await _player.play();

// On session end
await _player.stop();
await _player.release();
```

`flutter_pcm_player` is purpose-built for streaming PCM chunks — minimal buffering overhead, designed for this exact use case (real-time TTS/voice streams). No codec negotiation, no format wrapping.

**Why not B (flutter_soloud)?**
Built for game audio mixing. Heavier dependency, more setup. Overkill for a single-stream voice feed.

**Why not C (just_audio + custom feeder)?**
`just_audio` expects seekable sources. Streaming raw PCM requires a custom `StreamAudioSource` + byte-to-sample conversion. Hundreds of lines of boilerplate for something `flutter_pcm_player` does in 10.

---

## Q16 — Mic capture package (PCM16 16kHz mono)

**Pick: A — `record` ≥5.x.**

```dart
final _recorder = AudioRecorder();

Future<void> startMicStream() async {
  final config = RecordConfig(
    encoder: AudioEncoder.pcm16bits,
    sampleRate: 16000,
    numChannels: 1,
    echoCancel: true,   // important — prevents agent audio feeding back into mic
    noiseSuppress: true,
  );
  
  final stream = await _recorder.startStream(config);
  stream.listen((pcmChunk) {
    // Send binary frame to WS → server → Gemini Live
    _wsChannel.sink.add(pcmChunk);
  });
}

Future<void> stopMicStream() async {
  await _recorder.stop();
}
```

**Critical:** `echoCancel: true` — without this, agent audio output leaks into mic input, causing echo feedback and confusing Gemini's VAD (documented in issues-solved KB issue #0001).

**Why not B (flutter_sound)?**
Heavier, less maintained, worse null-safety. `startStream()` API is inconsistent across platforms.

**Why not C (native platform channel)?**
Weeks of work for no functional gain. `record` ≥5.x is battle-tested on both platforms for exactly this format.

---

## Q17 — Testing strategy

**Pick: B — unit tests + integration with mock WS server.**

**Unit tests (always required):**
```dart
// Test mapping table exhaustively — this is the highest-risk logic
test('maps basics.full_name to step1Draft.personalDetails.fullName', () {
  final mapped = VoiceFieldMapper.toSenaPath('basics', 'full_name', step: 1);
  expect(mapped, 'personalDetails.fullName');
});

// Test all VoiceEvent parsing
test('parses field_updated event', () {
  final json = {'type': 'field_updated', 'section': 'basics', 'field': 'full_name',
                'value': 'Jane', 'confidence': 0.95};
  final event = VoiceEvent.fromJson(json);
  expect(event, isA<FieldUpdatedEvent>());
});
```

**Integration with mock WS server:**
```dart
// Use shelf_web_socket to spin up real WS in test process
// Feed pre-recorded JSON event sequences
// Verify cubit state transitions and UI updates
test('completes step when step_completed received', () async {
  final mockServer = MockVoiceWsServer();
  mockServer.enqueue([
    {'type': 'ready', 'state': _mockState},
    {'type': 'field_updated', ...},
    {'type': 'step_completed', 'state': _finalState},
  ]);
  
  cubit.startSession(sessionId: 'test-123');
  await expectLater(cubit.stream, emitsInOrder([isA<VoiceActive>(), isA<VoiceCompleted>()]));
});
```

**Add C (manual QA checklist) as release gate, not automated:**
- Can agent understand Australian accents (test with au-en names: Aditya, Nguyen, O'Brien)?
- Does echo cancel prevent feedback loop?
- Does reconnect restore mid-sentence state?
- Does escalation screen appear in <500ms of server event?

---

## Q18 — Rollout / feature flag

**Pick: B — behind remote-config flag, gradual rollout.**

```dart
// lib/features/voice_onboarding/voice_feature_flag.dart
class VoiceFeatureFlag {
  final RemoteConfig _config;
  
  bool get isEnabled => _config.getBool('voice_onboarding_enabled');
  bool get isEnabledForTenant => _config.getString('voice_tenants').split(',')
      .contains(authService.currentTenantId);
}

// In onboarding step screen
if (featureFlag.isEnabled && featureFlag.isEnabledForTenant) {
  _buildMicFab();
}
```

**Rollout sequence:**
1. Ship with flag OFF everywhere — no user impact.
2. Enable for internal test tenant (your org) — team dogfood.
3. Enable for 1-2 pilot NDIS providers — observe completion rates + error rates.
4. Ramp to 25% → 50% → 100% over 2-4 weeks.

**Why not A (all clients immediately)?**
Voice is a new audio channel touching every onboarding step. A WS bug, VAD issue, or escalation UX problem affects every active onboarding in production. Cannot roll back a shipped APK instantly.

**Why not C (local debug flag)?**
Debug flags die on release builds. Use remote-config from the start — the infrastructure is already there in SENA (Firebase Remote Config or equivalent). C is fine for the first week of dev but should be promoted to B before any external testing.

---

## Summary decision table

| Q | Pick | One-line reason |
|---|------|----------------|
| Q5  | A (at POST /session) | Backend already supports `initial_state` — single round-trip |
| Q6  | B (user wins ≤5s)    | Voice helps, human intent wins on conflict |
| Q7  | B (FAB → sheet)      | Sheet gives transcript + controls without reflowing form |
| Q8  | B+D (snackbar+flash) | Targeted feedback at form field, no chat log overload |
| Q9  | A then C             | OS won't re-prompt after permanent denial — snackbar + hide FAB |
| Q10 | A (silent 3x retry)  | Mobile drops are common; silent reconnect + resumption_handle |
| Q11 | B (confirm) + A (OS) | Protect intentional nav; OS background = auto-stop |
| Q12 | B (full-screen stop) | NDIS compliance + human safety — no silent logging |
| Q13 | C + B (dart-define + derive host) | No hardcoded URLs in source |
| Q14 | B (send token)       | Zero cost now, saves a release cycle when auth lands |
| Q15 | A (flutter_pcm_player) | Purpose-built for raw PCM streaming |
| Q16 | A (record ≥5.x)     | Best maintained, echo-cancel critical |
| Q17 | B (unit + mock WS)  | Mapping table + event parsing = highest risk, must be automated |
| Q18 | B (remote-config flag) | Cannot roll back a shipped APK — gate everything |
