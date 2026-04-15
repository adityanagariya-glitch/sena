---
title: Multi-Tenancy
type: concept
tags: [multi-tenancy, security, architecture, compliance]
sources: ["[[src-technical-decisions]]", "[[src-architecture-audit]]"]
created: 2026-04-15
updated: 2026-04-15
---

# Multi-Tenancy

SENA is a multi-tenant SaaS platform. Each customer (an NDIS service provider) is a **tenant**. Cross-tenant data leakage is a **legal failure**, not just a bug — see [[ndis-compliance]].

## Tenant model (generic, pending client input)

- `tenant_id` is a top-level identifier attached to every user, session, case note, Redis key, and LiveKit room
- Current schema is generic; may need adjustment when client platform finalises their tenant model

## Enforcement layers

| Layer | Mechanism |
|-------|-----------|
| Database | [[row-level-security]] policies on every tenant-scoped table |
| Application | `WHERE tenant_id = :tenant_id` in all repository queries (belt + braces with RLS) |
| Redis | Key prefix `sena:{tenant_id}:{...}` — keys never collide across tenants |
| LiveKit | Room naming `sena:{tenant_id}:{session_id}` — no cross-tenant room join |
| Vector search | Metadata filter on `tenant_id` for all pgvector queries |

## Why belt + braces

RLS alone isn't enough — a missing `SET app.current_tenant` would be catastrophic. Application-level filtering is defence in depth. Both layers must pass for any row to be returned.

## Testing

A dedicated test suite exercises cross-tenant access patterns and expects all of them to fail. See COMPLY-06 and COMPLY-07 in `.planning/REQUIREMENTS.md`.

## Connections

- Hub: [[NDIS]], [[Architecture]]
- Related: [[row-level-security]], [[ndis-compliance]]
