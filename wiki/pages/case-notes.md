---
title: Case Notes
type: concept
tags: [ndis, case-notes, core-feature]
sources: ["[[src-flow-b]]", ".planning/REQUIREMENTS.md"]
created: 2026-04-15
updated: 2026-04-15
---

# Case Notes

A **case note** is a written record of a support-worker interaction with a participant. It's the primary audit artefact proving that billed services were delivered. Every shift typically produces at least one case note.

## What a compliant case note contains

- **Who** — participant, support worker, anyone else involved
- **When** — date, time, duration
- **Where** — location (home visit, community, facility)
- **What** — what supports were delivered, what happened, participant response
- **Incidents** — any safeguarding concerns, medication events, injuries
- **Next steps** — follow-up actions, risks flagged

Format conventions vary by provider. Many providers use SOAP (Subjective, Objective, Assessment, Plan) or a provider-specific template.

## SENA's approach

**Flow B** ([[flow-b-voice-dictation]]): support worker speaks naturally at the end of a shift. The system:
1. Streams audio through [[livekit]] to the voice agent
2. Transcribes and extracts structured case-note fields
3. Compiles a draft case note
4. Routes to an [[approval-workflow]] where a manager reviews and approves

## Why human approval is non-negotiable

See [[human-in-the-loop]]. NDIS case notes underpin billing and safeguarding — fully automated submission is both regulatorily risky and clinically unsafe.

## Connections

- Hub: [[NDIS]]
- Related: [[flow-b-voice-dictation]], [[approval-workflow]], [[human-in-the-loop]]
- Requirements: `.planning/REQUIREMENTS.md` Phase 8 (CASENOTE-*)
