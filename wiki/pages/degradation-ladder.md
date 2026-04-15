---
title: Degradation Ladder
type: concept
tags: [reliability, voice, resilience]
sources: ["[[src-new-plan]]", ".planning/REQUIREMENTS.md"]
created: 2026-04-15
updated: 2026-04-15
---

# Degradation Ladder

5-level graceful degradation strategy ensuring a support worker in the field can always complete a case note, even when the preferred stack is down.

## Levels

| Level | Stack | Trigger |
|-------|-------|---------|
| **0 — Full** | Gemini Live native audio, real-time | Default |
| **1 — Slow Gemini** | Gemini Live with larger buffers | Latency SLO breached, connection flaky |
| **2 — Chain** | Deepgram STT + Claude + ElevenLabs TTS (all AU) | Gemini Live unavailable (incl. AU region issue) |
| **3 — STT-only** | Deepgram transcription only, no realtime response | LLM providers degraded |
| **4 — Record-only** | Capture audio + transcript locally, compile later | Everything downstream unavailable |

## Why 5 levels

- Level 2 is the critical safety net if Gemini Live lacks AU hosting ([[australian-data-residency]])
- Level 4 means a worker in remote area with poor connectivity still finishes their shift without losing work
- Graded drop preserves as much UX as possible at each step

## Circuit breakers

Each level has its own circuit breaker (DEGRADE-01). Breaker opens on repeated failure, triggering a step down. Closes after a cool-off with successful probe.

## Requirements

`.planning/REQUIREMENTS.md` Phase 7 (DEGRADE-*).

## Connections

- Hub: [[Architecture]], [[NDIS]]
- Related: [[gemini-live-decision]], [[australian-data-residency]], [[session-state-machine]]
