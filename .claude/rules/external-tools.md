---
description: gstack skill pack + companion CLIs (agent-browser, specify, hivemind) — load when user invokes /qa, /browse, /design-*, /investigate, /office-hours, /retro, /canary, /plan-ceo-review, or asks about browser automation / spec-kit / hivemind. NOT auto-loaded; main thread reads on demand.
trigger_phrases:
  - "gstack"
  - "agent-browser"
  - "/browse"
  - "/qa"
  - "/design-"
  - "/investigate"
  - "/office-hours"
  - "/retro"
  - "/canary"
  - "spec-kit"
  - "specify init"
  - "hivemind"
---

# External Tools (user-global, installed 2026-05-14)

## gstack (skill pack)

Installed at `~/.claude/skills/gstack` (user-global, available in EVERY project). 47 sub-skills + native CLIs (`browse`, `design`, `pdf`).

### SENA-specific routing

| Task | Use SENA agent (NOT gstack) | Use gstack |
|------|------------------------------|------------|
| Plan / refactor / code review touching `services/`, `repositories/`, `prompts/` | `@agent-sena-planner`, `@agent-sena-business-reviewer`, `@agent-sena-security-reviewer` | — |
| Commit / Conventional Commits / PR review of SENA paths | `@agent-sena-git-committer`, `@agent-sena-code-reviewer`, `/review-pr` | — |
| Bug fix / surgical patch on reviewer FAIL | `@agent-sena-bug-fixer` | — |
| Browser testing / QA on a deployed URL / visual diff / accessibility tree | — | `/qa`, `/browse`, `/canary` |
| Design HTML / design consultation / design review of a UI mock | — | `/design-consultation`, `/design-html`, `/design-shotgun` |
| Root-cause debugging methodology / engineering retro | — | `/investigate`, `/retro` |
| Strategic / product-level "should we build this" check | — | `/office-hours`, `/plan-ceo-review` |
| Browser automation (open URL, fill form, screenshot) | — | `agent-browser` CLI OR `/browse` |

### Do NOT

- Use gstack `/review` or `/ship` for SENA-touching diffs — SENA pipeline (`sena-business-reviewer` + `sena-security-reviewer` → `sena-bug-fixer` → `sena-cleaner` → `sena-git-committer`) is canonical for tenant-isolation + NDIS compliance. gstack's reviewers don't know SENA's auto-block signatures.
- Use `mcp__claude-in-chrome__*` MCP tools — `agent-browser` / `/browse` is preferred.

### State + upgrade

- Global state: `~/.gstack/config.yaml`. Telemetry default OFF (`gstack-config set telemetry off|anonymous|community`).
- Upgrade: `/gstack-upgrade` or set `auto_upgrade: true` in config.

## Companion CLIs

- **`agent-browser`** (npm global, v0.27.0) — Chromium-only browser automation. Supports Chrome / Brave / Edge / Chrome for Testing / iOS Safari via Appium / cloud (Browserless, AgentCore). **No Firefox provider.** Run `agent-browser install` once to fetch Chrome for Testing if no Chromium browser detected.
- **`specify`** (uv tool, v0.8.10) — GitHub spec-kit CLI. `specify init <project>` to scaffold `/specify`, `/plan`, `/tasks` slash commands. PATH may need `uv tool update-shell` + shell restart.
- **`hivemind`** (npm global, v0.7.24) — Deeplake's shared-brain plugin. **Package installed but NOT wired.** `hivemind install` opens browser login + ships every session trace to Deeplake cloud. **HELD for SENA** pending Australian data residency decision (NDIS APP 8 + APP 11). Do NOT run `hivemind install` without explicit user override.
