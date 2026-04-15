---
title: Auth Mode Decision
type: decision
tags: [auth, jwt, dev, decided]
sources: [".planning/PROJECT.md", "CLAUDE.md"]
created: 2026-04-15
updated: 2026-04-15
---

# Auth Mode Decision

**Status:** DECIDED (dual-mode, gated by env)

SENA supports two authentication modes, controlled by `SENA_AI_AUTH_MODE`:

| Mode | Use case | Mechanism |
|------|----------|-----------|
| `dev_header` | Local dev, tests | Reads `X-User-Id` and `X-User-Roles` headers directly |
| `jwt` | Staging, production | Validates JWT bearer against configured public key |

## Why dual-mode

- **Dev speed** — header mode = no token issuance in local dev
- **Prod safety** — JWT mode = cryptographically signed, short-lived tokens
- Same request shape either way; only the dependency that validates changes

## Open items

- **JWT signing key ownership** — client platform team owns user management, so they issue tokens; SENA holds the public key. Confirmation pending ([[open-questions]]).
- **Role mapping** — how client team's roles map to SENA roles (`support_worker`, `manager`, `admin`) is undefined.

## Connections

- Hub: [[Architecture]], [[Client-Requirements]]
- Related: [[client-platform]], [[api-contracts]], [[open-questions]]
