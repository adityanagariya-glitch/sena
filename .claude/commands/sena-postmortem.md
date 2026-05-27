---
description: Direct invocation of @agent-sena-postmortem — blameless incident review. Five Whys → systemic root cause → three-tier action items (prevent / detect / recover) with owners and ETAs. NEVER names individuals. Writes the postmortem doc to .claude/issues-solved/<NNNN>-<slug>.md and adds INDEX.md row. NDIS APP 8/11 reportability check mandatory if PII in play.
allowed-tools: Agent
---

Route the incident to `sena-postmortem` (Agent tool, subagent_type: sena-postmortem).

The agent will:
1. Gather facts (what / timeline AEST / impact + NDIS-reportability / logs / deploys-in-window).
2. Five Whys silently → systemic root cause (never "human error").
3. Distinguish trigger from root cause.
4. Produce three-tier action items (prevent / detect / recover), each with owner + ETA. No "we'll be more careful."
5. Write to `.claude/issues-solved/<NNNN>-<slug>.md` + INDEX.md row.
6. Surface Claude-behaviour patterns to `/sena-learn` for `lessons.md`.

User's args (incident description / ticket link): $ARGUMENTS
