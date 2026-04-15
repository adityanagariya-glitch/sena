---
title: Client Requirements & Integration
type: hub
tags: [client, requirements, integration]
sources:
  - "[[src-questions-for-client]]"
  - "[[src-remaining-questions]]"
  - ".planning/PROJECT.md"
created: 2026-04-15
updated: 2026-04-15
---

# Client Requirements & Integration

Map of Content for requirements originating from the client team, integration points, and unresolved questions.

The SENA AI/ML backend is one half of a larger platform. The client team owns HR, payroll, shifts, and client management. The two teams have **no API contracts defined yet**.

---

## Integration Points

- [[client-platform]] -- the separate platform team; what they own (HR, payroll, shifts, client management), how they relate to the AI backend
- [[api-contracts]] -- API integration between AI team and client platform (not yet defined); this is a blocking dependency for end-to-end functionality

## Open Items

- [[open-questions]] -- unresolved questions for the client team (sourced from QUESTIONS_FOR_CLIENT.md and REMAINING_QUESTIONS.md)
- [[deployment-environment]] -- cloud provider decision was blocked pending client input; affects data residency strategy

## Relevant Requirements

From `.planning/REQUIREMENTS.md`:
- **INFRA-03**: Gemini Live audio round-trip validated through SENA servers (not client-direct)
- **SESS-05**: LiveKit room naming convention `sena:{tenant_id}:{session_id}` -- must align with client's tenant model
- **CTX-01**: Context preloader fetches participant data, shift info, form schema -- requires client platform API
- **CTX-05**: Tenant-specific form schema loaded from config -- schema definition needs client input
- **FORM-01**: FormState schema from `api_contracts.py` -- migrated from POC, needs client validation

## Constraints from Client Side

| Constraint | Impact on AI Team |
|-----------|-------------------|
| No API contracts yet | Cannot build integration layer; mock/stub all external data |
| Cloud provider undecided | Cannot finalise deployment architecture or data residency implementation |
| Mobile app owned by client | AI team owns server-side only; LiveKit SDK integration guide is v2 |
| Tenant model undefined | RLS and Redis key prefixes designed generically; may need adjustment |

---

## Connections

- NDIS domain hub: [[NDIS]]
- Architecture hub: [[Architecture]]
- Project overview: [[overview]]
