---
paths:
  - "**/gemini*.py"
  - "**/demo_live*.py"
  - "**/demo_live*.html"
  - "sena-ai/services/onboarding/**/*.py"
  - "sena-ai/services/voice/src/voice/services/gemini*.py"
  - "sena-ai/services/case_review/src/case_review/**/gemini*.py"
---

# Gemini API Rules (MANDATORY)

For ANY code touching Gemini API or Gemini Live API. **Hook-gated:** edits to `gemini*` / `demo_live*` files are BLOCKED until both `skills-gemini.flag` and `ctx7-gemini.flag` are set this session.

## Pre-coding prerequisites

1. **Invoke the skill first** — `Skill: gemini-live-api-dev` (Live API) or `Skill: gemini-api-dev` (general). Do NOT rely on training data — it is stale.
2. **Query Context7** — `mcp__plugin_context7_context7__resolve-library-id` then `query-docs` for `google-genai`. Sets `ctx7-gemini.flag`.

## Current models (verified 2026-05 via gemini-live-api-dev skill)

- **Gemini Live** (onboarding voice, personal-details voice): `gemini-3.1-flash-live-preview`
- **Gemini Flash** (case review summarise/classify): `gemini-3-flash-preview`
- **Deprecated — do NOT use:** `gemini-2.5-flash-native-audio-preview-12-2025`, `gemini-2.5-flash-native-audio-preview-*`, `gemini-live-2.5-flash-preview` (shutdown 2025-12-09), `gemini-2.0-flash-live-001` (shutdown 2025-12-09)

## Current Live API patterns

```python
# Send audio (real-time)
await session.send_realtime_input(
    audio=types.Blob(data=raw, mime_type="audio/pcm;rate=16000")
)

# Send text (real-time, during conversation)
await session.send_realtime_input(text="...")

# Signal end-of-speech (flush mic-paused buffer)
await session.send_realtime_input(audio_stream_end=True)

# Send video frame (real-time)
await session.send_realtime_input(
    video=types.Blob(data=frame, mime_type="image/jpeg")
)
```

**Do NOT use:**
- `session.send(input=..., end_of_turn=True)` — old API, misroutes
- `LiveClientRealtimeInput(media_chunks=[...])` — old wire format
- `send_client_content` for new user messages — that method is ONLY for seeding initial context history (requires `initial_history_in_client_content` in `history_config`)
- `media=` key in `send_realtime_input` — use specific keys: `audio`, `video`, `text`

## Receive loop — multi-part events

A single server event can contain **multiple content parts simultaneously** (audio chunk + transcript). Process ALL parts in each event:

```python
async for response in session.receive():
    content = response.server_content
    if content:
        if content.model_turn:
            for part in content.model_turn.parts:
                if part.inline_data:
                    play_audio(part.inline_data.data)
        if content.input_transcription:
            log_user(content.input_transcription.text)
        if content.output_transcription:
            log_agent(content.output_transcription.text)
        if content.interrupted is True:
            clear_audio_queue()
```

Multi-turn REQUIRES `realtime_input_config` with explicit VAD config. Use `await b2g`, not `asyncio.wait(FIRST_COMPLETED)`.

## Capability limits on `gemini-3.1-flash-live-preview`

- **Response modality:** TEXT or AUDIO per session, NOT both.
- **Audio-only session:** 15 min without compression.
- **Audio + video session:** 2 min without compression.
- **Connection lifetime:** ~10 min (implement session resumption).
- **Proactive audio NOT supported** — model will NOT speak first without user audio input. Greeting must be triggered by user speaking first (system prompt handles greeting content).
- **Affective dialogue NOT supported** — remove any config for it.
- **Async function calling NOT supported** — function calling is synchronous only.
- **Code execution NOT supported.**
- **URL context NOT supported.**

## Audio formats

- **Input:** Raw PCM, little-endian, 16-bit, mono, 16kHz native. MIME: `audio/pcm;rate=16000`.
- **Output:** Raw PCM, little-endian, 16-bit, mono, 24kHz.

## Forbidden patterns (CRITICAL)

**NEVER gate mic audio in server Python (`_browser_to_gemini`).** A server-side `_agent_speaking` flag causes VAD to silently stop after 2-4 turns: model audio for turn N+1 arrives before `turn_complete` of turn N fires, keeping the gate closed when the user tries to speak. Always forward audio unconditionally in `_browser_to_gemini`; rely on `activity_handling=START_OF_ACTIVITY_INTERRUPTS` for barge-in. Use `START_SENSITIVITY_LOW` — HIGH fires on ambient noise between turns.

**Flutter client MUST mute mic during agent speech (echo fix):** set `_agentSpeaking=true` on `turn_start`, `false` on `turn_complete`/`interrupted`. Gate in the mic stream listener (`if (!_agentSpeaking) _sendAudio(chunk)`), not in the recorder itself. Server also calls `send_realtime_input(audio_stream_end=True)` on `turn_start` to flush Gemini's VAD buffer of any echo frames already in flight.

## Best practices

- Use headphones when testing mic audio to prevent echo/self-interruption.
- Enable context window compression for sessions >15 min.
- Implement session resumption (Onboarding service has `services/resumption.py`).
- Use ephemeral tokens for client-side deployments — never expose API keys in browsers.
- Send `audioStreamEnd` when mic is paused to flush cached audio.
- Clear audio playback queues on interruption signals.
- Process all parts in each server event.
