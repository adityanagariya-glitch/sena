---
title: Gemini Live API — Multi-Turn Configuration (google-genai SDK)
type: decision
tags: [gemini, live-api, voice, multi-turn, google-genai, vad]
sources: [session-2026-04-17-debug]
created: 2026-04-17
updated: 2026-04-17
---

# Gemini Live — Multi-Turn Configuration

Authoritative reference for conversational Gemini Live sessions using `gemini-3.1-flash-live-preview` + `google-genai` Python SDK (1.73.x, 2026-04).

Derived from the 2026-04-17 debug session that made `sena-ai/demo_live_server.py` + `demo_client.html` work end-to-end.

## Non-obvious rules

### 1. `session.receive()` returns per-turn, not per-session

```python
# WRONG — kills conversation after turn 1
async for msg in session.receive():
    ...
# iterator exits → function returns → no more turns

# RIGHT — loop around receive()
while True:
    async for msg in session.receive():
        ...
    # log "iterator exited — re-entering"
    await asyncio.sleep(0.01)
    continue
```

The google-genai SDK yields messages in batches per turn. The iterator completes at turn boundaries but the underlying WebSocket stays open. You must re-call `session.receive()` for the next turn.

### 2. Multi-turn requires explicit `realtime_input_config`

Without the VAD config below, `gemini-3.1-flash-live-preview` treats the session as one-shot and closes after the first turn (manifests as `1011 keepalive ping timeout` ~30s later):

```python
config = types.LiveConnectConfig(
    response_modalities=["AUDIO"],
    system_instruction=types.Content(parts=[types.Part(text=SYSTEM_PROMPT)]),
    realtime_input_config=types.RealtimeInputConfig(
        automatic_activity_detection=types.AutomaticActivityDetection(
            disabled=False,
            start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_LOW,
            end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
            prefix_padding_ms=200,
            silence_duration_ms=800,
        ),
        activity_handling=types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
        turn_coverage=types.TurnCoverage.TURN_INCLUDES_ONLY_ACTIVITY,
    ),
    session_resumption=types.SessionResumptionConfig(handle=None),
    input_audio_transcription=types.AudioTranscriptionConfig(),
    output_audio_transcription=types.AudioTranscriptionConfig(),
)
```

### 3. Use `await b2g` lifecycle, not `asyncio.wait(FIRST_COMPLETED)`

```python
b2g = asyncio.create_task(_browser_to_gemini())  # forwards browser → Gemini
g2b = asyncio.create_task(_gemini_to_browser())  # forwards Gemini → browser
try:
    await b2g          # session ends only when BROWSER disconnects
finally:
    g2b.cancel()
    await asyncio.gather(g2b, return_exceptions=True)
```

`FIRST_COMPLETED` tears down the whole session if `g2b` exits for any reason (including transient iterator-end transitions).

### 4. Continuous streaming, no `audio_stream_end`

For Siri/Assistant-style continuous conversation:
```python
await session.send_realtime_input(
    audio=types.Blob(data=pcm16_16khz_bytes, mime_type="audio/pcm;rate=16000")
)
```
Gemini's built-in VAD detects turn boundaries automatically. `audio_stream_end` is only needed for explicit push-to-talk flush.

### 5. Transcription diagnostics are essential

Enable `input_audio_transcription` + `output_audio_transcription` so you can log what Gemini heard and said:

```python
if msg.server_content:
    if msg.server_content.input_transcription:
        log("USER_SAID:", msg.server_content.input_transcription.text)
    if msg.server_content.output_transcription:
        log("GEMINI_SAID:", msg.server_content.output_transcription.text)
```

Without these, debugging "why isn't Gemini responding to my voice?" is blind.

## Browser playback (Windows Chrome specifics)

1. **One shared AudioContext** for both mic capture and speaker output. Two contexts silently fail on Windows WASAPI.
2. **Do not force `sampleRate` on AudioContext constructor.** Let browser pick device-native rate.
3. **Manually upsample 24kHz PCM → native rate** before `createBuffer`. Browser's internal resampler fails silently on some Windows drivers.
4. **Await `playCtx.resume()` before scheduling buffers.** `resume()` is async; scheduling before resolve = frozen clock = silent playback.
5. **80ms lookahead on `src.start()`** to avoid scheduling in the past after a resume.

## Reference implementation

- **Demo (new API, continuous streaming):** `sena-ai/demo_live_server.py` + `sena-ai/demo_client.html`
- **Production (old API, same pattern):** `sena-ai/services/voice/src/voice/services/gemini_live_service.py` + `services/voice/src/voice/api/ws_routes.py`

Production uses the legacy `session.send(input=types.LiveClientRealtimeInput(media_chunks=[...]))` API. Demo uses the current `session.send_realtime_input(audio=Blob(...))` API. Do not mix.

## Connections

- [[personal-details-flow]]
- [[llm-provider-decision]]
- [[Architecture]]
