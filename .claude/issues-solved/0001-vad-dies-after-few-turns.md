---
id: 0001
symptom: "VAD stops detecting user voice after 2-4 turns; model goes silent"
aliases:
  - "voice activity detection dies"
  - "Gemini stops responding after few turns"
  - "model silent after turn 3"
  - "mic open but no USER_SAID log"
  - "speech_started never fires"
  - "multi-turn voice breaks after 2-3 exchanges"
root_cause: "Mic audio was gated by `_agent_speaking` flag — gate muted mic while model preloaded audio for next turn, so VAD never fired"
tags: [gemini-live, vad, multi-turn, audio]
files: [sena-ai/demo_client.html, sena-ai/services/onboarding/src/onboarding/services/gemini_live.py]
fix_commit: "df27ba4"
date_solved: 2026-04-17
verified: "Multi-turn confirmed via USER_SAID/GEMINI_SAID logs, 6+ turn conversation"
---

# 0001 — VAD dies after 2-4 turns

## Symptom

User speaks, model replies first 2-4 turns correctly. Then model stops responding. Mic appears open but no `USER_SAID` log line appears. Gemini server never emits `speech_started` for the user. Occasionally VAD eventually fires on loud noise.

## Root cause

Client code had an echo-suppression gate: "don't send mic audio while `_agent_speaking=true`". Problem: Gemini sends the next turn's audio into the browser's playback buffer BEFORE the user speaks. Gate closes → mic muted → user speaks into closed gate → VAD never sees speech → model waits forever.

The bug is subtle because turn 1 works (flag starts false) and turn 2 often works (flag clears before user speaks). By turn 3-4, timing drift catches up.

## Fix

**Stream mic audio unconditionally. Let Gemini's server-side VAD handle barge-in via `START_OF_ACTIVITY_INTERRUPTS`.**

```diff
- if (!this._agent_speaking) {
-   ws.send(audioChunk);
- }
+ ws.send(audioChunk);
```

Server config must include:

```python
realtime_input_config=types.RealtimeInputConfig(
    automatic_activity_detection=types.AutomaticActivityDetection(
        disabled=False,
        start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_LOW,
        end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
    ),
    activity_handling=types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
)
```

See commit `df27ba4` for full diff: `git show df27ba4`.

## Failed attempts (do NOT retry)

- **`START_SENSITIVITY_HIGH`** — fires on ambient noise between turns, exhausts VAD budget, model stops listening
- **Client-side echo gate on `_agent_speaking`** — the exact cause of this bug; gate closes before user speaks due to Gemini pre-buffering
- **Tightening gate timing (delay/debounce)** — Gemini's audio arrival is non-deterministic, any gate races eventually
- **Browser `echoCancellation:false`** — made self-echo worse without fixing VAD
- **`session.send(input=..., end_of_turn=True)`** — old API, misroutes to `send_client_content` instead of realtime input path

## Why this fix (not alternatives)

Root trade-off: accept some self-echo on non-headphone setups in exchange for reliable multi-turn. Gemini's server VAD is more robust than any client-side gate we tried. Tell user to use headphones or put speakers far from mic.

## Related

- Wiki: [[gemini-live-multi-turn-config]]
- Memory: `feedback_gemini_live_patterns.md` rule 7+8
- CLAUDE.md: Gemini API Rules rule 6
