---
title: API Contracts (External)
type: topic
tags: [integration, contracts, client, blocked]
sources: ["[[src-questions-for-client]]", "[[src-remaining-questions]]"]
created: 2026-04-15
updated: 2026-04-15
---

# API Contracts (External)

Status: **none defined**. This is a blocking dependency for end-to-end SENA functionality.

## Contracts needed

### From client platform → SENA
- Auth: JWT issuance, public key for validation (see [[auth-mode-decision]])
- Participant data API (read by SENA's [[context-preloading]])
- Shift info API (read by context preloader)
- Tenant metadata API (tenant ID, name, configuration, retention policy)
- Consent/permission API (who can be recorded, what data can be processed)

### From SENA → client platform
- SNS events ([[sns-events]]) — drafted, approved, rejected case notes
- Possible webhook callbacks for approval decisions
- Health / status endpoint for client team to surface in their ops UI

## Current workaround

Mocks and stubs. Every service that would call client APIs is wired to a mock for local dev.

## Risks

- Drift between SENA's assumed shape and client's eventual shape
- Rework cost scales with how long contracts stay undefined
- Integration testing can't happen until at least one contract is locked

## Connections

- Hub: [[Client-Requirements]]
- Related: [[client-platform]], [[open-questions]], [[auth-mode-decision]], [[context-preloading]]
