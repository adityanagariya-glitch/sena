---
title: Team Capacity
type: topic
tags: [team, constraints, operational]
sources: [".planning/PROJECT.md"]
created: 2026-04-15
updated: 2026-04-15
---

# Team Capacity

**2 effective engineers** (senior + team lead) + an intern on guided tasks.

## Why this matters architecturally

Every architectural choice is weighed against operational burden. Low-headcount bias drives:

- **Managed services** over self-hosted (databases, Redis, LiveKit Cloud where possible)
- **One DB** ([[pgvector]] in Postgres) over a dedicated vector DB
- **One framework** ([[fastapi-decision]]) over microframework sprawl
- **Ruff + mypy** for shared conventions (free code-review cycles)
- **Async-first** — scales per-process without adding threading complexity

## What this rules out

- Custom Kubernetes operators
- Self-hosted vector DBs or message queues
- Complex service meshes
- Multi-cloud unless forced by compliance (and even then, minimised)

## Connections

- Hub: [[Architecture]], [[Client-Requirements]]
- Related: [[deployment-environment]], [[fastapi-decision]], [[pgvector-decision]]
