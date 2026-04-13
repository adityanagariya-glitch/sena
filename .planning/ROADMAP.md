# ROADMAP: SENA Voice Assistant — LiveKit + Gemini Live Overhaul

**Project:** SENA Voice Assistant
**Type:** Brownfield migration (HTTP turn-based → LiveKit Agents persistent process)
**Granularity:** Detailed
**Coverage:** 64/64 v1 requirements mapped
**Created:** 2026-04-13

---

## Phases

- [ ] **Phase 1: LiveKit Agents + Gemini Live Foundation** — Basic audio round-trip validated through SENA servers
- [ ] **Phase 2: Session Orchestrator + State Machine** — 14-state machine with Redis persistence and tenant isolation
- [ ] **Phase 3: Hybrid Context Preloader** — System prompt assembled with full participant context before worker speaks
- [ ] **Phase 4: Tool Calling — Non-Blocking Pattern** — Agent calls tools without dead air; form fields update in real-time
- [ ] **Phase 5: Form Intelligence — 7-Screen Gated Flow** — Worker completes 7-screen form entirely by voice
- [ ] **Phase 6: Accessibility Features** — Full session completable without screen interaction
- [ ] **Phase 7: Degradation Ladder** — 5-level graceful degradation with automatic failover
- [ ] **Phase 8: Case Note Dictation Migration (Flow B)** — Case note dictation migrated from HTTP turns to LiveKit Agent
- [ ] **Phase 9: NDIS Compliance Layer** — All compliance requirements met — legal can review

---

## Phase Details

### Phase 1: LiveKit Agents + Gemini Live Foundation
**Goal**: A support worker's voice reaches Gemini Live through SENA's servers and a spoken response returns — the full audio round-trip is server-mediated, not client-direct
**Depends on**: Nothing (first phase)
**Requirements**: INFRA-01, INFRA-02, INFRA-03, INFRA-04, INFRA-05, INFRA-06, VOICE-01, VOICE-02, VOICE-03
**Success Criteria** (what must be TRUE):
  1. A test worker speaks into a LiveKit room and hears a Gemini Live response — audio never leaves SENA's server boundary
  2. The agent process runs persistently as a background worker (uvicorn restart does not kill in-session agents)
  3. VAD detects end of speech without push-to-talk; barge-in interrupts agent mid-response
  4. Audio response returns within <500ms on the Level 0 path under normal conditions
  5. Deepgram + Claude Sonnet + ElevenLabs Level 2 stack is installed and importable (not yet wired, just available)
**Files**:
  - `gemini_agent.py` (new) — Agent class, basic Gemini Live instructions, VAD config, noise cancellation
  - `main.py` (update) — agent worker config, persistent process entrypoint
  - `requirements.txt` / `pyproject.toml` (update) — livekit-agents v1.4+, google-realtime plugin, deepgram, elevenlabs
**Plans**: TBD

### Phase 2: Session Orchestrator + State Machine
**Goal**: Every session has a traceable identity, follows a validated state machine, and survives agent restarts — tenants are isolated at the room and rate-limit level
**Depends on**: Phase 1
**Requirements**: SESS-01, SESS-02, SESS-03, SESS-04, SESS-05, SESS-06, SESS-07, SESS-08, SESS-09, SESS-10
**Success Criteria** (what must be TRUE):
  1. A session created via POST /v1/voice/session has a UUID v7 `session_trace_id` and a LiveKit room named `sena:{tenant_id}:{session_id}`
  2. Attempting an invalid state transition (e.g., ACTIVE → APPROVED directly) is rejected with a logged error
  3. Killing and restarting the agent process leaves an in-progress session resumable with its prior state intact from Redis
  4. A tenant exceeding its rate limit receives a 429 before a session is created; the idempotency key prevents a duplicate if the request is retried
  5. Idle sessions auto-transition to IDLE_TIMEOUT after the configured inactivity window; token-overrun sessions transition to COST_TIMEOUT
**Files**:
  - `session_state.py` (new) — `SessionState` enum, `VALID_TRANSITIONS` dict, timeout handlers
  - `redis_service.py` (extend) — state machine read/write ops, sliding window rate limit, idempotency key check
  - `api/routes.py` (update) — session start spawns agent + writes INITIALISING; wires timeouts
**Plans**: TBD

