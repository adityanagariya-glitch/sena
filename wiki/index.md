---
title: Wiki Index
type: hub
tags: [index, navigation]
created: 2026-04-15
updated: 2026-04-16
---

# SENA Wiki — Master Index

Start here. This index links to every page in the wiki, organised by category.

For a narrative overview of the project, see [[overview]].
For a chronological record of wiki changes, see [[log]].
For code-level structure analysis, see [graphify-out/GRAPH_REPORT.md](../graphify-out/GRAPH_REPORT.md).

---

## Hubs (Maps of Content)

| Hub | Scope |
|-----|-------|
| [[NDIS]] | NDIS domain knowledge, compliance, data residency |
| [[Architecture]] | Technical architecture, service design, infrastructure |
| [[Client-Requirements]] | Client platform integration, open questions |

---

## Sources

Summaries of ingested raw documents live in `wiki/sources/`.

| Source | Raw Path | Status |
|--------|----------|--------|
| [[src-technical-decisions]] | `archive/TECHNICAL_DECISIONS.md` | ingested |
| [[src-architecture-audit]] | `archive/SENA_Architecture_Audit (1).md` | ingested |
| [[src-flow-b]] | `archive/FlowB.md` | ingested |
| [[src-questions-for-client]] | `archive/QUESTIONS_FOR_CLIENT.md` | ingested |
| [[src-remaining-questions]] | `archive/REMAINING_QUESTIONS.md` | ingested |
| [[src-multi-agent-system]] | `archive/MULTI_AGENT_SYSTEM_DESIGN.md` | ingested |
| [[src-plan-v1]] | `archive/plan_v1.md` | ingested |
| [[src-plan-v2]] | `archive/plan_v2.md` | ingested |
| [[src-revised-plan]] | `archive/revised_plan.md` | ingested |
| [[src-new-plan]] | `archive/new_plan.md` | ingested |
| [[src-plan]] | `archive/plan.md` | ingested |
| [[src-sprint-0]] | `archive/SPRINT_0_PLAN.md` | ingested |
| [[src-voice-repo-research]] | `archive/voice-assistant-repo-research.md` | ingested |
| [[src-voice-arch-analysis]] | `archive/voice_architecture_analysis.md` | ingested |
| [[src-reporesearch]] | `archive/reporesearch.md` | ingested |

---

## Pages by Type

### Entities

| Page | Description |
|------|-------------|
| [[voice-service]] | Flow B voice dictation service (primary active service) |
| [[ocr-service]] | Planned OCR/document processing service (scaffolded) |
| [[client-platform]] | The separate client platform team |
| [[ndia]] | National Disability Insurance Agency (NDIS administrator) |
| [[sena-common]] | Shared library (DB, middleware, schemas) |
| [[ndis-participant]] | NDIS participant — subject of case notes, not platform user |
| [[support-worker]] | Primary end user; field-based support professionals |

### Concepts

| Page | Description |
|------|-------------|
| [[ndis-overview]] | What NDIS is and how it works |
| [[ndis-compliance]] | Compliance requirements for AI systems under NDIS |
| [[case-notes]] | Case note requirements, formats (SOAP), approval flow |
| [[multi-tenancy]] | Data isolation requirements (legally mandated) |
| [[human-in-the-loop]] | Approval requirements for all AI outputs |
| [[australian-data-residency]] | Data sovereignty and APP 8/11 requirements |
| [[hybrid-search]] | Vector + BM25 search strategy |
| [[structure-aware-chunking]] | Document processing approach |
| [[multi-agent-system]] | Planned multi-agent architecture |
| [[degradation-ladder]] | 5-level graceful degradation strategy |
| [[session-state-machine]] | 14-state session lifecycle |
| [[context-preloading]] | Hybrid context preload with token budget |
| [[approval-workflow]] | Manager/admin approval workflow for AI outputs |
| [[rate-limiting]] | Rate limiting strategy and implementation |
| [[session-state]] | Session state management in Redis |
| [[plan-evolution]] | How the project plan evolved across iterations |

### Decisions

| Page | Description |
|------|-------------|
| [[fastapi-decision]] | Why Python + FastAPI |
| [[row-level-security]] | RLS for multi-tenant isolation |
| [[pgvector-decision]] | Vector store choice (pgvector) |
| [[aws-bedrock]] | LLM integration via AWS Bedrock (Claude 3.5 Sonnet) |
| [[livekit]] | Real-time voice conferencing choice |
| [[approach-d-architecture]] | LiveKit Agents on SENA backend (Approach D) |
| [[gemini-live-decision]] | Gemini Live native audio for voice layer |
| [[auth-mode-decision]] | Authentication mode decision (dev_header vs JWT) |
| [[llm-provider-decision]] | LLM provider choice (AWS Bedrock / Claude) |
| [[cloud-provider-decision]] | Cloud provider decision (was blocked on client) |
| [[gemini-live-multi-turn-config]] | Gemini Live multi-turn config (google-genai SDK rules, VAD, browser playback) |

### Topics

| Page | Description |
|------|-------------|
| [[redis-usage]] | Session state, rate limiting, distributed locks |
| [[sns-events]] | Event publishing architecture |
| [[monorepo-structure]] | Repo organisation (sena-ai/) |
| [[api-contracts]] | API integration with client team (not yet defined) |
| [[open-questions]] | Unresolved questions for client |
| [[deployment-environment]] | Cloud provider decision (blocked on client) |
| [[form-filling]] | 7-screen gated voice form flow |
| [[voice-validation]] | Readback-confirm pattern, accessibility |
| [[flow-b-voice-dictation]] | Detailed Flow B dictation workflow |
| [[personal-details-flow]] | Parallel voice flow for capturing participant personal details |
| [[aws-sns]] | AWS SNS event publishing details |
| [[team-capacity]] | 2-person team constraint and its architectural impact |

---

> **Maintenance:** Run the lint workflow periodically to find orphan pages, broken wikilinks, and stale content.
