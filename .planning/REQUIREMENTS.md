# Requirements: SENA Voice Assistant

**Defined:** 2026-04-13
**Core Value:** Support worker completes full voice session (onboarding or case note) entirely by speaking — sub-500ms latency, no screen required

## v1 Requirements

### Infrastructure & Framework

- [ ] **INFRA-01**: LiveKit Agents v1.4+ installed and integrated into voice service
- [ ] **INFRA-02**: `google.realtime.RealtimeModel` plugin configured for Gemini Live native audio
- [ ] **INFRA-03**: Gemini Live audio round-trip validated end-to-end through SENA servers (NOT client-direct)
- [ ] **INFRA-04**: Agent process runs as persistent background worker (not per-request)
- [ ] **INFRA-05**: Deepgram STT + Claude Sonnet + ElevenLabs TTS stack installed as Level 2 fallback
- [ ] **INFRA-06**: Noise cancellation configured (BVC or Krisp plugin)

### Session Management

- [ ] **SESS-01**: 14-state session machine implemented (`INITIALISING` → `APPROVED` / `RETURNED_FOR_CHANGES`)
- [ ] **SESS-02**: All state transitions validated against allowed-transition map (invalid transitions rejected)
- [ ] **SESS-03**: Session state persisted in Redis with 4h TTL; survives agent restart
- [ ] **SESS-04**: Session created with `session_trace_id` (UUID v7) for log correlation
- [ ] **SESS-05**: LiveKit room named `sena:{tenant_id}:{session_id}` (tenant isolation enforced at room level)
- [ ] **SESS-06**: Idle timeout transitions to `IDLE_TIMEOUT` after configurable inactivity (default 5 min)
- [ ] **SESS-07**: Cost timeout transitions to `COST_TIMEOUT` after configurable token spend
- [ ] **SESS-08**: Connection-lost auto-saves draft to Redis; reconnect resumes from persisted state
- [ ] **SESS-09**: Tenant-level rate limiting on session creation (Redis sliding window)
- [ ] **SESS-10**: Idempotency key prevents duplicate session creation

### Context Preloading

- [ ] **CTX-01**: `context_preloader.py` fetches participant data, shift info, form schema, NDIS goals before worker speaks
- [ ] **CTX-02**: Context assembled within 2s of session start (PRELOAD_TIMEOUT_MS = 2000)
- [ ] **CTX-03**: Token budget guard enforces 28K cap with 6 priority tiers (identity always in; history dropped first)
- [ ] **CTX-04**: Participant context cached in Redis (TTL 15 min) — DB hit only on cache miss
- [ ] **CTX-05**: Tenant-specific form schema loaded from config and injected into system prompt
- [ ] **CTX-06**: On preload failure: retry once with minimal prompt (identity + form fields); log DEGRADED state
- [ ] **CTX-07**: Phonetic name map (`name_alias_map.py`) included in system prompt for correct name recognition

### Voice Processing

- [ ] **VOICE-01**: VAD (Voice Activity Detection) detects end of worker speech without manual push-to-talk
- [ ] **VOICE-02**: Barge-in / interruption supported — worker can interrupt agent mid-response
- [ ] **VOICE-03**: Response audio streamed back to worker within target <500ms (Level 0 normal path)
- [ ] **VOICE-04**: Agent says "One moment..." or equivalent when tool call takes >1s (Level 1 behaviour)
- [ ] **VOICE-05**: Transcription accuracy measured and logged per session (for monitoring)

### Tool Calling

- [ ] **TOOL-01**: `@function_tool` pattern implemented for all agent tools
- [ ] **TOOL-02**: `update_field(field_id, value, confidence)` — updates form state in Redis + DB
- [ ] **TOOL-03**: `get_session_context()` — retrieves current form state for agent reasoning
- [ ] **TOOL-04**: `lookup_ndis_policy(query)` — rule-based policy lookup (v1; RAG in v2)
- [ ] **TOOL-05**: `escalate_incident(description)` — creates escalation record, notifies supervisor
- [ ] **TOOL-06**: `describe_camera_image(image_data)` — receives camera frame, returns AI description verbally
- [ ] **TOOL-07**: Tools execute non-blocking where supported; fallback to blocking with spoken acknowledgement

### Form Filling (7-Screen Gated Flow)

