---
title: Redis
type: entity
tags: [redis, cache, state, entity]
sources: ["[[src-architecture-audit]]"]
created: 2026-04-15
updated: 2026-04-15
---

# Redis

In-memory data store. Single Redis instance (Docker Compose service) used for multiple concerns in SENA.

See [[redis-usage]] for how SENA applies Redis across session state, rate limiting, distributed locks, and context caching.

## Key conventions

All Redis keys prefixed with `sena:{tenant_id}:` for [[multi-tenancy]]. A missing tenant prefix is a bug.

## Why Redis (not just Postgres)

- **Latency** — sub-ms reads for hot paths (rate limit counters, session state lookup)
- **TTL** — first-class expiry semantics
- **Atomic ops** — INCR, SETNX for locks, Lua scripts for complex atomic flows

## Risks

- Single Redis → single point of failure. Future: consider Redis Cluster or ElastiCache for prod.
- No durability by default — state that must survive a Redis restart goes to Postgres

## Connections

- Hub: [[Architecture]]
- Related: [[redis-usage]], [[session-state-machine]], [[rate-limiting]]
