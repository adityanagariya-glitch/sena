---
title: AWS SNS
type: entity
tags: [aws, events, external-service, entity]
sources: ["[[src-architecture-audit]]"]
created: 2026-04-15
updated: 2026-04-15
---

# AWS SNS

Amazon Simple Notification Service. Used as SENA's event publishing layer.

## Where it's used

- **Case note lifecycle events** — `case_note.drafted`, `case_note.approved`, `case_note.rejected`
- **Session events** — potentially, for consumers interested in session starts/ends
- **Compliance audit events** — possible future use for tamper-evident logging

## Why SNS

- AWS-native, AU region available
- Fan-out to SQS or HTTP webhooks — client team can subscribe without SENA coupling to their infra
- Pay-per-use; cheap at our volumes

## Decoupling rationale

Publishing to SNS instead of calling client APIs directly:
- No retry/backoff logic in SENA for downstream failures
- Client team can change consumers without SENA deploys
- Natural place to emit the audit trail required by [[ndis-compliance]]

## Integration

- Published from the service layer on final state transitions
- Topic ARN configured per environment via `SENA_AI_SNS_*` env vars

## Connections

- Hub: [[Architecture]]
- Related: [[approval-workflow]], [[api-contracts]]
