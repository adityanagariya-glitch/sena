---
title: SNS Events
type: topic
tags: [sns, events, integration]
sources: ["[[src-architecture-audit]]"]
created: 2026-04-15
updated: 2026-04-15
---

# SNS Events

Event publishing architecture using [[aws-sns]].

## Published events (indicative)

| Event | When | Consumers |
|-------|------|-----------|
| `case_note.drafted` | On session end + compile | Client platform (for UI refresh) |
| `case_note.approved` | On manager approval | Client platform (billing, reporting) |
| `case_note.rejected` | On manager rejection | Client platform (worker notification) |
| `session.started` | On voice session start | Observability / analytics |
| `session.ended` | On voice session end | Observability / analytics |

## Payload shape

- `event_type`
- `tenant_id`
- `session_id` / `case_note_id`
- `timestamp`
- `actor_user_id`
- Minimum payload — consumers fetch details via API, not via event payload (avoids PII in event bus)

## Decoupling rationale

See [[aws-sns]]. SENA publishes; client team subscribes. No retry/backoff coupling; changes on either side don't force coordinated deploys.

## Connections

- Hub: [[Architecture]]
- Related: [[aws-sns]], [[approval-workflow]], [[api-contracts]]
