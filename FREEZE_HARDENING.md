# Freeze Hardening — gemini-3.1-flash-live-preview

> Audience: Flutter dev (§A), Backend dev (§B). Read §0 first, then your own section.
> Both devs read §C verification matrix before claiming done.

## §0 Why this exists

The Gemini Live API on `gemini-3.1-flash-live-preview` silently hangs under four known conditions documented by the SDK team and reproduced in our staging environment. The connection stays OPEN, no error frames arrive, and the only symptom is that the model stops replying. Restarting the WS clears it but loses context.

The four failure modes and their SENA-specific severity:

1. **VAD turn-end failure (HIGH for SENA).** Background noise — TV, kitchen sounds, kids — prevents the server-side VAD from registering a clean silence. The model waits forever. NDIS participants frequently call in from noisy home environments. SENA today relies entirely on VAD; there is **no client-driven turn delimiter**.

2. **Pipeline degradation (MEDIUM for SENA).** Over long sessions (>10 minutes) the `input_audio_transcription` engine in the preview model can drop quality and eventually stop processing new chunks. Mitigated by `context_window_compression` (`SlidingWindow`) which is supported by the SDK but **not enabled** in our `LiveConnectConfig`.

3. **PCM format sensitivity (HIGH for SENA).** Any drift in sample rate, channel count, bit depth, or endianness silently drops chunks. Flutter sets format once at recorder init and never validates per chunk. Backend does **no inbound validation** of mime-type or chunk structure. A driver-level format switch is invisible to the user but fatal to the session.

4. **Interruption recovery (MEDIUM for SENA).** When the user talks over the agent, the outbound audio buffer must be dumped and the model needs to know what thought was interrupted. Our backend stores `_last_interrupted_intent` but never injects it back. Our Flutter `_player.flush()` works but lacks ordering guarantees.

This document specifies the four mitigations that close the gap.

---

## §A Flutter changes

### A1 — Emit explicit `audio_end` WS frame

**Why:** VAD cannot be trusted. The client must be able to force a turn end.

**Where:** `lib/features/voice_onboarding/presentation/controllers/voice_session_controller.dart`

**Trigger on all four conditions:**

| Trigger | How |
|---|---|
| Mic mute button tap | Existing toggle handler → after stopping recorder, send `audio_end`. |
| Client-side silence | Background RMS monitor on the recorded PCM. If `RMS < -50 dBFS` for `1500 ms` continuous, send `audio_end`. Only fires while recording is active and at least one chunk has been sent. Single-shot per turn — reset on next agent `turn_start`. |
| App lifecycle paused/inactive | `WidgetsBindingObserver.didChangeAppLifecycleState` → on `AppLifecycleState.paused` or `.inactive`, send `audio_end` and stop recorder. |
| Explicit "I'm done" UI button | If exposed in the screen — same handler as mic-mute path. |

**WS frame:** `{"type":"audio_end"}` (already supported by backend; just needs active emission).

**Telemetry:** log local event `audio_end_emitted` with reason: `mute | silence | lifecycle | explicit`.

### A2 — Per-chunk PCM format guard

**Why:** A driver- or OS-level format switch is invisible to the user but kills the session.

**Where:** wherever PCM chunks are read from the recorder stream before being base64-encoded for WS send. Likely `voice_audio_recorder.dart` or similar.

**Guard logic:**
```dart
const _expectedSampleRate = 16000;
const _expectedChannels = 1;
const _expectedBitsPerSample = 16;
const _expectedEndian = Endian.little;

bool _isValidPcmChunk(Uint8List chunk, RecorderConfig cfg) {
  if (cfg.sampleRate != _expectedSampleRate) return false;
  if (cfg.channels   != _expectedChannels)   return false;
  if (cfg.bitsPerSample != _expectedBitsPerSample) return false;
  if (cfg.endian     != _expectedEndian)     return false;
  if (chunk.length % 2 != 0) return false;       // 16-bit alignment
  return true;
}
```

On mismatch: log `audio_format_drop` with `expected` vs `seen`, do **not** send the chunk, increment `_droppedChunkCount`.

### A3 — Recorder re-init on format drift detection

If `_droppedChunkCount >= 3` within a 5-second window: attempt **one** recorder re-init with the canonical config. If re-init fails or drop count keeps climbing: surface a user-visible toast ("Microphone audio format issue. Please restart the session.") and stop the recorder.

### A4 — Player flush ordering

**Where:** `lib/features/voice_onboarding/data/services/voice_audio_player.dart`

**Current:** `_player.flush()` releases and re-setups in one call. No drain guarantee.

