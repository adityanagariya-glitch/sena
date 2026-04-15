---
title: Flow B — Voice Dictation
type: concept
tags: [flow-b, voice, dictation, case-notes]
sources: ["[[src-flow-b]]", "[[src-new-plan]]"]
created: 2026-04-15
updated: 2026-04-15
---

# Flow B — Voice Dictation

The user flow where a support worker dictates a case note at shift end. SENA's flagship feature.

## User story

A disability support worker finishes a shift. They open the app, press record, and speak naturally about what happened: what supports they delivered, how the participant responded, any incidents. The system produces a structured [[case-notes|case note]] draft. A manager reviews and approves it.

## Target experience

- **Hands-free** — full flow via voice for low-literacy or vision-impaired workers
- **Sub-500ms** — response perceptibly instant
- **Interruptible** — worker can correct, restart, pause
- **Fail-soft** — if the best model is unavailable, [[degradation-ladder]] keeps the session going

## Architecture

Currently HTTP turn-based; migrating to LiveKit Agent / Gemini Live under [[approach-d-architecture]].

In the target state:
1. Client opens LiveKit session against SENA server
2. SENA spawns an Agent process
3. Agent bridges audio to Gemini Live (or Level-2 fallback)
4. Agent calls function tools to query participant context, record state changes
5. On session end, transcript compiled into case note by [[aws-bedrock]] Claude
6. [[approval-workflow]] kicks off

## Related flows

- Personal details flow — parallel flow for participant onboarding, shares session infrastructure but uses a [[form-filling]] gated flow instead of free-form dictation

## Requirements

`.planning/REQUIREMENTS.md` Phase 8 (CASENOTE-*) covers Flow B.

## Connections

- Hub: [[NDIS]], [[Architecture]]
- Related: [[case-notes]], [[voice-service]], [[approach-d-architecture]], [[session-state-machine]]
