---
title: Open Questions
type: topic
tags: [questions, blocked, open-items]
sources: ["[[src-questions-for-client]]", "[[src-remaining-questions]]"]
created: 2026-04-15
updated: 2026-04-15
---

# Open Questions

Unresolved items that are blocking or shaping active work.

## Client-blocked

| # | Question | Impact |
|---|----------|--------|
| Q1 | Which cloud provider (GCP / AWS / Azure)? | Blocks [[deployment-environment]], OCR provider choice |
| Q2 | Shape of tenant_id? | Affects [[multi-tenancy]] key schemes |
| Q3 | Who owns user management + JWT issuance? | [[auth-mode-decision]] prod mode |
| Q4 | Participant/shift API shape? | [[context-preloading]] depends on it |
| Q5 | Data retention per-tenant configurability? | [[ndis-compliance]] COMPLY-05 implementation |
| Q6 | Mobile app LiveKit SDK integration timeline? | v2 rollout planning |

## Internal / research

| # | Question | Impact |
|---|----------|--------|
| Q7 | Gemini Live `australia-southeast1` availability? | Existence of Level-0 in [[degradation-ladder]] |
| Q8 | Which observability stack (Grafana Cloud / Datadog / AWS CloudWatch / ...)? | Phase-independent but needed for prod |
| Q9 | Prompt eval framework? | Quality gates for LLM outputs |
| Q10 | Cost caps per tenant? | Guardrail vs pricing model |

## How this page stays current

- Items resolved move to a decision page and are removed from here
- New items added during planning iterations
- Reviewed during each milestone kickoff

## Connections

- Hub: [[Client-Requirements]]
- Sources: [[src-questions-for-client]], [[src-remaining-questions]]
