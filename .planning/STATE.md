# STATE: SENA Voice Assistant

**Project:** SENA Voice Assistant — LiveKit + Gemini Live Overhaul
**Created:** 2026-04-13
**Last Updated:** 2026-04-13

---

## Project Reference

**Core Value:** A support worker — including those with no digital literacy or visual impairment — completes a full participant onboarding or shift case note entirely by speaking, with sub-500ms response latency, without touching a screen.

**Current Focus:** Phase 1 — LiveKit Agents + Gemini Live Foundation

---

## Current Position

| Field | Value |
|-------|-------|
| Current Phase | 1 — LiveKit Agents + Gemini Live Foundation |
| Current Plan | None (planning not yet started) |
| Phase Status | Not started |
| Overall Progress | 0/9 phases complete |

**Progress bar:** `[ ] [ ] [ ] [ ] [ ] [ ] [ ] [ ] [ ]` (0/9)

---

## Phase Summary

| Phase | Name | Status |
|-------|------|--------|
| 1 | LiveKit Agents + Gemini Live Foundation | Not started |
| 2 | Session Orchestrator + State Machine | Not started |
| 3 | Hybrid Context Preloader | Not started |
| 4 | Tool Calling — Non-Blocking Pattern | Not started |
| 5 | Form Intelligence — 7-Screen Gated Flow | Not started |
| 6 | Accessibility Features | Not started |
| 7 | Degradation Ladder | Not started |
| 8 | Case Note Dictation Migration (Flow B) | Not started |
| 9 | NDIS Compliance Layer | Not started |

---

## Accumulated Context

### Architecture Decisions (Already Locked)

- **Approach D (server-mediated audio):** LiveKit Agent on SENA backend subscribes to worker's room audio track, forwards to Gemini Live WebSocket, streams response back. Client never connects to Gemini directly. This is non-negotiable — NDIS compliance.
- **Brownfield migration:** Preserve `voice_repo.py`, `models/db.py`, `redis_service.py`, `approval_service.py`, `event_service.py`, `auth_service.py`. Replace HTTP turn-based routes with LiveKit Agent process.
- **FastAPI stays for session lifecycle:** POST /v1/voice/session (start), POST /v1/voice/session/end, GET /v1/voice/session/{id}. Conversation moves entirely to LiveKit Agent.
- **Gemini Live region risk:** `australia-southeast1` support unconfirmed. Level 2 (Deepgram + Claude Sonnet + ElevenLabs) must be production-ready, not aspirational.
- **Dual agent types:** Onboarding agent (7-screen form) and dictation agent (Flow B case notes) — same LiveKit framework, different system prompts and tools.

### Key Files to Preserve (Do Not Overwrite)

- `sena-ai/services/voice/src/voice/repositories/voice_repo.py` — god node, 26 edges, reuse as-is
- `sena-ai/services/voice/src/voice/models/db.py` — extend, do not replace
- `sena-ai/services/voice/src/voice/services/redis_service.py` — extend for state machine
- `sena-ai/services/voice/src/voice/services/approval_service.py` — preserve unchanged
- `sena-ai/services/voice/src/voice/services/event_service.py` — preserve unchanged
- `sena-ai/services/voice/src/voice/services/auth_service.py` — preserve unchanged

### New Files Required (Across All Phases)

| File | Phase | Purpose |
|------|-------|---------|
| `gemini_agent.py` | 1 (+ updates in 3,4,5,6) | Core LiveKit Agent class |
| `session_state.py` | 2 | 14-state enum + transition validation |
| `context_preloader.py` | 3 | 6-tier token budget assembler |
| `name_alias_map.py` | 3 | Phonetic name matching |
| `voice_validation.py` | 5 | Readback-confirm field validation |
| `degradation_manager.py` | 7 | Circuit breakers + level determination |
| `level2_agent.py` | 7 | Deepgram+Claude+ElevenLabs agent |
| `level3_agent.py` | 7 | Rule-based sequential field prompter |
| `dictation_agent.py` | 8 | Case note dictation agent subclass |
| `audit_logger.py` | 9 | PII-redacting structured logger |
| `consent_service.py` | 9 | Verbal consent capture + persistence |

### Todos

- [ ] Confirm Gemini Live `australia-southeast1` region availability before Phase 1 ships
- [ ] Validate `api_contracts.py` FormState schema (40+ fields) before Phase 5 DB migration
- [ ] Confirm SNS topic ARN and IAM permissions for dictation SNS event (Phase 8)

### Blockers

None active at project start.

---

## Performance Metrics

| Metric | Target | Actual |
|--------|--------|--------|
| Audio round-trip latency (Level 0) | <500ms | TBD |
| Audio round-trip latency (Level 2) | <900ms | TBD |
| Context preload time | <2000ms | TBD |
| Requirements covered | 64/64 | 64/64 |

---

## Session Continuity

**To resume:** Read ROADMAP.md for phase goals and success criteria. Check this STATE.md for current position and accumulated decisions. Start with Phase 1 plan via `/gsd-plan-phase 1`.

**External research:** `voice-assistant-repo-research.md`, `voice_architecture_analysis.md`, `SENA_Architecture_Audit (1).md` in repo root.

---

*State initialized: 2026-04-13*
