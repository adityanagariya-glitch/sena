---
title: Persistent Task List
updated: 2026-04-17
---

> Last session end-state (2026-04-17 PM): continuous-streaming voice demo WORKING.
> Turn-by-turn conversation confirmed via USER_SAID / GEMINI_SAID logs. See task #1.

# SENA Task List

Session-persistent todos. Survives `/compact` and session resets. Claude reads this file at session start and updates it as work progresses.

**Status legend:** `pending` | `in_progress` | `completed` | `blocked`

---

## Active

### #1 — Voice assistant: conversational streaming (Siri/Assistant-style)
- **Status:** completed (2026-04-17, WORKING end-to-end after 4 iteration cycles)
- **Priority:** P0 (primary blocker)
- **Final solution summary:**
  - **Pattern**: continuous mic streaming + Gemini-native VAD (no push-to-talk, no `audio_stream_end`, no keepalive nudge)
  - **Client (`sena-ai/demo_client.html`)**:
    - Single shared `AudioContext` for mic + playback (dual contexts silently fail on Windows WASAPI)
    - Manual upsample 24kHz→native rate before `createBuffer` (bypasses buggy browser resampler)
    - 80ms lookahead + awaited `resume()` before scheduling (avoids frozen-clock silent playback)
    - Test beep on Start (diagnoses speaker chain independent of Gemini)
  - **Server (`sena-ai/demo_live_server.py`)**:
    - `realtime_input_config` with explicit `automatic_activity_detection` — REQUIRED for multi-turn on `gemini-3.1-flash-live-preview`
    - `session_resumption`, `input_audio_transcription`, `output_audio_transcription` enabled
    - **CRITICAL**: `session.receive()` returns after each turn batch. Must wrap in `while True: async for msg in session.receive(): ... continue` — a `return` after the iterator ends kills the conversation
    - `await b2g` lifecycle (NOT `asyncio.wait(FIRST_COMPLETED)` — that tears down session when g2b exits after turn 1)
    - Transcription logs `USER_SAID` / `GEMINI_SAID` for debugging
- **Verified working:** multi-turn conversation with turn_start/turn_complete cycling, transcription proves pipeline end-to-end.

### #2 — Update wiki pages for Gemini Live changes
- **Status:** completed (2026-04-17)
- **Done:**
  - `wiki/log.md` — 2026-04-17 entry appended
  - `wiki/pages/personal-details-flow.md` — added WebSocket Live mode, SDK API surface notes
  - `wiki/pages/llm-provider-decision.md` — split REST vs Live rows, model history, MCP/Skills rule

### #3 — Update CLAUDE.md with session-learned rules
- **Status:** completed (2026-04-17)
- **Done:** Added "Gemini API Rules (MANDATORY)", "Demo Stack", "Cleanup Rule" sections to project `CLAUDE.md`.

### #4 — Session context snapshot for next session resume
- **Status:** in_progress
- **Done:**
  - Persistent task file at `.claude/tasks/TASKS.md` (this file)
  - Memory at `~/.claude/projects/.../memory/feedback_mcp_skills.md`
  - CLAUDE.md Gemini rules section
- **Remaining:** None. Next session reads this file + CLAUDE.md + memory index.

---

## Backlog (deferred)

- Audio transcription display in demo UI (show what Gemini hears + says)
- Wire `GeminiLiveService` into production voice service (currently demo-only)
- AU data residency sign-off for Gemini Live (blocker before production Live mode)
- Session resumption + context window compression (Gemini Live has 10-min connection lifetime)
- Ephemeral token auth for client-side (so browser doesn't hold API key)

---

## Conventions

- Update this file whenever a task status changes or a new task is added.
- Lead each task with ID, status, and 1-line summary.
- Include file paths, constraints, and acceptance criteria for P0/P1 items.
- When a task completes, keep the entry (don't delete) for a few sessions — provides trail.
- When backlog grows stale, prune to a separate archive file.
