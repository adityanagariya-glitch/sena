---
title: LLM Provider Decision
type: decision
tags: [llm, providers, split, decided]
sources: ["[[src-new-plan]]", "[[src-architecture-audit]]"]
created: 2026-04-15
updated: 2026-04-17
---

# LLM Provider Decision

**Status:** PARTIALLY IMPLEMENTED (2026-04-17)

Gemini is now live for the personal details flow in two modes (REST + Live WebSocket). Bedrock remains for Flow B.

SENA uses **two** LLM providers for different layers:

| Layer | Provider | Model | Status |
|-------|----------|-------|--------|
| Personal details onboarding (HTTP REST) | [[gemini-live-decision]] | `gemini-2.0-flash` | ✅ Implemented — `GeminiService` in `services/gemini_service.py` |
| Personal details onboarding (real-time audio) | [[gemini-live-decision]] | `gemini-3.1-flash-live-preview` | ✅ Demo working — `GeminiLiveService` + `demo_live_server.py`; AU data residency sign-off still pending for production |
| Flow B — case note dictation | [[aws-bedrock]] | Claude 3.5 Sonnet | ✅ Implemented — `BedrockService` |

## Model history

- `gemini-2.5-flash-native-audio-latest` — **deprecated**. Closes session after first turn when triggered by text input. Migrated away 2026-04-17.
- `gemini-live-2.5-flash-preview` / `gemini-2.0-flash-live-001` — deprecated, scheduled shutdown 2025-12-09.
- `gemini-3.1-flash-live-preview` — **current**. Low-latency native audio, 128k context, `thinkingLevel` config. Does NOT support proactive audio or affective dialogue.

## API surface notes

google-genai SDK (current):
- `send_realtime_input(audio=Blob, text=str, audio_stream_end=bool)` — for in-conversation input
- `send_client_content(...)` — reserved for initial history seeding only
- Removed/deprecated: `session.send(input=..., end_of_turn=True)`, `LiveClientRealtimeInput(media_chunks=[...])`

## Tooling

For any Gemini work: invoke Skill `gemini-live-api-dev` or `gemini-api-dev` FIRST, and query the `gemini-api-docs-mcp` MCP server. Do not rely on training-data memory — multiple deprecated patterns leaked through before this rule was enforced.

## Why not a single provider

- Gemini Live is newer; Claude is more battle-tested for structured text tasks in SENA's prompts
- Gemini Live is voice-optimised; Claude is text-optimised
- Provider diversity reduces single-vendor lock-in risk

## Risks

- Two API surfaces to maintain
- Two prompt-engineering workflows
- Cost across two providers instead of one bulk discount

Acceptable trade-off for the latency + quality gain.

## Connections

- Hub: [[Architecture]]
- Related: [[gemini-live-decision]], [[aws-bedrock]], [[degradation-ladder]]
- Source: [[src-new-plan]]
