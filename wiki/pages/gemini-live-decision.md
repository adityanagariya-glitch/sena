---
title: Gemini Live Decision
type: decision
tags: [voice, llm, gemini, decided]
sources: ["[[src-new-plan]]", "[[src-voice-arch-analysis]]"]
created: 2026-04-15
updated: 2026-04-15
---

# Gemini Live Decision

**Status:** DECIDED (with AU-region risk)

**Gemini Live** (Google's native-audio multimodal model) is the chosen conversational voice layer for SENA.

## Why Gemini Live over alternatives

| Option | Verdict |
|--------|---------|
| **Gemini Live (chosen)** | Single model handles STT + reasoning + TTS. Lowest latency possible. |
| OpenAI Realtime | Similar single-model approach. US-only hosting disqualifies under [[australian-data-residency]]. |
| Deepgram + Claude + ElevenLabs (chain) | Mature, AU-deployable, but 3 hops = more latency. Kept as Level 2 fallback in [[degradation-ladder]]. |
| Whisper + Claude + Piper (self-hosted) | Full control, full ops burden. Not viable for 2-person team today. |

## The unresolved risk

Gemini Live availability in `australia-southeast1` is **unconfirmed** at decision time. If it's US-only, routing audio through Gemini violates [[australian-data-residency]].

**Mitigation:** Level 2 degradation (Deepgram + Claude + ElevenLabs, all AU-hosted) must be production-ready, not a best-effort fallback. See [[degradation-ladder]].

## What Bedrock/Claude is still used for

Voice = Gemini Live. But text post-processing stays on [[aws-bedrock]]:
- Case note compilation from conversation transcript
- Approval-reasoning summaries for managers
- Personal-details form extraction

This split is intentional: Gemini owns the conversational turn, Claude owns the structured output.

## Connections

- Hub: [[Architecture]]
- Source: [[src-new-plan]], [[src-voice-arch-analysis]]
- Related: [[approach-d-architecture]], [[degradation-ladder]], [[aws-bedrock]]
