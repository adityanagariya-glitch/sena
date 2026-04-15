---
title: sena-common
type: entity
tags: [shared-library, python, entity]
sources: ["[[src-architecture-audit]]"]
created: 2026-04-15
updated: 2026-04-15
---

# sena-common

Shared Python library at `sena-ai/shared/`. Used by all SENA services (currently voice, eventually ocr).

## What lives in sena-common

- **DB middleware** — sets `app.current_tenant` from request context (critical for [[row-level-security]])
- **Auth schemas** — shared Pydantic types for user/tenant/role
- **Common schemas** — cross-service DTOs
- **Observability helpers** — logging, tracing setup with PII redaction
- **Error types** — shared exception hierarchy

## Why a shared library

- Avoid divergence across services on the most security-sensitive pieces (tenant filter, auth)
- Single place to fix a multi-tenant bug
- Workspace install keeps inner-loop fast (`pip install -e ".[dev]"` from `sena-ai/`)

## Connections

- Hub: [[Architecture]]
- Related: [[multi-tenancy]], [[monorepo-structure]]
