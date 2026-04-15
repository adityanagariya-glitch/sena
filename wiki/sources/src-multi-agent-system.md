---
title: Multi-Agent System Design (Source)
type: source
raw_path: "archive/Extras/MULTI_AGENT_SYSTEM_DESIGN.md"
ingested: 2026-04-15
tags: [multi-agent, architecture, planned, source]
---

# Multi-Agent System Design (Source Summary)

## Key Takeaways

- Design for a future multi-agent architecture
- Specialist agents per domain (dictation, personal details, approval routing, compliance)
- Coordinator/router pattern
- Not yet implemented — design artefact only

## Detailed Summary

Proposed architecture:
- **Coordinator agent** — routes user intent to specialist agents
- **Dictation agent** — handles case note dictation (current Flow B scope)
- **Personal details agent** — structured form-filling for participant onboarding
- **Approval agent** — review assistance for managers
- **Compliance agent** — PII redaction, audit-log annotation

Open issues raised in the design:
- How agents share state (Redis? shared conversation context?)
- Latency budget per hop
- Cost trade-off with Gemini Live single-model approach

Design predates the Approach D / Gemini Live decision. Some content superseded.

> [!warning] Possible contradiction
> Multi-agent design assumed separate STT + LLM + TTS chain. Current direction (Gemini Live native audio) collapses these into a single model, reducing need for some coordination. Multi-agent pattern may still apply at the application layer (intent routing) but not at the voice layer.

## Pages Updated

- [[multi-agent-system]]

## Connections

- Hub: [[Architecture]]
- Related: [[src-voice-arch-analysis]]
