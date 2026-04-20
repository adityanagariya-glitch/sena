## Plan: Hybrid Voice Context for 7-Screen Gated Form

Adopt a hybrid architecture: global session memory for shared facts plus screen-scoped active context for conversational focus. This avoids prompt bloat, preserves natural continuity (names/common facts), and enforces forward progression by required starred fields while allowing optional-field skips and voice back-navigation.

**Steps**
1. Phase 1 - Canonical Form Contract
1. Define one source-of-truth schema for all 7 screens: field id, screen id, required flag (starred), optional flag, dependencies, and validation rule.
2. Add explicit gating semantics: starred fields must be complete before forward navigation; optional fields can be skipped with a spoken confirmation.
3. Add cross-screen field classes: global_identity (name, participant id), global_context (date/location/staff), and local_screen fields.
4. Store this schema in backend config and expose to the voice agent at session start.

2. Phase 2 - Session State and Navigation Model
1. Extend session state to include current_screen, completed_screens, field_values, field_confidence, skipped_optional_fields, and cross_screen_facts.
2. Implement deterministic forward gate: move to next screen only when all required fields in current screen are filled and validated.
3. Implement controlled back-navigation: allow voice commands like "go back to screen 2", reopen prior screen in edit mode, and recompute downstream dependencies before returning forward.
4. Define conflict policy: if editing a back screen invalidates later screen fields, mark affected fields stale and ask for reconfirmation.

3. Phase 3 - Hybrid Context Assembly (Core Decision)
1. Build prompt/context in three tiers per turn:
2. Tier A (always included): compact global memory summary (name, participant, critical risks, session goal).
3. Tier B (always included): active screen packet (required fields, already captured values, missing required, optional pending).
4. Tier C (budget dependent): recent turn window for current screen + minimal carry-forward summary from previous screens.
5. Keep full form state outside the natural-language prompt (Redis/DB state object); pass only compressed slices to the model.
6. Add token budget guard with hard ceilings and fallback summarization when context grows.

4. Phase 4 - Prompt Engineering Pattern
1. Use stable system instructions that do not change per turn: role, safety/compliance, tone, grounding constraints, and no fabrication rules.
2. Use screen-specific instruction overlays: what this screen is for, which required fields remain, and accepted synonyms for natural input.
3. Use a strict response contract: conversational reply + structured extraction payload + completion status + next action recommendation.
4. Add conversational control rules:
5. If user mentions another screen while current screen has missing required fields: acknowledge, store intent, gently redirect.
6. If current screen required fields complete: offer natural transition sentence to next screen.
7. If optional field skipped: confirm skip intent and continue without blocking.

5. Phase 5 - Validation and Progression Engine
1. Implement field-level validators (format, enum, range, dependency) independent of LLM output.
2. Gate transitions using validated field map (not model confidence alone).
3. Apply confidence policy: high-confidence extraction auto-fill; medium asks confirmation; low requests repetition/rephrase.
4. Add per-screen completeness telemetry: required_complete ratio, optional_capture ratio, re-ask count.

6. Phase 6 - Reliability and Provider Strategy (Phased)
1. Phase 6A (now): single provider with robust retries, timeout budget, and structured failure prompts.
2. Phase 6B (next): add fallback provider pipeline with same structured I/O contract so state model stays unchanged.
3. Add circuit-breaker-driven degradation for new sessions while preserving ongoing sessions.

7. Phase 7 - UX and Conversational Naturalness
1. Maintain a global memory sentence the agent can naturally reference across screens (name/pronouns/key facts).
2. Use short conversational recaps on screen entry (what is already known, what still needed).
3. Keep question order flexible within a screen by selecting the next missing field opportunistically from user utterance content.
4. Add explicit voice commands: next, go back, skip optional, summarize this screen, summarize all.

8. Phase 8 - Verification and Rollout
1. Unit tests: screen gate rules, back-navigation state repair, validator behavior, confidence policies.
2. Integration tests: 7-screen happy path, skip optional path, back-edit causing stale downstream fields, resume session mid-way.
3. Load tests: token-budget behavior under long sessions, latency with summarization trigger.
4. UAT with voice users: naturalness score, correction burden, completion time, and error rate.
5. Feature-flag rollout by tenant/team; monitor telemetry and iterate thresholds.

**Relevant files**
- c:/Users/Admin/Downloads/SENA/sena-ai/services/voice/src/voice/prompts/dictation_prompt.py - Reuse prompt builder pattern for layered context packets.
- c:/Users/Admin/Downloads/SENA/sena-ai/services/voice/src/voice/services/dictation_service.py - Reuse session lifecycle and turn-processing orchestration.
- c:/Users/Admin/Downloads/SENA/sena-ai/services/voice/src/voice/services/redis_service.py - Extend state model for screen-level gating and cross-screen facts.
- c:/Users/Admin/Downloads/SENA/sena-ai/services/voice/src/voice/models/schemas.py - Add structured extraction and progression response contracts.
- c:/Users/Admin/Downloads/SENA/sena-ai/services/voice/src/voice/api/routes.py - Add navigation commands and progression endpoints/contracts.
- c:/Users/Admin/Downloads/SENA/api_contracts.py - Reuse deterministic routing and missing-field driven orchestration patterns.
- c:/Users/Admin/Downloads/SENA/PHASE12_GAP_TRACKER.md - Track token budget, extraction confidence, and transport gaps as acceptance criteria.
- c:/Users/Admin/Downloads/SENA/VOICE_ONBOARDING_TIMELINE.md - Reuse sliding-window/summarization budget pattern.

**Verification**
1. Validate required-field gating: cannot advance when any starred field is missing.
2. Validate optional skip flow: skip is explicitly confirmed and does not block progression.
3. Validate back-navigation: editing prior screen correctly marks dependent later fields stale and requests reconfirmation.
4. Validate prompt budget: no turn exceeds configured token threshold; summarization triggers deterministically.
5. Validate conversational continuity: agent references global facts correctly across screens without re-asking unnecessarily.
6. Validate provider degradation: active sessions stable; new sessions degrade according to policy.

**Decisions**
- Confirmed: starred fields are mandatory; non-starred fields may be skipped.
- Confirmed: back-navigation is allowed by voice.
- Chosen approach: hybrid context (global memory + active-screen context), not single giant prompt and not fully isolated per-screen prompt.
- Included scope: architecture, prompt strategy, state model, gating logic, and phased reliability strategy.
- Excluded scope: final provider selection and production auth transport hardening details (kept as adjacent roadmap items).

**Further Considerations**
1. Threshold tuning recommendation: start with strict required gating + medium confidence confirmation, then adjust from telemetry after pilot.
2. Human factors recommendation: define max re-ask count per field to avoid frustrating loops, then offer guided examples.
3. Governance recommendation: maintain a versioned form schema so prompt overlays and validators stay synchronized during form updates.