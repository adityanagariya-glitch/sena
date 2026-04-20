---
title: Personal Details Flow
type: concept
tags: [voice, flow, personal-details, form]
sources: ["[[src-flow-b]]", "[[src-architecture-audit]]", "CLAUDE.md"]
created: 2026-04-16
updated: 2026-04-17
---

# Personal Details Flow

A parallel voice-guided flow for capturing participant personal details, running alongside (or independently from) [[flow-b-voice-dictation]]. Uses the same voice infrastructure but a different prompt context and output schema.

Two delivery modes now coexist:

1. **HTTP REST mode** (production) — transcript-in / JSON-out per turn. Uses `gemini-2.0-flash` via `GeminiService`.
2. **WebSocket Live mode** (demo / next-gen) — bidirectional PCM16 audio streaming via Gemini Live API. Uses `gemini-3.1-flash-live-preview` via `GeminiLiveService`.

## API endpoints

**HTTP REST (production):**
```
POST /v1/voice/personal-details/session       — start session
POST /v1/voice/personal-details/session/turn  — process voice turn (transcript → fields)
POST /v1/voice/personal-details/session/end   — end session, return collected fields
```

**WebSocket (Live API):**
```
WS   /v1/voice/personal-details/live/{session_id}  — bidirectional audio stream
```

Demo stack (no auth / no DB): `sena-ai/demo_live_server.py` + `sena-ai/demo_client.html` running on port 8082.

All endpoints require `support_worker`, `manager`, or `admin` role.

## Output schema

Unlike Flow B (which produces free-form case note text), this flow returns structured field-value pairs:

```json
{
  "fields": { "name": "...", "dob": "...", "ndis_number": "..." },
  "missing_fields": ["emergency_contact"],
  "completeness_score": 0.85,
  "agent_reply": "Got it. What is the emergency contact name?"
}
```

The agent asks targeted questions to collect missing fields until `completeness_score` reaches threshold or the session ends.

## Architecture

### HTTP REST mode (production)
- Uses **Google Gemini** (`gemini-2.0-flash`) via `GeminiService` (`services/gemini_service.py`) for structured extraction — **not** Bedrock
- `GeminiService` has identical interface to `BedrockService.run_personal_details_turn()` — same prompt, same output schema
- Called from `personal_details_service.py:128` — still live at runtime
- Session state held in [[redis-usage]] with same TTL/key conventions
- Rate limiting applied per-turn (same as Flow B, `rate_limit_turn_per_minute`)
- No LiveKit session needed — operates from plain text transcript input
- Requires `SENA_AI_GEMINI_API_KEY` in `.env` (get from https://aistudio.google.com)

### WebSocket Live mode (real-time audio)
- Uses **Google Gemini Live** (`gemini-3.1-flash-live-preview`) via `GeminiLiveService` (`services/gemini_live_service.py`)
- Browser mic (PCM16 16 kHz mono) → FastAPI WS → `session.send_realtime_input(audio=Blob(...))` → Gemini → PCM16 24 kHz mono → browser speaker
- `audio_stream_end=True` signal flushes VAD when mic pauses
- Session lifecycle: WS stays open until browser disconnects; `g2b` task cancelled in finally-block (never `asyncio.wait(FIRST_COMPLETED)`)
- Proactive audio NOT supported on this model — model only speaks after user input; greeting is handled via system-prompt instruction
- Requires `SENA_AI_GEMINI_API_KEY` + `SENA_AI_GEMINI_LIVE_MODEL_ID` in `.env`
- Demo: `demo_live_server.py` + `demo_client.html` (no DB, no Redis, no auth — pure audio pipeline)

### API surface notes (current google-genai SDK)
- `session.send_realtime_input(audio=..., text=..., audio_stream_end=...)` — use for all in-conversation input
- `session.send_client_content(...)` — reserved for seeding initial history only
- Deprecated patterns to avoid: `session.send(input=..., end_of_turn=True)`, `LiveClientRealtimeInput(media_chunks=[...])`, `role="user"` on `system_instruction`

## Relationship to Flow B

| Dimension | Flow B | Personal Details Flow |
|-----------|--------|-----------------------|
| Output | Narrative case note (SOAP) | Structured field-value pairs |
| Prompt style | Open dictation with guided questions | Targeted field collection |
| Typical length | Multiple turns | Short (5-10 fields) |
| Approval required | Yes (human-in-the-loop) | Currently unclear — see [[open-questions]] |

## Connections

- Hub: [[Architecture]]
- Related: [[flow-b-voice-dictation]], [[voice-service]], [[support-worker]], [[ndis-participant]]
- Infrastructure: [[aws-bedrock]], [[redis-usage]]
- Open: [[open-questions]] — approval workflow for personal details TBD