### Phase 3: Hybrid Context Preloader
**Goal**: Before the agent speaks its first word, it holds the participant's full context — name, goals, form schema, shift info — within a 28K token budget, loaded from cache where possible
**Depends on**: Phase 2
**Requirements**: CTX-01, CTX-02, CTX-03, CTX-04, CTX-05, CTX-06, CTX-07
**Success Criteria** (what must be TRUE):
  1. The agent's first spoken word arrives after preload completes — the system prompt contains participant name, NDIS goals, and form schema before any worker speech is processed
  2. Preload completes within 2 seconds of session start; a Redis cache hit skips the DB query (verified by log timing)
  3. A session started when the participant cache is cold hits the DB exactly once; a second session within 15 min uses cache
  4. Injecting a 40K-token participant record is rejected; the budget guard drops history tiers and stays under 28K
  5. When preload fails (simulated DB timeout), the agent starts with minimal prompt (identity + form fields) and the session is marked DEGRADED in the state machine
**Files**:
  - `context_preloader.py` (new) — 6-priority-tier token budget assembler, 2s timeout, retry-with-minimal fallback
  - `name_alias_map.py` (new) — phonetic name matching, included in system prompt assembly
  - `gemini_agent.py` (update) — wires `context_preloader` at session start, injects assembled prompt
**Plans**: TBD

### Phase 4: Tool Calling — Non-Blocking Pattern
**Goal**: The agent can look up data, update fields, and escalate incidents mid-conversation without the worker hearing silence
**Depends on**: Phase 3
**Requirements**: TOOL-01, TOOL-02, TOOL-03, TOOL-04, TOOL-05, TOOL-06, TOOL-07, VOICE-04, VOICE-05
**Success Criteria** (what must be TRUE):
  1. Calling `update_field` for a spoken value writes to Redis and DB within the same turn; the agent does not wait silently
  2. When a tool call takes longer than 1 second, the agent speaks "One moment..." before the result arrives
  3. `lookup_ndis_policy` returns a rule-based answer for at least the 10 most common NDIS policy queries without an LLM call
  4. `escalate_incident` creates a DB escalation record and the supervisor receives a notification within the session turn
  5. `describe_camera_image` returns a verbal description of a submitted camera frame; transcription accuracy is logged per session
**Files**:
  - `gemini_agent.py` (update) — `@function_tool` decorators for all 5 tools, WHEN_IDLE async pattern, spoken acknowledgement logic
  - `voice_repo.py` (extend) — DB write operations for tool results (field updates, escalation records)
**Plans**: TBD

### Phase 5: Form Intelligence — 7-Screen Gated Flow
**Goal**: A worker can complete the full 7-screen personal details form entirely by voice — advancing screens, skipping optional fields, correcting entries, and navigating back — without touching a screen
**Depends on**: Phase 4
**Requirements**: FORM-01, FORM-02, FORM-03, FORM-04, FORM-05, FORM-06, FORM-07, FORM-08, ACCESS-01, ACCESS-02, ACCESS-05
**Success Criteria** (what must be TRUE):
  1. Saying "next" on a screen with incomplete required fields plays a spoken error listing the missing fields — the screen does not advance
  2. Saying "skip this one" on an optional field skips it with verbal confirmation and moves to the next field
  3. Saying "go back to screen 2" reopens screen 2 in edit mode; previously entered values are preserved
  4. Every field entry triggers a verbal readback ("I heard John Smith — is that right?") before the value is committed
  5. Completing screen 7 triggers a full-form verbal summary; saying "confirm" submits; low-confidence fields are re-read before summary
  6. Changing a participant's date of birth causes the agent to flag downstream fields that depend on age and re-prompt for them
**Files**:
  - `models/db.py` (extend) — FormState as SQLAlchemy model with `screen_id`, `field_confidence`, `skipped_fields`, `completed_screens` columns
  - `voice_validation.py` (new) — readback-confirm pattern for all field types, phonetic alias integration
  - `gemini_agent.py` (update) — screen navigation state machine, gate check logic, cross-screen global facts, stale field detection
**Plans**: TBD
**UI hint**: yes

### Phase 6: Accessibility Features
**Goal**: A worker with visual impairment or no digital literacy can complete an entire session — including taking a photo and escalating an incident — using only their voice
**Depends on**: Phase 5
**Requirements**: ACCESS-03, ACCESS-04, ACCESS-06, ACCESS-07
**Success Criteria** (what must be TRUE):
  1. Saying "pause" suspends the session; saying "resume" or "continue" restarts it from the exact point of suspension
  2. Saying "take a photo" causes the agent to capture a frame from the LiveKit video track and speak a description of what it sees
  3. Saying "I need to escalate this" initiates the escalation flow verbally — no screen tap required; supervisor is notified
  4. A worker with a completely covered screen (verified by test) can complete a full personal details form end-to-end
