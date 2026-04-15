---
title: Client Platform
type: entity
tags: [client, integration, external-team, entity]
sources: ["[[src-questions-for-client]]", ".planning/PROJECT.md"]
created: 2026-04-15
updated: 2026-04-15
---

# Client Platform

The platform built by the **separate client team**, complementary to SENA's AI/ML backend.

## What the client team owns

- HR / payroll
- Shifts / rostering
- Client management (participants, plans)
- User management / auth / identity
- Mobile app (iOS + Android)
- Web frontend

## What SENA owns

- Voice AI (Flow B, personal details)
- Future: OCR, RAG over policy docs
- Embedding/vector search infrastructure
- Multi-tenant data store for AI-specific data

## Shared concerns (no contract yet)

- **Tenant model** — who generates and owns `tenant_id`?
- **Auth** — client team issues JWTs; SENA validates
- **Participant / shift data** — SENA needs read access for [[context-preloading]]
- **Case note submission** — SENA publishes SNS events; client team consumes for billing
- **Mobile audio capture** — client team's app hosts the LiveKit client SDK

## Status

**No API contracts defined.** This is a blocking dependency for end-to-end functionality. Current development uses mocks/stubs.

## Connections

- Hub: [[Client-Requirements]]
- Related: [[api-contracts]], [[open-questions]], [[auth-mode-decision]]
