---
title: Rate Limiting
type: concept
tags: [rate-limiting, redis, abuse-prevention]
sources: ["[[src-architecture-audit]]"]
created: 2026-04-15
updated: 2026-04-15
---

# Rate Limiting

Per-user + per-tenant rate limiting using [[redis]] fixed-window counters.

## Why

- Cap cost damage from a runaway client loop
- Protect downstream LLM providers from bursts that cause throttle/failure
- Fairness across tenants on shared infrastructure

## Approach

Fixed-window counters:
```
key   = sena:{tenant_id}:rate:{user_id}:{window_start}
INCR key
EXPIRE key <window_seconds>
```

If INCR result exceeds limit → 429 response.

## Tiers

- **Per endpoint** — voice session creation, turn processing, approval decisions each have their own limits
- **Per tenant** — aggregated cap to prevent one tenant exhausting shared capacity
- **Global** — absolute ceiling as a final safeguard

## Connections

- Hub: [[Architecture]]
- Related: [[redis-usage]], [[voice-service]]
