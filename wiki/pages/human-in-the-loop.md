---
title: Human In The Loop
type: concept
tags: [ndis, compliance, approval, core-principle]
sources: ["[[src-architecture-audit]]", "[[src-flow-b]]"]
created: 2026-04-15
updated: 2026-04-15
---

# Human In The Loop

A hard architectural and compliance constraint: **no AI output is ever final without human approval**.

## Why

- NDIS providers are legally accountable for the records they submit
- Clinical/safeguarding notes have real-world consequences (medication, incidents, billing)
- Regulator trust in AI-generated content depends on a clear human sign-off chain

## How it shows up in SENA

1. The AI drafts — case notes, personal-details forms, summaries
2. A human reviews (support worker for their own note, manager for approval)
3. The system records both the draft and the approval decision with timestamps and user IDs
4. Only after approval is the record marked as final and eligible for downstream systems (billing, reporting)

See [[approval-workflow]] for the state machine and roles. The manager/admin role gate is enforced at `POST /v1/approval/decision`.

## What this rules out

- Auto-submission of case notes, ever
- AI-initiated changes to existing finalised records
- Bypassing review for "low-risk" content — no exceptions

## Connections

- Hub: [[NDIS]]
- Related: [[approval-workflow]], [[ndis-compliance]], [[case-notes]]
