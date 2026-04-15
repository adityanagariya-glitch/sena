---
title: NDIS Domain Knowledge
type: hub
tags: [ndis, compliance, domain]
sources:
  - "[[src-architecture-audit]]"
  - "[[src-technical-decisions]]"
  - "[[src-questions-for-client]]"
  - ".planning/REQUIREMENTS.md"
created: 2026-04-15
updated: 2026-04-15
---

# NDIS Domain Knowledge

Map of Content for everything related to the National Disability Insurance Scheme and its implications for the SENA platform.

---

## Core Domain

- [[ndis-overview]] -- what NDIS is, how it works, who the participants and providers are
- [[case-notes]] -- case note requirements, SOAP format, what constitutes a compliant case note

## Compliance & Legal

- [[ndis-compliance]] -- compliance requirements for AI systems operating in NDIS context
- [[australian-data-residency]] -- data sovereignty requirements (Australian Privacy Act APP 8 + APP 11); all audio and PII must transit SENA servers
- [[human-in-the-loop]] -- approval requirements for all AI outputs before submission; manager/admin review workflow

## Data Architecture

- [[multi-tenancy]] -- data isolation requirements (legally mandated, zero cross-tenant leakage); implemented via [[row-level-security]], Redis key prefixes, LiveKit room naming
- [[row-level-security]] -- PostgreSQL Row-Level Security for tenant isolation at the database layer

## Voice-Specific NDIS Concerns

- [[voice-validation]] -- readback-confirm pattern ensuring data accuracy for NDIS records
- [[degradation-ladder]] -- 5-level fallback strategy ensuring service continuity for support workers in the field
- [[session-state-machine]] -- 14-state session lifecycle with NDIS-compliant audit trail

## Requirements Coverage

The NDIS compliance requirements are formalised in `.planning/REQUIREMENTS.md` under the `COMPLY-*` series (Phase 9):
- COMPLY-01: AI I/O audit logging with session_trace_id and tenant_id
- COMPLY-02: PII redaction before structured log emission
- COMPLY-03: Consent recording at session start
- COMPLY-04: Audio always transits SENA backend (never client-direct)
- COMPLY-05: Configurable data retention per tenant (default 90 days)
- COMPLY-06: Multi-tenant isolation (RLS + Redis prefix + LiveKit room prefix)
- COMPLY-07: Cross-tenant access alerts

---

## Connections

- Architecture hub: [[Architecture]]
- Client requirements hub: [[Client-Requirements]]
- Project overview: [[overview]]