- [ ] **FORM-01**: FormState schema from `api_contracts.py` migrated to SQLAlchemy model with screen/gate tracking
- [ ] **FORM-02**: 7-screen gated navigation: required (starred) fields must be complete before advancing
- [ ] **FORM-03**: Optional fields skippable with spoken confirmation ("skip this one")
- [ ] **FORM-04**: Voice back-navigation: "go back to screen 2" reopens prior screen in edit mode
- [ ] **FORM-05**: Field confidence score tracked per field; low-confidence fields flagged for readback
- [ ] **FORM-06**: Cross-screen global facts (name, participant ID, date) persist across all screens
- [ ] **FORM-07**: Form completion triggers submission flow (readback summary → confirm → submit)
- [ ] **FORM-08**: Stale/conflicting field detection (e.g., DOB changes → downstream fields re-validated)

### Voice Validation & Accessibility

- [ ] **ACCESS-01**: All entered field values read back verbally before confirmation ("I heard John Smith — is that right?")
- [ ] **ACCESS-02**: Verbal readback of full form summary before submission
- [ ] **ACCESS-03**: "Pause" voice command suspends session; "Resume" or "Continue" restarts
- [ ] **ACCESS-04**: Camera trigger via voice ("take a photo") — agent describes image verbally
- [ ] **ACCESS-05**: Name confusion detection via phonetic alias map — agent asks for confirmation on low-confidence matches
- [ ] **ACCESS-06**: Incident escalation triggered via voice ("I need to escalate this")
- [ ] **ACCESS-07**: All accessibility flows work without any screen interaction

### Degradation Ladder

- [ ] **DEGRADE-01**: Circuit breakers implemented for Gemini Live, Deepgram, Claude Sonnet, ElevenLabs
- [ ] **DEGRADE-02**: Level 0 (normal): Gemini Live native audio, non-blocking tools, ~250–320ms
- [ ] **DEGRADE-03**: Level 1 (degraded): Gemini Live + blocking tools only, spoken "one moment" acknowledgement
- [ ] **DEGRADE-04**: Level 2 (alternative): Deepgram STT → Claude Sonnet → ElevenLabs TTS; system prompt transferred from Redis
- [ ] **DEGRADE-05**: Level 3 (minimal): Sequential field-by-field prompting, no LLM reasoning
- [ ] **DEGRADE-06**: Level 4 (emergency): Raw audio recorded to S3, async transcription later; worker told explicitly
- [ ] **DEGRADE-07**: Degradation level determined at session creation — session does not switch levels mid-session
- [ ] **DEGRADE-08**: Circuit breaker state observable via health endpoint

### Case Note Dictation (Flow B Migration)

- [ ] **DICT-01**: Case note dictation session replaced by LiveKit Agent (removes HTTP turn-by-turn loop)
- [ ] **DICT-02**: Dictation-specific system prompt (NDIS case note structure, SOAP format)
- [ ] **DICT-03**: `draft_case_note` tool updates live draft in Redis during session
- [ ] **DICT-04**: Session end compiles final draft, creates ApprovalQueueItem, publishes SNS event
- [ ] **DICT-05**: Approval workflow (manager approve/reject) preserved from existing implementation

### NDIS Compliance

- [ ] **COMPLY-01**: All AI input/output logged with `session_trace_id`, `tenant_id`, timestamp
- [ ] **COMPLY-02**: PII never logged in plaintext — redacted before structured log emission
- [ ] **COMPLY-03**: Consent recorded at session start (verbal consent captured and persisted)
- [ ] **COMPLY-04**: Audio never transits client-to-Gemini directly — always via SENA backend
- [ ] **COMPLY-05**: Data retention policy configurable per tenant (default: 90 days for audio transcripts)
- [ ] **COMPLY-06**: Multi-tenant isolation: RLS on all DB queries, Redis key prefix `{tenant_id}:`, LiveKit room prefix
- [ ] **COMPLY-07**: Cross-tenant data access triggers alert + audit log entry

## v2 Requirements

### RAG & Knowledge Base

- **RAG-01**: `lookup_ndis_policy` backed by vector search over NDIS policy documents
- **RAG-02**: Per-tenant policy document ingestion
- **RAG-03**: Citation tracking — agent references specific policy sections verbally

### Advanced Analytics

- **ANALYTICS-01**: Per-session latency dashboard (P50/P95/P99 by degradation level)
- **ANALYTICS-02**: Field fill rate by screen (which fields cause most retries)
- **ANALYTICS-03**: Noise / accent failure rate tracking

### Mobile SDK Integration

- **MOBILE-01**: iOS LiveKit SDK integration guide for mobile team
- **MOBILE-02**: Push-to-talk mode for noisy environments

## Out of Scope

