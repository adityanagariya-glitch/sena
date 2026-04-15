---
title: Technical Architecture
type: hub
tags: [architecture, technical]
sources:
  - "[[src-architecture-audit]]"
  - "[[src-technical-decisions]]"
  - "[[src-flow-b]]"
  - "[[src-multi-agent-system]]"
  - "[[src-voice-repo-research]]"
  - "[[src-voice-arch-analysis]]"
  - ".planning/PROJECT.md"
created: 2026-04-15
updated: 2026-04-15
---

# Technical Architecture

Map of Content for SENA's technical architecture, infrastructure, and design decisions.

For code-level dependency analysis, see [graphify-out/GRAPH_REPORT.md](../graphify-out/GRAPH_REPORT.md).

---

## Services

- [[voice-service]] -- Flow B voice dictation service (primary active service); layered architecture with API, services, repositories, models, prompts
- [[ocr-service]] -- planned OCR/document processing service (scaffolded, not yet implemented)
- [[monorepo-structure]] -- repo organisation (`sena-ai/` with shared library, services, docker-compose)

## Framework & Language Decisions

- [[fastapi-decision]] -- why Python + FastAPI (async-first, team expertise, Pydantic integration)
- [[approach-d-architecture]] -- LiveKit Agents on SENA backend (Approach D); why Approaches B/C were rejected
- [[gemini-live-decision]] -- Gemini Live native audio for the conversational voice layer

## Data Layer

- [[row-level-security]] -- RLS for multi-tenant isolation at the PostgreSQL level
- [[pgvector-decision]] -- vector store choice (pgvector in PostgreSQL, no separate vector DB)
- [[hybrid-search]] -- vector + BM25 keyword search strategy
- [[structure-aware-chunking]] -- document processing approach for RAG (v2)

## External Services

- [[aws-bedrock]] -- LLM integration (Claude 3.5 Sonnet) for case note generation and text post-processing
- [[livekit]] -- real-time voice conferencing; WebRTC, audio codec, VAD, interruption handling
- [[redis-usage]] -- session state, rate limiting, distributed locks, context caching
- [[sns-events]] -- event publishing architecture for case note lifecycle

## Voice Architecture

- [[session-state-machine]] -- 14-state session lifecycle (INITIALISING to APPROVED)
- [[context-preloading]] -- hybrid context preload with 28K token cap and 6 priority tiers
- [[degradation-ladder]] -- 5-level graceful degradation (Gemini Live down to record-only)
- [[form-filling]] -- 7-screen gated form flow with voice navigation
- [[voice-validation]] -- readback-confirm pattern for data accuracy

## Planned

- [[multi-agent-system]] -- planned multi-agent architecture (from MULTI_AGENT_SYSTEM_DESIGN.md)

## Key Patterns

| Pattern | Where Used |
|---------|------------|
| Async-first (AsyncSession, async services) | All DB operations, all service layer |
| Dependency injection | `api/deps.py` -- DB sessions, Redis client |
| Pydantic-settings with env prefix | `core/settings.py` (SENA_AI_ prefix) |
| Repository pattern | `repositories/voice_repo.py` (god node, 26 edges) |
| Circuit breaker | Planned for degradation ladder (DEGRADE-01) |
| Idempotency keys | Planned for session creation (SESS-10) |

---

## Connections

- NDIS domain hub: [[NDIS]]
- Client requirements hub: [[Client-Requirements]]
- Project overview: [[overview]]
- Code graph: [graphify-out/GRAPH_REPORT.md](../graphify-out/GRAPH_REPORT.md)