**Files**:
  - `gemini_agent.py` (update) — pause/resume command handlers, voice-triggered camera integration, verbal escalation flow
  - Vision integration — LiveKit video track frame capture wired to `describe_camera_image` tool
**Plans**: TBD

### Phase 7: Degradation Ladder
**Goal**: If Gemini Live fails, the session continues at a lower capability level — the worker is never stranded in silence
**Depends on**: Phase 6
**Requirements**: DEGRADE-01, DEGRADE-02, DEGRADE-03, DEGRADE-04, DEGRADE-05, DEGRADE-06, DEGRADE-07, DEGRADE-08
**Success Criteria** (what must be TRUE):
  1. Simulating a Gemini Live failure at session creation routes the session to Level 2 (Deepgram + Claude Sonnet + ElevenLabs) without error to the worker
  2. The Level 2 agent uses the same system prompt transferred from Redis — form context and participant data carry over
  3. Level 3 (rule-based sequential prompting) completes a form session without any LLM call — verified by log absence of Bedrock invocations
  4. Level 4 (record-only) tells the worker explicitly that audio is being recorded for later processing; the audio file appears in S3
  5. The `/health/ready` endpoint exposes circuit breaker state for Gemini, Deepgram, Claude, and ElevenLabs as distinct fields
  6. A session started at Level 2 does not switch to Level 0 mid-session even if Gemini recovers
**Files**:
  - `degradation_manager.py` (new) — `DegradationLevel` enum, circuit breakers for all 4 services, level determination at session creation
  - `level2_agent.py` (new) — Deepgram STT + Claude Sonnet + ElevenLabs TTS agent class
  - `level3_agent.py` (new) — rule-based sequential field prompter, zero LLM dependency
  - `api/routes.py` (update) — health endpoint exposes circuit breaker states
**Plans**: TBD

### Phase 8: Case Note Dictation Migration (Flow B)
**Goal**: A support worker dictates a case note by speaking to a LiveKit Agent — no HTTP turn-by-turn loop — and the resulting draft goes through the existing approval workflow unchanged
**Depends on**: Phase 7
**Requirements**: DICT-01, DICT-02, DICT-03, DICT-04, DICT-05
**Success Criteria** (what must be TRUE):
  1. Starting a dictation session type no longer creates an HTTP polling loop — the worker speaks continuously and the draft updates live
  2. The live draft in Redis updates as the worker speaks (visible via GET /v1/voice/session/{id} before session end)
  3. Ending the dictation session creates an ApprovalQueueItem and publishes the SNS event — the approval workflow proceeds identically to the prior implementation
  4. A manager can approve or reject the case note via POST /v1/approval/decision without any change to that endpoint's contract
  5. The dictation agent uses NDIS-specific SOAP format prompting — a test dictation produces a structured note with Situation, Background, Assessment, Plan sections
**Files**:
  - `dictation_agent.py` (new) — Agent subclass for case note flow, NDIS SOAP system prompt
  - `prompts/dictation_prompt.py` (new or update) — NDIS case note structure, SOAP format, NDIS terminology
  - `api/routes.py` (update) — session type discriminator routes to dictation agent vs. onboarding agent
**Plans**: TBD

### Phase 9: NDIS Compliance Layer
**Goal**: All AI input/output is auditable, PII is protected, consent is recorded, and a legal reviewer can confirm NDIS + Australian Privacy Act compliance from logs and test results alone
**Depends on**: Phase 8
**Requirements**: COMPLY-01, COMPLY-02, COMPLY-03, COMPLY-04, COMPLY-05, COMPLY-06, COMPLY-07
**Success Criteria** (what must be TRUE):
  1. Every AI input and output log entry contains `session_trace_id`, `tenant_id`, and timestamp — no PII appears in plaintext in any log line
  2. A session cannot progress past INITIALISING until verbal consent is captured and a consent record is written to the DB
  3. Querying the DB as Tenant A for a session belonging to Tenant B returns zero rows (RLS enforced — verified by compliance test)
  4. The async retention cleanup job removes audio transcripts older than the tenant-configured retention window (default 90 days)
  5. A cross-tenant access attempt (simulated) creates an alert log entry and an audit trail record within the same request cycle
  6. Audio is confirmed server-mediated in all test sessions — no direct client-to-Gemini route exists (network trace verification)
