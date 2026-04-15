---
title: Australian Data Residency
type: concept
tags: [compliance, data-residency, legal, privacy]
sources: ["[[src-architecture-audit]]", "[[src-voice-arch-analysis]]"]
created: 2026-04-15
updated: 2026-04-15
---

# Australian Data Residency

Participant and provider data must reside in Australia. This is driven by the Australian Privacy Act, NDIS requirements, and customer contractual obligations.

## Legal anchors

- **APP 8** (Cross-border disclosure of personal information) — disclosing PII offshore creates accountability for the overseas recipient's handling
- **APP 11** (Security of personal information) — reasonable steps to protect PII
- **NDIS Practice Standards** — additional provider-level data-handling requirements

## What this means in practice

- All **audio** must transit SENA servers — not client-direct to overseas AI providers
- All **databases** must run in AU regions
- Model inference must run in AU regions where available
- Observability data (logs, traces) must not carry unredacted PII offshore

## Impact on architecture

- [[approach-d-architecture]] chosen over B/C — only approach that keeps audio in SENA's control
- Cloud provider decision constrained to AU-region offerings ([[deployment-environment]])
- **Risk:** Gemini Live availability in `australia-southeast1` is unconfirmed. If unavailable, the [[degradation-ladder]] Level 2 (Deepgram + Claude + ElevenLabs) must run from AU regions and be production-ready.

## Compliance requirement

`COMPLY-04`: Audio always transits SENA backend.

## Connections

- Hub: [[NDIS]]
- Related: [[approach-d-architecture]], [[degradation-ladder]], [[ndis-compliance]]
