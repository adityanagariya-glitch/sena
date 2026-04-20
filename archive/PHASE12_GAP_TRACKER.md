# Phase 1-2 Gap Tracker

Reference plans:
- VOICE_ONBOARDING_TIMELINE.md (execution baseline for Phase 1-2)
- MERGED_SPRINT0_VOICE_EXECUTION_PLAN.md (gates and dependency control)

## Current Assessment Date
- 2026-04-07

## Scope Correction (User Clarification)

This tracker originally covered full Phase 1-2. Per user clarification, the active check is now limited to:
- VOICE_ONBOARDING_TIMELINE.md Phase 1 (Week 1) Contracts & Transport Layer only (24h AI Eng + 16h Integration/Testing).

### Focused Status: Phase 1 Contracts & Transport Layer (24h/16h)

1. API contracts (`FormState`, `ContextPacket`, `FieldUpdate`)
- Status: Complete
- Evidence: Implemented in `api_contracts.py` as Pydantic models and response contracts.

2. LiveKit transport setup and bidirectional WebRTC transport test
- Status: Partially complete
- Evidence: LiveKit token endpoint exists in `api_contracts.py`.
- Gap: No explicit end-to-end bidirectional transport verification evidence (join/publish/receive/disconnect assertions) documented in backend tests.

3. Mock LangGraph orchestrator that echoes dummy field updates to UI
- Status: Partially complete
- Evidence: Mock graph and routing are implemented.
- Gap: Current behavior is primarily next-question routing plus user override echo; dedicated mock extraction echo flow is not explicitly separated as a transport-stage dummy update path.

### Net Result for This Scope
- The specific 24h/16h Phase 1 task is mostly implemented but not fully complete.
- Remaining gaps for this scoped task:
  1. Add/record bidirectional WebRTC transport verification.
  2. Make mock orchestrator behavior explicitly match "echo dummy field updates" contract for integration stage.

## A) Phase 1 Gaps (Timeline vs Current Implementation)

### P1-G1: JWT validation middleware is missing
- Plan source:
  - Phase 1 State Management: "JWT validation & Tenant ID extraction"
- Current evidence:
  - tenant_id is accepted from request body in ContextPacket.
  - No bearer token verification middleware in API layer.
- Risk:
  - Tenant spoofing risk and no production-safe auth boundary.
- Implementation steps:
  1. Add auth settings in environment:
     - JWT_ISSUER, JWT_AUDIENCE, JWT_JWKS_URL, JWT_REQUIRED=true.
  2. Add middleware/dependency in API service:
     - Extract Authorization header.
     - Verify signature via JWKS.
     - Validate issuer, audience, expiry.
  3. Derive tenant_id from token claim (for example: tid/org_id).
  4. Reject mismatches when payload tenant_id != token tenant claim.
  5. Add tests:
     - valid token accepted.
     - missing token rejected.
     - wrong tenant claim rejected.
  6. Feature flag rollout:
     - VOICE_JWT_REQUIRED=false in dev, true in staging/prod.
- Dependency:
  - Merged plan Track B Q3 auth decision.

### P1-G2: LiveKit transport verification is incomplete
- Plan source:
  - Phase 1 Contracts & Transport: bidirectional WebRTC transport test.
- Current evidence:
  - Token endpoint exists.
  - No backend-level transport verification hooks (room join/leave events, media path checks, telemetry assertions).
- Risk:
  - Token generation alone does not prove end-to-end voice transport.
- Implementation steps:
  1. Add LiveKit integration test profile:
     - start local LiveKit in docker-compose or test env.
  2. Implement server-side webhook endpoint for LiveKit events.
  3. Verify flow in tests:
     - token issued -> participant join event -> track published -> disconnect event.
  4. Add metrics:
     - join latency, publish latency, disconnect reason.
  5. Add failure hooks for frontend fallback messaging.
- Dependency:
  - Runtime infra readiness for LiveKit test environment.

### P1-G3: Turn-history memory is only partially implemented
- Plan source:
  - Phase 1 State Management: "form state and turn-history" in Redis.
- Current evidence:
  - Form state is stored with TTL 1h.
  - Structured turn-history list is not persisted as a separate timeline.
- Risk:
  - Harder debugging, replay, quality audit, and context strategy handoff to Phase 2.
- Implementation steps:
  1. Introduce session history key:
     - session:{id}:turns as Redis list/json log.
  2. Store every sync event with:
     - timestamp, event_type, user_message, overrides, agent_response, updates.
  3. Cap list length (for example 100 turns) to prevent unbounded memory.
  4. Add retrieval endpoint for internal debugging.
  5. Add tests for append, ordering, truncation, TTL behavior.
- Dependency:
  - None (can be done now in mock mode).

## B) Phase 2 Gaps (Timeline vs Current Implementation)

### P2-G1: Gemini multimodal streaming is not integrated
- Plan source:
  - Phase 2 Cognitive Core: Vertex AI Gemini multimodal direct audio-in.
- Current evidence:
  - Extraction node is mock pass-through.
  - Separate POC uses ChatOpenAI gpt-4o for text interactions.
- Risk:
  - Voice cognitive path is not production representative.
- Implementation steps:
  1. Add provider adapter interface:
     - transcribe_and_extract(audio_chunk, context) -> typed extraction output.
  2. Implement Gemini adapter (Vertex client) behind VOICE_PROVIDER_MODE=live.
  3. Keep mock adapter for deterministic tests.
  4. Add integration tests with recorded sample audio.
  5. Add timeout and retry policy per request.
