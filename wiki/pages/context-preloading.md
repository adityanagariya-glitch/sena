---
title: Context Preloading
type: concept
tags: [context, rag, voice, tokens]
sources: ["[[src-new-plan]]", ".planning/REQUIREMENTS.md"]
created: 2026-04-15
updated: 2026-04-15
---

# Context Preloading

At session start, SENA loads relevant context into the voice agent's prompt before the conversation begins. This avoids mid-turn RAG latency and grounds the model in participant + shift specifics.

## Design

- **28K token cap** — hard budget so model responses stay fast and cheap
- **6 priority tiers** — context ordered by importance; lower tiers dropped if budget exceeds cap
- **Hybrid** — mixes structured data (participant profile, shift info) and unstructured snippets (recent case notes)

## Priority tiers (indicative)

1. **Participant identity + consent status** (always included)
2. **Current shift info** (worker, location, duration, type)
3. **Recent case notes** (last N, truncated)
4. **Form schema** (if doing personal details flow)
5. **NDIS-specific tenant policy snippets** (v2)
6. **Historical patterns** (opt-in, v2)

## Budget guard

Before sending context to model, a guard trims in reverse-priority order until under cap. Logged so we can track when tiers get cut.

## Requirements

`.planning/REQUIREMENTS.md` Phase 3 (CTX-*).

## Connections

- Hub: [[Architecture]]
- Related: [[session-state-machine]], [[voice-service]], [[client-platform]] (data source)
