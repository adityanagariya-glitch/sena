---
title: LLM Provider Decision
type: decision
tags: [llm, providers, split, decided]
sources: ["[[src-new-plan]]", "[[src-architecture-audit]]"]
created: 2026-04-15
updated: 2026-04-15
---

# LLM Provider Decision

**Status:** DECIDED (split stack — but see implementation note below)

> [!warning] Implementation vs Plan Divergence
> The split-stack architecture is the **planned** state from design documents. The **current codebase** uses AWS Bedrock (Claude 3.5 Sonnet) only — for both voice turn processing and case note compilation. Gemini Live integration is not yet implemented. Treat this page as the target architecture, not current reality.

SENA uses **two** LLM providers for different layers:

| Layer | Provider | Model | Why |
|-------|----------|-------|-----|
| Conversational voice | [[gemini-live-decision]] | Gemini Live native audio | Single-model STT+reasoning+TTS = lowest latency |
| Text post-processing | [[aws-bedrock]] | Claude 3.5 Sonnet | Proven quality for structured extraction + case note compilation |

## Why not a single provider

- Gemini Live is newer; Claude is more battle-tested for structured text tasks in SENA's prompts
- Gemini Live is voice-optimised; Claude is text-optimised
- Provider diversity reduces single-vendor lock-in risk

## Risks

- Two API surfaces to maintain
- Two prompt-engineering workflows
- Cost across two providers instead of one bulk discount

Acceptable trade-off for the latency + quality gain.

## Connections

- Hub: [[Architecture]]
- Related: [[gemini-live-decision]], [[aws-bedrock]], [[degradation-ladder]]
- Source: [[src-new-plan]]