| Feature | Reason |
|---------|--------|
| Client-direct audio (Approach B/C) | NDIS compliance failure — audio must transit SENA servers |
| LangGraph in production agent | Replaced by LiveKit Agents event model; LangGraph stays in POC only |
| RAG / vector policy lookup | v2 — rule-based lookup sufficient for v1 |
| Mobile app code changes | AI team owns server-side only |
| Real-time supervisor monitoring | v2 — out of v1 scope |
| Multi-language support | English only for v1 |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| INFRA-01 | Phase 1 | Pending |
| INFRA-02 | Phase 1 | Pending |
| INFRA-03 | Phase 1 | Pending |
| INFRA-04 | Phase 1 | Pending |
| INFRA-05 | Phase 1 | Pending |
| INFRA-06 | Phase 1 | Pending |
| VOICE-01 | Phase 1 | Pending |
| VOICE-02 | Phase 1 | Pending |
| VOICE-03 | Phase 1 | Pending |
| SESS-01 | Phase 2 | Pending |
| SESS-02 | Phase 2 | Pending |
| SESS-03 | Phase 2 | Pending |
| SESS-04 | Phase 2 | Pending |
| SESS-05 | Phase 2 | Pending |
| SESS-06 | Phase 2 | Pending |
| SESS-07 | Phase 2 | Pending |
| SESS-08 | Phase 2 | Pending |
| SESS-09 | Phase 2 | Pending |
| SESS-10 | Phase 2 | Pending |
| CTX-01 | Phase 3 | Pending |
| CTX-02 | Phase 3 | Pending |
| CTX-03 | Phase 3 | Pending |
| CTX-04 | Phase 3 | Pending |
| CTX-05 | Phase 3 | Pending |
| CTX-06 | Phase 3 | Pending |
| CTX-07 | Phase 3 | Pending |
| TOOL-01 | Phase 4 | Pending |
| TOOL-02 | Phase 4 | Pending |
| TOOL-03 | Phase 4 | Pending |
| TOOL-04 | Phase 4 | Pending |
| TOOL-05 | Phase 4 | Pending |
| TOOL-06 | Phase 4 | Pending |
| TOOL-07 | Phase 4 | Pending |
| VOICE-04 | Phase 4 | Pending |
| VOICE-05 | Phase 4 | Pending |
| FORM-01 | Phase 5 | Pending |
| FORM-02 | Phase 5 | Pending |
| FORM-03 | Phase 5 | Pending |
| FORM-04 | Phase 5 | Pending |
| FORM-05 | Phase 5 | Pending |
| FORM-06 | Phase 5 | Pending |
| FORM-07 | Phase 5 | Pending |
| FORM-08 | Phase 5 | Pending |
| ACCESS-01 | Phase 5 | Pending |
| ACCESS-02 | Phase 5 | Pending |
| ACCESS-05 | Phase 5 | Pending |
| ACCESS-03 | Phase 6 | Pending |
| ACCESS-04 | Phase 6 | Pending |
| ACCESS-06 | Phase 6 | Pending |
| ACCESS-07 | Phase 6 | Pending |
| DEGRADE-01 | Phase 7 | Pending |
| DEGRADE-02 | Phase 7 | Pending |
| DEGRADE-03 | Phase 7 | Pending |
| DEGRADE-04 | Phase 7 | Pending |
| DEGRADE-05 | Phase 7 | Pending |
| DEGRADE-06 | Phase 7 | Pending |
| DEGRADE-07 | Phase 7 | Pending |
| DEGRADE-08 | Phase 7 | Pending |
| DICT-01 | Phase 8 | Pending |
| DICT-02 | Phase 8 | Pending |
| DICT-03 | Phase 8 | Pending |
| DICT-04 | Phase 8 | Pending |
| DICT-05 | Phase 8 | Pending |
| COMPLY-01 | Phase 9 | Pending |
| COMPLY-02 | Phase 9 | Pending |
| COMPLY-03 | Phase 9 | Pending |
| COMPLY-04 | Phase 9 | Pending |
| COMPLY-05 | Phase 9 | Pending |
| COMPLY-06 | Phase 9 | Pending |
| COMPLY-07 | Phase 9 | Pending |

**Coverage:**
- v1 requirements: 64 total
- Mapped to phases: 64
- Unmapped: 0 ✓

---
*Requirements defined: 2026-04-13*
*Last updated: 2026-04-13 — traceability expanded to per-requirement rows; VOICE split corrected (VOICE-01..03 → Phase 1, VOICE-04..05 → Phase 4); ACCESS split corrected (ACCESS-01,02,05 → Phase 5, ACCESS-03,04,06,07 → Phase 6)*