- Dependency:
  - Merged plan Q1 cloud/provider decision + model access verification.

### P2-G2: Deterministic typed extraction pipeline is missing
- Plan source:
  - Phase 2 Routing & Extraction: parse model output into strict FieldUpdate list.
- Current evidence:
  - updates are currently user override echoes (source=user_correction).
  - No parser from model output -> FieldUpdateItem with confidence/source.
- Risk:
  - No trustworthy AI extraction path; no confidence-driven UX.
- Implementation steps:
  1. Define extraction schema contract:
     - field_id, value, confidence, source, evidence_span.
  2. Add validator/parser layer:
     - rejects unknown fields and malformed values.
  3. Add reconciliation logic:
     - AI extraction vs existing form state vs user override precedence.
  4. Add confidence thresholds:
     - auto-apply above threshold, ask confirmation below threshold.
  5. Add deterministic unit tests with fixed model payload fixtures.
- Dependency:
  - Cognitive provider integration (can start with mock fixtures now).

### P2-G3: Sliding Window Context Manager is missing
- Plan source:
  - Phase 2 Cognitive Core: summarize after 5 turns, stay under budget.
- Current evidence:
  - Full message list is reused without summarization policy.
- Risk:
  - Token growth, latency increases, context degradation.
- Implementation steps:
  1. Add conversation memory module:
     - raw_turns, summary_text, rolling_window.
  2. Policy:
     - after N turns (default 5), summarize older turns.
  3. Prompt assembly:
     - system + objective + tenant context + summary + recent N turns.
  4. Persist summary + window metadata in Redis.
  5. Add tests for summary trigger and token budget enforcement.
- Dependency:
  - None (implement now with mock summarizer, then swap to model summarizer).

### P2-G4: TTS synthesis path is missing
- Plan source:
  - Phase 2 Routing & Extraction: wire TTS delivery path (if needed).
- Current evidence:
  - Text response generation exists; no TTS output endpoint or stream path.
- Risk:
  - Voice round-trip not complete for production UX.
- Implementation steps:
  1. Add speech output interface:
     - synthesize(text, voice_profile) -> audio bytes/URL.
  2. Add provider adapters (mock + live).
  3. Add endpoint/stream event to return audio response metadata.
  4. Add caching for repeated prompts.
  5. Add latency/quality metrics per synthesis call.
- Dependency:
  - Provider decision (Q1) and transport finalization.

### P2-G5: Persona prompt package is not formalized
- Plan source:
  - Phase 2 Cognitive Core: explicit user_persona, tenant_identity, active_objective prompts.
- Current evidence:
  - POC system prompt exists, but no formal prompt package or versioned prompt config tied to API path.
- Risk:
  - Prompt drift and inconsistent behavior across environments.
- Implementation steps:
  1. Externalize prompts to versioned config files.
  2. Split prompts into components:
     - persona, compliance constraints, objective, response style.
  3. Add prompt version in response metadata for traceability.
  4. Add regression tests with golden conversation fixtures.
- Dependency:
  - None.

## C) Separate Missed Items From Merged Plan Gates (Affecting Phase 1-2 Promotion)

These items are not all coding tasks inside Phase 1-2, but missing them blocks promotion to live/staging.

### M-GATE-1: Track B Q1/Q2/Q3 not documented as resolved
- Q1 cloud/provider choice
- Q2 integration pattern choice
- Q3 auth/JWT claim design
- Impact:
  - Blocks live provider integration, HITL integration, and production auth closure.
- Future steps:
  1. Create decision record file with approved answers.
  2. Add architecture consequences and owner sign-off.
  3. Link each decision to feature flags and backlog tasks.

### M-GATE-2: Sprint 0 Must Gate A still open in merged plan
- Baseline migrations runnable
- Tenant isolation test green
- No-tenant rejection tests green
- Impact:
  - Prevents safe promotion from mock to live.
- Future steps:
  1. Add CI checks for migration apply + rollback smoke test.
  2. Add isolated integration tests for tenant rejection/auth mismatch.
  3. Make Gate A checklist part of release criteria.

### M-GATE-3: Sprint 0 Should Gate B open (cloud, CI/CD, staging)
- Cloud and managed Postgres provisioned
- CI pipeline enforced
- Model access verified
- Staging deployment healthy
- Impact:
  - Phase 2 live testing and UAT cannot be considered complete.
- Future steps:
  1. Provision AU-region staging resources.
  2. Add pipeline stages: lint -> test -> build -> deploy -> smoke test.
  3. Add synthetic monitoring for voice endpoints.

## D) Priority Order To Close Gaps

1. P1-G1 JWT middleware and tenant claim enforcement
2. P1-G3 turn-history persistence
3. P2-G2 typed extraction parser and reconciliation
4. P2-G3 sliding window context manager
5. P2-G1 live provider adapter (after Q1)
6. P2-G4 TTS path (after provider finalization)
7. P2-G5 prompt package/versioning
8. Merged gate closure tasks (M-GATE-1/2/3) in parallel

## E) Suggested Tracking Fields (for ongoing maintenance)

For each gap above, track:
- Owner
- Status (Not Started / In Progress / Blocked / Done)
- Target Date
- Dependency
- PR Link
- Test Evidence
- Rollout Flag
