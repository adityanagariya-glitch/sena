# SENA Voice Assistant — LiveKit + Gemini Live Overhaul

## What This Is

A real-time voice assistant for Australian NDIS disability support workers built on LiveKit Agents Framework with Gemini Live native audio (single model: STT + reasoning + TTS). Replaces the current HTTP turn-based voice service with a persistent bidirectional audio stream. Covers two flows: (1) voice-guided personal details collection (7-screen gated form), and (2) case note dictation (Flow B). All audio transits SENA servers for NDIS compliance and Australian data residency.

## Core Value

A support worker — including those with no digital literacy or visual impairment — completes a full participant onboarding or shift case note entirely by speaking, with sub-500ms response latency, without touching a screen.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] LiveKit Agents + Gemini Live native audio end-to-end audio round-trip
- [ ] 14-state session state machine (INITIALISING → APPROVED) with Redis persistence
- [ ] Hybrid context preload: system prompt assembled before worker speaks (28K token cap, 6 priority tiers)
- [ ] Non-blocking tool calls (WHEN_IDLE / async) — agent keeps talking during lookups
- [ ] 5-level graceful degradation ladder (Gemini Live → Gemini+blocking → Deepgram+Claude+ElevenLabs → rule-based → record-only)
- [ ] 7-screen gated form filling: required fields gate progression, optional fields skippable
- [ ] Voice validation with readback-confirm pattern (all field entries verbally confirmed)
- [ ] Phonetic name alias map (NDIS participant names correctly recognised)
- [ ] Voice-triggered camera + AI description (accessibility — no screen needed)
- [ ] Pause/resume, incident escalation, back-navigation via voice commands
- [ ] NDIS PII audit log (all AI I/O logged with session_trace_id + tenant_id)
- [ ] Multi-tenant isolation (RLS + Redis key prefix by tenant_id)
- [ ] Case note dictation migrated from HTTP turns to LiveKit Agent (Flow B)
- [ ] NDIS compliance: Australian data residency, consent recording, data retention policy

### Out of Scope

- Direct client-to-Gemini audio (Approach B) — FAILS NDIS compliance, audio must transit SENA servers
- LangGraph orchestration in production agent — replaced by LiveKit Agents event model (LangGraph patterns remain in POC for reference)
- Mobile app changes — AI team owns server-side only
- RAG/vector search in v1 — deferred to v2 (NDIS policy lookup via rule-based fallback for now)

## Context

**Existing codebase:** `sena-ai/services/voice/` — HTTP turn-based pipeline (POST /session → POST /session/turn → POST /session/end). This is replaced, not extended.

**Existing assets to migrate/reuse:**
- `poc_onboarding.py` — Working LangGraph + tool calling POC → extract tool patterns, discard LangGraph orchestration
- `voice_repo.py` — SQLAlchemy async data layer → reuse as-is (god node, 26 edges)
- `redis_service.py` — Session state caching → extend for 14-state machine
- `models/db.py` — ORM entities → extend with screen/form state tables

**Architecture decision (Approach D):** LiveKit Agents on SENA backend subscribes to worker's LiveKit room audio track → forwards to Gemini Live WebSocket → streams response audio back. All audio server-side. Reference: `SENA_Architecture_Audit (1).md`.

**Blocking risk:** Gemini Live `australia-southeast1` region support unconfirmed. Level 2 degradation (Deepgram + Claude Sonnet + ElevenLabs) must be production-ready as fallback, not aspirational.

**External repos studied:** gemini-live-quickstart (validation), livekit/agents (framework), python-agents-examples (tool patterns), agent-starter-python (project scaffold), BexTuychiev gist (simplest tool wiring reference). See `voice-assistant-repo-research.md`.

## Constraints

- **Compliance:** Australian Privacy Act APP 8 + APP 11 — all audio and PII must transit and be logged on SENA servers
- **Compliance:** NDIS — human-in-the-loop approval required before case note submission
- **Multi-tenancy:** Zero cross-tenant data leakage — legally mandated, not optional
- **Latency:** Target <500ms end-to-end (Level 0 normal path). Level 2 fallback up to ~900ms acceptable
- **Tech stack:** Python 3.12+, FastAPI, SQLAlchemy async, LiveKit Agents v1.4+, Gemini Live (`google.realtime.RealtimeModel`), Redis, PostgreSQL
- **AWS Bedrock:** Current LLM (Claude Sonnet) stays for case note text post-processing and approval; Gemini Live handles the conversational voice layer
- **Team:** 2 effective engineers (senior + team lead); intern on guided tasks

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| LiveKit Agents framework | Handles WebRTC, audio codec, VAD, interruptions — eliminates custom audio relay code | — Pending |
| Gemini Live native audio | Single model = lowest latency (no STT→LLM→TTS pipeline), best for <500ms target | — Pending (region TBC) |
| Level 2 fallback = Deepgram+Claude+ElevenLabs | All three have AU region support, production-ready, same system prompt via Redis | — Pending |
| Hybrid Preload (massive system prompt) | Eliminates 80% of tool calls → removes dead air for 80% of interactions | — Pending |
| Keep voice_repo.py and SQLAlchemy layer | Preserves multi-tenant RLS, existing DB migrations, audit trail | — Pending |
| Split HTTP API from Agent process | FastAPI handles session lifecycle; LiveKit Agent handles conversation — clean separation | — Pending |

---
*Last updated: 2026-04-13 — initial project creation*