**Fix:** split into ordered steps:
```dart
Future<void> flushAndReset() async {
  await _player.stop();           // 1. stop playback
  await Future.delayed(const Duration(milliseconds: 100));  // 2. drain residual PCM
  await _player.release();        // 3. release native handle
  await _player.setupPcm(sampleRate: 24000, channels: 1, bitsPerSample: 16);  // 4. re-init
}
```

### A5 — Subscribe to new `audio_format_rejected` server event

**Where:** the WS message dispatcher in `voice_session_controller.dart`.

```dart
case 'audio_format_rejected':
  AppLogger.warn('voice', 'Backend rejected audio format: ${data['seen']}, expected: ${data['expected']}');
  AppSnackbar.error('Microphone format mismatch — restarting recorder');
  await _recorder.stop();
  await _recorder.startWithCanonicalConfig();
  break;
```

---

## §B Backend changes

### B1 — Enable context window compression

**Why:** prevents pipeline degradation on long sessions. SDK-supported, zero risk.

**Where:** `SENA_AI/sena-ai/services/onboarding/src/onboarding/services/gemini_live.py` — `LiveConnectConfig` construction (search for `LiveConnectConfig(`).

**Add:**
```python
from google.genai import types

config = types.LiveConnectConfig(
    # ...existing fields...
    context_window_compression=types.ContextWindowCompressionConfig(
        sliding_window=types.SlidingWindow(),
    ),
)
```

Verified by Context7 doc fetch — `contextWindowCompression` is a first-class `LiveConnectConfig` property and is the official long-session mechanism.

### B2 — Intent re-injection on interrupt

**Why:** preserve mid-utterance intent so the agent's next reply addresses the interruption AND returns to the interrupted thread.

**Where:** `gemini_live.py` — interrupt handler (search `_last_interrupted_intent`) and the agent-turn-start callsite.

**Pattern:**
- Interrupt handler **already** moves the partial buffer into `self._last_interrupted_intent`.
- New behaviour: before the NEXT agent turn starts, if `_last_interrupted_intent` is set, inject one hidden text turn via `send_client_content`, then clear it.

```python
async def _maybe_reinject_intent(self, session):
    if not self._last_interrupted_intent:
        return
    intent = self._last_interrupted_intent
    self._last_interrupted_intent = None
    note = (
        f'(SYSTEM: you were mid-sentence saying "{intent}" when interrupted — '
        f'address the user\'s interruption first, then return to that thread if still relevant.)'
    )
    await session.send_client_content(
        turns=[types.Content(role='user', parts=[types.Part(text=note)])],
        turn_complete=False,
    )
    log.info("interrupt_intent_reinjected session=%s chars=%d", self._session_id, len(intent))
```

Call `_maybe_reinject_intent` immediately before re-enabling the realtime audio input pipe after an interrupt event.

Also extend the outbound event:
```python
await self._ws.send_text(json.dumps({
    "type": "interrupted",
    "intent_preserved": bool(self._last_interrupted_intent or intent),
}))
```

### B3 — Inbound audio format validator

**Why:** silent format drift currently produces invisible session hangs.

**Where:** `SENA_AI/sena-ai/services/onboarding/src/onboarding/api/ws_routes.py` — audio frame handler.

**Logic:**
1. Inspect inbound audio blob mime-type if present in the message envelope (`{"type":"audio","mime":"audio/pcm;rate=16000;channels=1"}`).
2. If mime missing, fall back to byte-length heuristic — for 20 ms @ 16 kHz mono 16-bit, expect `640 bytes`. Tolerate 320 / 640 / 1280 / 1920 byte multiples. Anything else → suspect.
3. On confirmed mismatch:
   - Send to client: `{"type":"audio_format_rejected","expected":"audio/pcm;rate=16000;channels=1;bits=16","seen":"<observed>"}`
   - Log `structlog` event `audio_format_rejected_chunk` with session id + observed shape.
   - Drop the chunk (do NOT forward to Gemini).
   - Increment `self._format_rejection_count`.
4. **Hard kill:** if three rejections happen within five seconds:
   ```python
   await self._ws.close(code=1003, reason="audio format violation")
   ```
   1003 is the standards-defined "unsupported data" close code.

### B4 — Chunk-flow metrics + silence deadband

**Why:** make stalls observable.

**Where:** add fields to the per-connection state object in `gemini_live.py`:
```python
self.audio_chunk_count: int = 0
self.audio_bytes: int = 0
self.last_audio_chunk_at: float = 0.0  # already present per audit
```

Increment per chunk forwarded. Extend `_silence_monitor()`:
- If `(now - last_audio_chunk_at) > 10s` AND `not agent_active` AND `recording supposedly active` (no `audio_end` since last `turn_start`):
  - Log `audio_chunk_deadband_warning session=... last_chunk=...s_ago`
  - This is a diagnostic only — no user-visible action. Helps post-mortem the next freeze report.

---

## §C End-to-end verification matrix

