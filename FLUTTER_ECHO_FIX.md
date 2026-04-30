# Voice Assistant Echo Fix — Flutter Action Required

**Issue:** The voice assistant (Sena) hears its own output audio as user input.  
**Server fix:** Already deployed in `gemini_live.py`.  
**Flutter fix:** Required — see below.  
**File to edit:** `lib/features/voice_onboarding/presentation/controllers/voice_session_controller.dart`

---

## Problem

When Sena speaks, the phone's microphone picks up the speaker output and sends
it back to the server as user audio. This causes Gemini to:
- Interpret its own voice as a new user utterance
- Respond to itself mid-sentence
- Loop indefinitely on its own output

**Why hardware AEC alone is not enough:**  
`RecordConfig(echoCancel: true)` is already set, which requests hardware
Acoustic Echo Cancellation. Hardware AEC works by comparing the mic signal
against the playback signal using a fixed-latency reference. Our server streams
PCM at 24 kHz back to the phone with variable network buffering, so the
playback timing is unpredictable — hardware AEC loses its reference alignment
and passes the echo through.

---

## Server-side fix already applied

`gemini_live.py` now calls `send_realtime_input(audio_stream_end=True)` the
instant a `turn_start` event fires. This tells Gemini's VAD "user speech has
ended" so it discards any echo frames already buffered before Flutter mutes.
The server cannot do more — the mic audio originates on the phone.

---

## Flutter fix required

### What to implement

In `VoiceSessionController`, gate mic chunk sending based on whether the agent
is currently speaking. When `turn_start` is received → stop sending mic audio.
When `turn_complete` or `interrupted` is received → resume sending mic audio.

### Exact changes — `voice_session_controller.dart`

#### 1. Add `_agentSpeaking` flag (after `_micSub` declaration, line ~87)

```dart
// ── internal ───────────────────────────────────────────────────────────────
VoiceSession? _session;
StreamSubscription<VoiceEvent>? _eventSub;
StreamSubscription<Uint8List>? _micSub;
// True while Gemini is speaking — mic chunks are suppressed to prevent the
// assistant's own playback audio from looping back as user input.
bool _agentSpeaking = false;
```

#### 2. Handle turn events in `_handleEvent` (currently no-op, line ~288)

**Before:**
```dart
case VoiceTurnStart():
case VoiceTurnComplete():
case VoiceInterrupted():
  // No-op for Track A.
  break;
```

**After:**
```dart
case VoiceTurnStart():
  _agentSpeaking = true;
  break;
case VoiceTurnComplete():
case VoiceInterrupted():
  _agentSpeaking = false;
  break;
```

#### 3. Gate mic chunks in `_startMic` (line ~325)

**Before:**
```dart
_micSub = stream.listen(
  (chunk) => _sendAudio(chunk),
  onError: (Object e) =>
      AppLogger.error('VoiceCtrl', 'mic stream error: $e'),
);
```

**After:**
```dart
_micSub = stream.listen(
  (chunk) {
    if (!_agentSpeaking) _sendAudio(chunk);
  },
  onError: (Object e) =>
      AppLogger.error('VoiceCtrl', 'mic stream error: $e'),
);
```

---

## Why this gate is safe (does not break VAD)

The banned server-side `_agent_speaking` gate causes VAD to silently die because
Gemini sends turn N+1 model audio *before* `turn_complete` of turn N arrives on
the server. The server flag stays `true` at the wrong time and the mic gets
silenced exactly when Gemini is listening for the user.

The Flutter-side gate has no such race: `turn_start` and `turn_complete` are
events the client receives in sequence. There is no buffering discrepancy — the
client sees `turn_start` *after* the server has already started streaming audio
bytes, so muting at `turn_start` is correct timing. VAD on the server side is
unaffected because the server keeps forwarding audio unconditionally; it simply
receives fewer (zero) chunks during playback, which is a normal state the VAD
handles as "user silence."

---

## Test checklist

- [ ] Start a session. Let Sena greet. Sena should NOT interrupt itself.
- [ ] After Sena finishes speaking (`turn_complete`), say something. Sena should
      respond to you, not to itself.
- [ ] Interrupt Sena mid-sentence (`interrupted`). After interruption, confirm mic
      resumes: Sena should hear your words.
- [ ] Long session (>3 turns). Confirm mic still works on turn 5+.
- [ ] Silence test: say nothing for 8 seconds after `turn_complete`. Sena should
      check in: "Hey, just checking — are you still there?"

---

## WS events the Flutter client must handle (for reference)

| Event | Type | Action |
|-------|------|--------|
| `turn_start` | text JSON | Start audio playback queue. **Set `_agentSpeaking = true`.** |
| `turn_complete` | text JSON | Flush/stop playback. **Set `_agentSpeaking = false`.** |
| `interrupted` | text JSON | Clear playback queue immediately. **Set `_agentSpeaking = false`.** |
| `go_away` | text JSON `{time_left_ms: N}` | Gemini session closing in N ms — call the resume endpoint before expiry |
| `resumable` | text JSON `{handle, ttl_sec}` | Store handle for reconnect |

---

## Contact

Questions → raise against the SENA AI backend repo or ping the AI team.  
Server source: `SENA_AI/sena-ai/services/onboarding/src/onboarding/services/gemini_live.py`
