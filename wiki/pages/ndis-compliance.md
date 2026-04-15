---
title: NDIS Compliance
type: concept
tags: [ndis, compliance, legal]
sources: ["[[src-architecture-audit]]", ".planning/REQUIREMENTS.md"]
created: 2026-04-15
updated: 2026-04-15
---

# NDIS Compliance

Compliance requirements for AI systems operating inside NDIS provider workflows.

## Principles

1. **Human accountability** — every billed service and every clinical record traces back to a human who is accountable ([[human-in-the-loop]])
2. **Data sovereignty** — participant data stays in Australia ([[australian-data-residency]])
3. **Tenant isolation** — one provider's data cannot leak to another ([[multi-tenancy]])
4. **Auditability** — everything AI did must be reconstructable
5. **Consent** — participants consent to recording and AI processing

## SENA's compliance requirements (from .planning/REQUIREMENTS.md, Phase 9)

| ID | Requirement |
|----|-------------|
| COMPLY-01 | AI I/O audit logging with `session_trace_id` and `tenant_id` |
| COMPLY-02 | PII redaction before structured log emission |
| COMPLY-03 | Consent recording at session start |
| COMPLY-04 | Audio always transits SENA backend (never client-direct) |
| COMPLY-05 | Configurable data retention per tenant (default 90 days) |
| COMPLY-06 | Multi-tenant isolation (RLS + Redis prefix + LiveKit room prefix) |
| COMPLY-07 | Cross-tenant access alerts |

## Architectural implications

- [[approach-d-architecture]] — only approach that keeps all audio in SENA (compliant with COMPLY-04)
- [[row-level-security]] — enforces COMPLY-06 at the database layer
- [[session-state-machine]] — builds the audit trail needed for COMPLY-01
- [[degradation-ladder]] — ensures availability so workers never resort to non-compliant workarounds

## Connections

- Hub: [[NDIS]]
- Related: [[human-in-the-loop]], [[multi-tenancy]], [[australian-data-residency]]
