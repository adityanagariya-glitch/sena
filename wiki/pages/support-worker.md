---
title: Support Worker
type: entity
tags: [user, role, ndis, entity]
sources: ["[[src-flow-b]]", "[[src-architecture-audit]]", ".planning/PROJECT.md"]
created: 2026-04-16
updated: 2026-04-16
---

# Support Worker

A support worker is the **primary end user** of the SENA platform. They are disability support professionals employed by NDIS service providers (the tenants) who deliver direct services to [[ndis-participant|NDIS participants]].

## Role in SENA

Support workers interact with SENA primarily through:
1. **[[flow-b-voice-dictation]]** — dictating case notes via voice after delivering a service
2. **[[personal-details-flow]]** — capturing participant personal details via voice-guided form
3. Viewing their own draft case notes pending approval

## RBAC

In the auth system, support workers carry the `support_worker` role:

| Action | Allowed? |
|--------|----------|
| Start voice session | Yes |
| Submit case note for approval | Yes |
| Approve/reject case notes | **No** (manager/admin only) |
| Cross-tenant access | **No** |

Role enforced at every API endpoint via `require_roles(auth, {"support_worker", "manager", "admin"})`.

## UX context

Support workers are often in the field — at a participant's home or in community settings — when they dictate. This means:
- Mobile-first interaction (client-side LiveKit SDK)
- Voice must work on low/variable connectivity → [[degradation-ladder]]
- Minimal cognitive overhead: the AI should ask targeted questions, not just transcribe
- Errors corrected via readback-confirm: [[voice-validation]]

## Connections

- Hub: [[NDIS]], [[Architecture]]
- Related: [[ndis-participant]], [[flow-b-voice-dictation]], [[personal-details-flow]], [[approval-workflow]], [[degradation-ladder]]
- Auth: [[auth-mode-decision]] — support workers authenticate via JWT in production
