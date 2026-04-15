---
title: Approach D Architecture
type: decision
tags: [architecture, voice, livekit, decided, foundational]
sources: ["[[src-voice-arch-analysis]]", "[[src-revised-plan]]", "[[src-new-plan]]"]
created: 2026-04-15
updated: 2026-04-15
---

# Approach D Architecture

**Status:** DECIDED

SENA runs **LiveKit Agents on the SENA backend**. Client devices never connect directly to cloud voice providers; all audio transits SENA servers.

## The four approaches considered

| Approach | Audio path | Verdict |
|----------|-----------|---------|
| A | HTTP turn-based (client → FastAPI → Bedrock, text turns) | Current state. High latency. UX poor. |
| B | Client ↔ cloud voice model directly (Gemini Live, OpenAI Realtime) | Lowest latency. **Fails [[australian-data-residency]].** |
| C | Hybrid — client direct for audio, SENA proxies metadata | Residency risk persists; audio still hits non-SENA surface. |
| **D** | Client ↔ SENA ↔ cloud voice model | Slightly higher latency than B. **Only compliant option.** |

## How Approach D works

1. Client opens LiveKit session against SENA-hosted LiveKit server
2. SENA backend spawns a LiveKit Agent process per session
3. Agent bridges audio to [[gemini-live-decision]] from AU region servers
4. Agent tool calls and state changes hit FastAPI → Redis / Postgres
5. All audio bytes log-traceable through SENA infrastructure

## Split of responsibilities

- **FastAPI HTTP API** — session lifecycle (start, end, approval decisions)
- **LiveKit Agent process** — conversation, tool calls, STT/TTS streaming
- Clean boundary: HTTP API owns persistence; Agent owns real-time

## Latency budget

Target sub-500ms perceived response. The extra AU-region hop costs ~30-80ms vs direct cloud. Acceptable.

## Related constraints

- [[australian-data-residency]] — the driver
- [[ndis-compliance]] COMPLY-04 — the formal requirement
- [[degradation-ladder]] — covers the case where Gemini Live is unavailable in AU region

## Connections

- Hub: [[Architecture]], [[NDIS]]
- Source: [[src-voice-arch-analysis]], [[src-new-plan]]
- Related: [[voice-service]], [[livekit]], [[gemini-live-decision]]
