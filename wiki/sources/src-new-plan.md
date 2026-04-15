---
title: New Plan (Source)
type: source
raw_path: "archive/Extras/new_plan.md"
ingested: 2026-04-15
tags: [planning, historical, source]
---

# New Plan (Source Summary)

## Key Takeaways

- Latest archived plan iteration
- Commits to Approach D + Gemini Live native audio
- Expands voice service requirements to 64 items across 9 phases

## Detailed Summary

Finalises architecture direction:
- **Approach D** chosen (LiveKit Agents on SENA backend)
- **Gemini Live** for conversational voice layer (single model, lowest latency)
- **Bedrock/Claude** retained for case note text post-processing and approval reasoning
- **5-level degradation ladder** for reliability
- **14-state session machine** formalised

Requirements list evolved into `.planning/REQUIREMENTS.md` (64 requirements).

## Pages Updated

- [[approach-d-architecture]]
- [[gemini-live-decision]]
- [[session-state-machine]]
- [[degradation-ladder]]

## Connections

- Related: [[src-revised-plan]], [[src-plan-v2]]
