---
title: Approval Workflow
type: concept
tags: [approval, case-notes, compliance, rbac]
sources: ["[[src-flow-b]]", "[[src-architecture-audit]]"]
created: 2026-04-15
updated: 2026-04-15
---

# Approval Workflow

State machine from case-note draft to approved final record. Implements [[human-in-the-loop]].

## States

```
DRAFT → SUBMITTED → APPROVED | REJECTED
                       ↓
                  (on approve: SNS event published)
```

## Roles

| Role | Can do |
|------|--------|
| `support_worker` | Create draft, edit own draft, submit for approval |
| `manager` | Approve, reject, request changes on workers' drafts |
| `admin` | Everything a manager can do + cross-team scope |

Role gate enforced at `POST /v1/approval/decision`.

## Audit artefacts captured

- Draft version history (who edited, when)
- AI-drafted vs human-edited diff
- Approval decision (approver, timestamp, reason if rejected)
- SNS event on approval (downstream consumers = billing, reporting)

## Why an explicit workflow

[[ndis-compliance]] requires provable human sign-off. An implicit "the record exists ∴ someone approved it" is not good enough. The workflow makes the decision point explicit and timestamped.

## Connections

- Hub: [[NDIS]], [[Architecture]]
- Related: [[case-notes]], [[human-in-the-loop]], [[aws-sns]], [[sns-events]], [[support-worker]]