| # | Scenario | Action | Expected client side | Expected backend log |
|---|---|---|---|---|
| 1 | `audio_end` via mic mute | Speak 5s, tap mute | Mic icon updates, no further chunks sent | `audio_end_received`, model replies within 1s |
| 2 | `audio_end` via silence | Speak 3s, fall silent 2s | At ~1500 ms silence: `audio_end_emitted reason=silence` | Same as #1 within 1.5s of silence |
| 3 | Client-side format drift drop | Force-spoof recorder to 8 kHz | Local `audio_format_drop`, no chunks on wire | No inbound audio chunks at backend |
| 4 | Client-side recorder re-init | After 3 drops in 5s | Recorder re-init log, normal chunks resume | Inbound chunks resume |
| 5 | Backend format rejection | `test_harness.html` injects 48 kHz PCM | Client receives `audio_format_rejected`, toast shown | Three `audio_format_rejected_chunk` → WS close 1003 |
| 6 | Long-session compression | 25-min audio session, full step | No mid-session disconnect; coherent replies past 15-min mark | No 1011 / token-limit close codes |
| 7 | Interrupt + intent preserved | Cut agent off mid-sentence | Player drains 100ms then re-inits; no stale audio | `interrupt_intent_reinjected chars=N` in backend log |
| 8 | Interrupt event flag | Same as #7 | Client receives `interrupted.intent_preserved=true` | — |
| 9 | Player flush ordering | Trigger 5 interrupts in 30s | No PCM init errors, no double-stop exceptions | — |
| 10 | Silence deadband warning | App "recording" but mic disconnected | No client event (diagnostic only) | `audio_chunk_deadband_warning` at ~10s |

Commands:
```bash
# Backend
cd SENA_AI/sena-ai/services/onboarding
uvicorn src.onboarding.main:create_app --factory --reload --port 8083

# New backend tests
pytest tests/test_audio_format_validator.py tests/test_interrupt_intent_reinject.py tests/test_context_compression_config.py -v

# Live smoke test
open SENA_AI/sena-ai/services/onboarding/test_harness.html
```

```bash
# Flutter
flutter test test/features/voice_onboarding/audio_format_guard_test.dart
flutter test test/features/voice_onboarding/audio_end_emission_test.dart
flutter run -d <device>   # exercise scenarios 1–4, 7–9 manually
```

---

## §D Wire-contract changes (added by this work)

| Direction | Frame | Status |
|---|---|---|
| Client → Server | `{"type":"audio_end"}` | already supported; now actively emitted by Flutter (A1) |
| Server → Client | `{"type":"audio_format_rejected","expected":"...","seen":"..."}` | **new** (B3) |
| Server → Client | `{"type":"interrupted","intent_preserved": true \| false}` | **extended** with `intent_preserved` field (B2) |

Update `SENA_AI/FLUTTER_WIRING_HANDOFF.md` event table to reflect these three changes when this work ships.

---

## §E Non-goals (intentionally out of scope)

- Switching to a partner integration (LiveKit / Pipecat / Fishjam). Out of scope — keep the WebSocket-direct architecture.
- Refactoring the player module beyond the four-line ordering fix in A4.
- Server-side mic gating — explicitly forbidden by existing SENA architecture rules.
- Reworking the silence monitor — it stays as today; B4 only adds passive metrics.
- Switching off `gemini-3.1-flash-live-preview`. Model migration is a separate decision.

---

## §F Rollout & risk

- **Ship order:** B1 first (zero risk, single line). Then B3 + B4 (wire-contract owner). Then Flutter A2 + A3 + A5 (pairs with B3). Then Flutter A1 (lowest-risk Flutter change). Then B2 + Flutter A4 (interrupt-flow regression risk — ship together with tests).
- **Feature flag (recommended):** gate B1 compression behind `SENA_AI_GEMINI_CONTEXT_COMPRESSION_ENABLED=true` (default true) so it can be disabled without a redeploy if regression observed.
- **Telemetry to add this round:** `audio_end_emitted`, `audio_format_drop`, `audio_format_rejected_chunk`, `interrupt_intent_reinjected`, `audio_chunk_deadband_warning`. All structlog at INFO; PII-free (counts and reasons only).
- **Known risk — A1 silence threshold tuning.** 1500 ms is a starting guess. Surface as `audio_end_silence_ms` config so it can be lengthened to 2500 ms without a code change for users with slow / paused speech.
- **Known risk — B1 sliding-window drop.** Early-turn context can be summarized away. Mitigation: monitor `agent_said` for "earlier you said X" regressions in long-session tests before enabling in production.
- **Known risk — B3 false-positive rejection.** Truncated chunks at TCP boundaries can byte-sniff wrong. Mitigation: require **three** consecutive rejections in 5s before WS close (already in spec).
