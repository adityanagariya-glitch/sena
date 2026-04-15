---
title: SENA Project Overview
type: topic
tags: [overview, sena, ndis, voice, architecture]
sources:
  - "[[src-architecture-audit]]"
  - "[[src-technical-decisions]]"
  - ".planning/PROJECT.md"
  - ".planning/REQUIREMENTS.md"
created: 2026-04-15
updated: 2026-04-15
---

# SENA Project Overview

## What SENA Is

SENA is an AI-powered multi-tenant SaaS platform for Australian NDIS (National Disability Insurance Scheme) service providers. This repository contains the **AI/ML backend layer only** -- the broader platform covering HR, payroll, shifts, and client management is built by a separate client team. No API contracts exist yet between the two teams.

The core value proposition: a disability support worker -- including those with no digital literacy or visual impairment -- completes a full participant onboarding or shift case note entirely by speaking, with sub-500ms response latency, without touching a screen.

## Current State

**Active service:** The voice service (`sena-ai/services/voice/`) implements Flow B case note dictation. It currently runs as an HTTP turn-based pipeline (POST /session, POST /session/turn, POST /session/end) using AWS Bedrock (Claude 3.5 Sonnet) for LLM processing, LiveKit for voice conferencing, Redis for session state, and PostgreSQL with pgvector for persistence.

**Scaffolded:** The OCR service (`sena-ai/services/ocr/`) exists as a directory but has no implementation yet.

**Shared infrastructure:** A `sena-common` shared library provides database middleware, schemas, and cross-cutting concerns. Docker Compose orchestrates Redis and two PostgreSQL instances (ai-db with pgvector on port 5433, shared-db on port 5434).

**Planned overhaul:** The voice service is being redesigned around LiveKit Agents Framework with Gemini Live native audio (Approach D). This replaces the HTTP turn-based pipeline with a persistent bidirectional audio stream. The overhaul adds a 14-state session state machine, hybrid context preloading (28K token cap, 6 priority tiers), 7-screen gated form filling for personal details, and a 5-level [[degradation-ladder]].

## Key Architectural Choices and Why

| Decision | Rationale |
|----------|-----------|
| [[fastapi-decision\|Python + FastAPI]] | Team expertise, async-first, rapid prototyping |
| [[row-level-security\|Row-Level Security]] | Legally mandated multi-tenant data isolation for NDIS |
| [[pgvector-decision\|pgvector]] | Embeddings/vector search in PostgreSQL, no separate vector DB |
| [[hybrid-search\|Hybrid search]] | Vector + BM25 keyword search for better recall |
| [[approach-d-architecture\|Approach D (LiveKit Agents on SENA backend)]] | All audio transits SENA servers for NDIS compliance; Approaches B/C fail data residency requirements |
| [[gemini-live-decision\|Gemini Live native audio]] | Single model (STT + reasoning + TTS) = lowest latency for <500ms target |
| [[aws-bedrock\|AWS Bedrock (Claude Sonnet)]] | Stays for case note text post-processing and approval; Gemini handles conversational voice layer |
| Split HTTP API from Agent process | FastAPI handles session lifecycle; LiveKit Agent handles conversation -- clean separation |

## Hard Constraints

- **[[multi-tenancy]]:** Zero cross-tenant data leakage -- legally mandated, not optional
- **[[human-in-the-loop]]:** All AI outputs require human approval before submission
- **[[australian-data-residency]]:** Australian Privacy Act APP 8 + APP 11; all audio and PII must transit SENA servers
- **[[ndis-compliance]]:** Consent recording, PII audit logging, data retention policy

## What's Next

### Open Questions

- Gemini Live `australia-southeast1` region support is unconfirmed -- Level 2 fallback (Deepgram + Claude + ElevenLabs) must be production-ready
- No API contracts defined between AI team and client platform team
- Cloud provider deployment decision was blocked on client input
- Team is 2 effective engineers (senior + team lead) plus an intern on guided tasks

### Upcoming Work

The v1 requirements (.planning/REQUIREMENTS.md) define 64 requirements across 9 phases:
1. Infrastructure & Framework (LiveKit Agents, Gemini Live integration)
2. Session Management (14-state machine, Redis persistence)
3. Context Preloading (participant data, token budget guard)
4. Tool Calling (function tools, non-blocking execution)
5. Form Filling (7-screen gated flow, voice validation)
6. Accessibility (pause/resume, camera trigger, incident escalation)
7. Degradation Ladder (5 levels, circuit breakers)
8. Case Note Dictation (Flow B migration to LiveKit Agent)
9. NDIS Compliance (audit logging, PII redaction, consent)

All 64 requirements are currently in **Pending** status.

### v2 (Future)

- RAG/vector search over NDIS policy documents (replacing rule-based lookup)
- Per-session latency dashboards and analytics
- iOS LiveKit SDK integration guide for mobile team

---

## Connections

- Hubs: [[NDIS]], [[Architecture]], [[Client-Requirements]]
- Planning: `.planning/PROJECT.md`, `.planning/REQUIREMENTS.md`
- Code graph: [graphify-out/GRAPH_REPORT.md](../graphify-out/GRAPH_REPORT.md)
