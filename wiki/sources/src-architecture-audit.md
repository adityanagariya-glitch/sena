---
title: SENA Architecture Audit (Source)
type: source
raw_path: "archive/SENA_Architecture_Audit (1).md"
ingested: 2026-04-15
tags: [architecture, audit, source]
---

# SENA Architecture Audit (Source Summary)

## Key Takeaways

- Full audit of the existing SENA AI backend as of archive date
- Documents the Flow B HTTP turn-based voice pipeline
- Identifies need for LiveKit Agents migration (Approach D)
- Lists data residency risks in Approaches B (client-direct audio) and C (hybrid)

## Detailed Summary

Audit covers:
- **Service inventory** — voice service active, OCR scaffolded, sena-common shared library
- **Data flow** — client → FastAPI → Bedrock + LiveKit + Redis + Postgres
- **Gaps** — no end-to-end audio residency guarantee under Approach B/C; HTTP turn model high-latency
- **Recommendation** — migrate to LiveKit Agents Framework with Gemini Live for sub-500ms latency while keeping all audio through SENA servers

## Pages Updated

- [[voice-service]]
- [[approach-d-architecture]]
- [[gemini-live-decision]]
- [[australian-data-residency]]
- [[degradation-ladder]]

## Connections

- Hub: [[Architecture]], [[NDIS]]
- Related: [[src-flow-b]], [[src-voice-arch-analysis]]
