---
title: Session State Machine
type: concept
tags: [session, state-machine, voice, design]
sources: ["[[src-new-plan]]", ".planning/REQUIREMENTS.md"]
created: 2026-04-15
updated: 2026-04-15
---

# Session State Machine

A 14-state machine tracking the lifecycle of a voice session from connect to approved.

## Why formalise it

- Auditability — every transition is logged with timestamp + actor (COMPLY-01)
- Resumability — a mid-session disconnect can resume from a known state
- Fail-soft handoff to [[degradation-ladder]] levels without losing state
- Clear contract for UI state (loading spinners, error views, retry affordances)

## States (indicative — see `.planning/REQUIREMENTS.md` Phase 2)

```
INITIALISING → CONNECTING → PRELOADING → LISTENING → PROCESSING →
RESPONDING → TOOL_CALLING → WAITING_USER → PAUSED → DEGRADING →
COMPILING → AWAITING_APPROVAL → APPROVED | REJECTED
```

(Exact names in code may vary; canonical list lives in the voice service state module.)

## Persistence

State held in [[redis]] (`sena:{tenant_id}:session:{id}:state`) for fast access, mirrored to [[pgvector|PostgreSQL]] on transitions for durability.

## Transition rules

- Only specific transitions are legal (enforced server-side)
- Invalid transitions are rejected + logged as anomalies
- Some transitions trigger side-effects (e.g., entering `COMPILING` kicks off Bedrock compilation; entering `APPROVED` publishes SNS event)

## Connections

- Hub: [[Architecture]], [[NDIS]]
- Related: [[voice-service]], [[approval-workflow]], [[degradation-ladder]]
- Requirements: `.planning/REQUIREMENTS.md` Phase 2 (SESS-*)
