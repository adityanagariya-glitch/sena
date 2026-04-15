---
title: Session State
type: concept
tags: [session, state, redis]
sources: ["[[src-architecture-audit]]"]
created: 2026-04-15
updated: 2026-04-15
---

# Session State

In-memory session data held in Redis while a voice session is active. See [[session-state-machine]] for the formal state machine.

## What's in session state

- Current machine state (LISTENING, PROCESSING, etc.)
- Conversation turn history (recent turns for context)
- Active degradation level
- Tool-call scratchpad (in-flight function calls)
- Partial form data (if in personal-details flow)

## Key

`sena:{tenant_id}:session:{id}:state` — a Redis hash or JSON blob

## Durability

Mirrored to Postgres on **state transitions** (not every mutation). On Redis failure, the last committed transition is recoverable from Postgres; in-flight turn data is lost (acceptable — user can retry).

## Connections

- Hub: [[Architecture]]
- Related: [[session-state-machine]], [[redis-usage]]