**Files**:
  - `audit_logger.py` (new) — structured log emission with PII redaction, session_trace_id + tenant_id correlation
  - `consent_service.py` (new) — verbal consent capture at session start, DB persistence
  - Compliance test suite (new) — cross-tenant isolation, PII log scanning, audio routing verification, retention policy test
**Plans**: TBD

---

## Progress Table

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. LiveKit Agents + Gemini Live Foundation | 0/0 | Not started | - |
| 2. Session Orchestrator + State Machine | 0/0 | Not started | - |
| 3. Hybrid Context Preloader | 0/0 | Not started | - |
| 4. Tool Calling — Non-Blocking Pattern | 0/0 | Not started | - |
| 5. Form Intelligence — 7-Screen Gated Flow | 0/0 | Not started | - |
| 6. Accessibility Features | 0/0 | Not started | - |
| 7. Degradation Ladder | 0/0 | Not started | - |
| 8. Case Note Dictation Migration (Flow B) | 0/0 | Not started | - |
| 9. NDIS Compliance Layer | 0/0 | Not started | - |

---

## Coverage Map

| Requirement | Phase |
|-------------|-------|
| INFRA-01 | Phase 1 |
| INFRA-02 | Phase 1 |
| INFRA-03 | Phase 1 |
| INFRA-04 | Phase 1 |
| INFRA-05 | Phase 1 |
| INFRA-06 | Phase 1 |
| VOICE-01 | Phase 1 |
| VOICE-02 | Phase 1 |
| VOICE-03 | Phase 1 |
| SESS-01 | Phase 2 |
| SESS-02 | Phase 2 |
| SESS-03 | Phase 2 |
| SESS-04 | Phase 2 |
| SESS-05 | Phase 2 |
| SESS-06 | Phase 2 |
| SESS-07 | Phase 2 |
| SESS-08 | Phase 2 |
| SESS-09 | Phase 2 |
| SESS-10 | Phase 2 |
| CTX-01 | Phase 3 |
| CTX-02 | Phase 3 |
| CTX-03 | Phase 3 |
| CTX-04 | Phase 3 |
| CTX-05 | Phase 3 |
| CTX-06 | Phase 3 |
| CTX-07 | Phase 3 |
| TOOL-01 | Phase 4 |
| TOOL-02 | Phase 4 |
| TOOL-03 | Phase 4 |
| TOOL-04 | Phase 4 |
| TOOL-05 | Phase 4 |
| TOOL-06 | Phase 4 |
| TOOL-07 | Phase 4 |
| VOICE-04 | Phase 4 |
| VOICE-05 | Phase 4 |
| FORM-01 | Phase 5 |
| FORM-02 | Phase 5 |
| FORM-03 | Phase 5 |
| FORM-04 | Phase 5 |
| FORM-05 | Phase 5 |
| FORM-06 | Phase 5 |
| FORM-07 | Phase 5 |
| FORM-08 | Phase 5 |
| ACCESS-01 | Phase 5 |
| ACCESS-02 | Phase 5 |
| ACCESS-05 | Phase 5 |
| ACCESS-03 | Phase 6 |
| ACCESS-04 | Phase 6 |
| ACCESS-06 | Phase 6 |
| ACCESS-07 | Phase 6 |
| DEGRADE-01 | Phase 7 |
| DEGRADE-02 | Phase 7 |
| DEGRADE-03 | Phase 7 |
| DEGRADE-04 | Phase 7 |
| DEGRADE-05 | Phase 7 |
| DEGRADE-06 | Phase 7 |
| DEGRADE-07 | Phase 7 |
| DEGRADE-08 | Phase 7 |
| DICT-01 | Phase 8 |
| DICT-02 | Phase 8 |
| DICT-03 | Phase 8 |
| DICT-04 | Phase 8 |
| DICT-05 | Phase 8 |
| COMPLY-01 | Phase 9 |
| COMPLY-02 | Phase 9 |
| COMPLY-03 | Phase 9 |
| COMPLY-04 | Phase 9 |
| COMPLY-05 | Phase 9 |
| COMPLY-06 | Phase 9 |
| COMPLY-07 | Phase 9 |

**Total mapped: 64/64 v1 requirements**

---

*Roadmap created: 2026-04-13*
