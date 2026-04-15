---
title: Redis Usage
type: topic
tags: [redis, cache, state]
sources: ["[[src-architecture-audit]]"]
created: 2026-04-15
updated: 2026-04-15
---

# Redis Usage

How SENA uses [[redis]] across the voice service.

## Uses

| Use | Key pattern | TTL |
|-----|-------------|-----|
| Session state | `sena:{tenant_id}:session:{id}:state` | Until session end + audit window |
| Session lock (distributed) | `sena:{tenant_id}:session:{id}:lock` | Short (acquired per operation) |
| Rate limit counter | `sena:{tenant_id}:rate:{user_id}:{window}` | Window duration |
| Idempotency cache | `sena:{tenant_id}:idem:{key}` | Per SLA (e.g., 24h) |
| Context cache (planned) | `sena:{tenant_id}:ctx:{participant_id}` | Short (few minutes) |

All keys prefixed with `sena:{tenant_id}:` — enforces [[multi-tenancy]].

## Patterns

- **SETNX for locks** — simple distributed lock for session-scoped mutations
- **INCR + EXPIRE for rate limiting** — fixed-window counters
- **Lua scripts** for atomic multi-op flows (rare; usually not needed)

## Durability boundary

Redis is cache + fast state. Anything that must survive a Redis failure goes to Postgres. Session state is mirrored to Postgres on transitions (see [[session-state-machine]]).

## Connections

- Hub: [[Architecture]]
- Related: [[redis]], [[session-state-machine]], [[rate-limiting]]
