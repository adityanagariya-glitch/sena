---
title: Multi-Agent System (Planned)
type: concept
tags: [multi-agent, architecture, planned, speculative]
sources: ["[[src-multi-agent-system]]"]
created: 2026-04-15
updated: 2026-04-15
---

# Multi-Agent System (Planned)

Design artefact for a future multi-agent architecture. Not implemented. Partially superseded by direction changes.

## Original idea

Specialist agents per domain, coordinated by a router:

- **Coordinator** — classifies user intent, routes to specialists
- **Dictation agent** — Flow B case note dictation
- **Personal details agent** — onboarding form filling
- **Approval agent** — manager review assistance
- **Compliance agent** — PII redaction, audit annotation

## Why it may still matter

Even with [[gemini-live-decision]] collapsing STT+LLM+TTS into one model, **intent routing** at the application layer remains useful:
- Separate prompts, tools, and context windows per flow
- Clean separation of concerns
- Easier to evolve one flow without regressing another

## Why parts are superseded

> [!warning] Contradiction with current direction
> The original multi-agent design assumed a separate STT + LLM + TTS chain. [[gemini-live-decision]] collapses voice processing into a single model. The multi-agent pattern is thus more about **application-layer orchestration** than voice-layer architecture.

## Connections

- Hub: [[Architecture]]
- Source: [[src-multi-agent-system]]
- Related: [[approach-d-architecture]], [[gemini-live-decision]], [[voice-service]]
