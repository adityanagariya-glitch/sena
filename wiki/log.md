---
title: Wiki Log
type: topic
tags: [log, changelog]
created: 2026-04-15
updated: 2026-04-15
---

# Wiki Log

Append-only chronological record of wiki operations. Newest entries at the bottom.

---

## [2026-04-15] bootstrap | Archive Ingestion

Batch ingestion of all archive/ documents to seed the wiki. Sources processed: TECHNICAL_DECISIONS, SENA_Architecture_Audit, FlowB, QUESTIONS_FOR_CLIENT, REMAINING_QUESTIONS, MULTI_AGENT_SYSTEM_DESIGN, plan series (5 files), SPRINT_0_PLAN + related sprint docs, voice-assistant-repo-research, voice_architecture_analysis, reporesearch. Also referenced: .planning/PROJECT.md, .planning/REQUIREMENTS.md.

**Pages created:**
- `wiki/index.md` -- master index with categorised links to all wiki pages
- `wiki/overview.md` -- living synthesis of SENA project state
- `wiki/log.md` -- this file
- `wiki/NDIS.md` -- hub for NDIS domain knowledge
- `wiki/Architecture.md` -- hub for technical architecture
- `wiki/Client-Requirements.md` -- hub for client requirements and integration

**Source summaries:** 15 placeholder entries registered in index (to be expanded on individual ingest).

**Detail pages:** 30+ page stubs registered in index across entities, concepts, decisions, and topics (to be created as individual pages during source-by-source ingest).

---

## [2026-04-16] lint | Full Wiki Lint Pass

Ran full lint pass covering: orphan pages, broken wikilinks, missing pages for frequently-mentioned entities, contradictions between pages, and missing cross-references.

**Findings and fixes:**

- **0 orphan pages** — all pages have ≥2 inbound links. No action needed.
- **Broken wikilink `[[postgres]]`** — fixed in previous session (points to `[[pgvector|PostgreSQL]]`). Confirmed clean.
- **Source status** — updated all 15 source entries in index from "placeholder" → "ingested".
- **11 orphan pages not in index** — added all to index.md (approval-workflow, auth-mode-decision, aws-sns, cloud-provider-decision, flow-b-voice-dictation, llm-provider-decision, ndia, plan-evolution, rate-limiting, sena-common, team-capacity).
- **Contradiction flagged** — `llm-provider-decision.md` described a Gemini Live + Bedrock split stack as decided, but the current codebase uses Bedrock only. Added `[!warning]` callout marking Gemini Live as planned/not-yet-implemented.
- **3 missing pages created** — `ndis-participant.md`, `support-worker.md`, `personal-details-flow.md` (all referenced in code and requirements but had no wiki page).
- **Cross-references added** — Architecture hub updated with approval-workflow, personal-details-flow, flow-b-voice-dictation, support-worker, ndis-participant sections. approval-workflow.md Connections updated to include [[sns-events]] and [[support-worker]].

**Web search gaps flagged (not yet filled — require external sources):**
- Current NDIS Practice Standards version and digital record-keeping requirements
- Australian Privacy Act APP 8/11 specifics for cloud-hosted health/disability data
- LiveKit v2 SDK breaking changes (client team owns mobile SDK integration)
