---
title: Voice Assistant Repo Research (Source)
type: source
raw_path: "archive/voice-assistant-repo-research.md"
ingested: 2026-04-15
tags: [research, voice, external, source]
---

# Voice Assistant Repo Research (Source Summary)

## Key Takeaways

- Research survey of existing voice assistant open-source repos
- Benchmarks against LiveKit Agents, Pipecat, Vocode, Retell AI
- Informs the Approach D decision and framework selection

## Detailed Summary

Comparative analysis:
- **LiveKit Agents** — winner; WebRTC native, broad model support, Python first-class
- **Pipecat** — alternative; good framework, less mature at the time of research
- **Vocode / Retell** — hosted/SaaS offerings; data residency disqualifies both for NDIS
- **Custom WebRTC + model chaining** — highest flexibility, highest maintenance burden

Findings supported the [[approach-d-architecture]] decision.

## Pages Updated

- [[approach-d-architecture]]
- [[livekit]]

## Connections

- Hub: [[Architecture]]
- Related: [[src-voice-arch-analysis]]
