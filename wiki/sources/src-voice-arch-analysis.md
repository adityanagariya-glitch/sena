---
title: Voice Architecture Analysis (Source)
type: source
raw_path: "archive/voice_architecture_analysis.md"
ingested: 2026-04-15
tags: [architecture, voice, analysis, source]
---

# Voice Architecture Analysis (Source Summary)

## Key Takeaways

- Deep-dive analysis of voice architecture approaches
- Evaluates Approaches A (polling), B (client-direct to cloud model), C (hybrid), D (agent on SENA backend)
- Concludes Approach D is the only NDIS-compliant option

## Detailed Summary

**Approach A** — HTTP turn-based (current Flow B). High latency, poor UX.

**Approach B** — Client connects directly to cloud voice model (Gemini Live, OpenAI Realtime). Lowest latency but audio leaves SENA → data residency failure.

**Approach C** — Hybrid: client-direct audio for latency, SENA proxies metadata. Residency risk remains since audio still hits non-SENA-controlled services first.

**Approach D** — LiveKit Agent runs on SENA infrastructure; client connects to SENA; SENA fans audio to Gemini Live from Australian servers. Slightly higher latency than B but residency-compliant.

Recommendation: Approach D. Accept the small latency cost for compliance.

## Pages Updated

- [[approach-d-architecture]]
- [[gemini-live-decision]]
- [[australian-data-residency]]

## Connections

- Hub: [[Architecture]], [[NDIS]]
- Related: [[src-voice-repo-research]], [[src-architecture-audit]]
