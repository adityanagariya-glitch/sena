---
title: LiveKit
type: entity
tags: [voice, webrtc, external-service, entity]
sources: ["[[src-voice-repo-research]]", "[[src-architecture-audit]]"]
created: 2026-04-15
updated: 2026-04-15
---

# LiveKit

Open-source WebRTC platform for real-time voice/video. SENA self-hosts LiveKit (or uses LiveKit Cloud) as the audio transport and uses **LiveKit Agents Framework** for server-side agent processes.

## Why LiveKit

- **WebRTC native** — handles NAT traversal, codec selection, jitter buffering for free
- **Python Agents Framework** — first-class Python agent abstraction (vs bolting Python onto Pipecat/Vocode)
- **Self-host friendly** — critical for [[approach-d-architecture]] / [[australian-data-residency]]
- **Healthy ecosystem** — mature client SDKs for web, iOS, Android

## Role in SENA

- **Transport** — audio between support worker client and SENA Agent
- **Room model** — one room per session; naming convention `sena:{tenant_id}:{session_id}` enforces [[multi-tenancy]]
- **Agent framework** — hosts the Python agent process that orchestrates the conversation and tool calls

## Integration details

- Token issuance handled server-side (`POST /v1/voice/session` returns a LiveKit JWT)
- Dev token lifetime short; regenerated per session
- Agent process started on session start, torn down on end

## Rejected alternatives

See [[src-voice-repo-research]] — Pipecat, Vocode, Retell AI all evaluated. LiveKit won on self-host fit + Python story.

## Connections

- Hub: [[Architecture]]
- Related: [[voice-service]], [[approach-d-architecture]], [[session-state-machine]]
- Source: [[src-voice-repo-research]]
