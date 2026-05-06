# PRD: Cross-Screen Shared Context for Onboarding Voice

## Problem Statement

When a participant on the onboarding voice flow advances from one screen to the next, the assistant forgets everything they just said. Each screen change creates a new WebSocket session and a new system prompt; nothing carries forward except whatever the mobile app explicitly sends back. So the participant who just spent ten minutes on the Personal Details screen telling the assistant about their goals, their family, their anxiety about NDIS plan dates, opens the next screen and the assistant greets them like a stranger. The conversation feels cold, the participant has to repeat themselves, and the trust they built with the assistant evaporates at every screen boundary.

## Solution

The assistant remembers what the same participant told it on prior screens — within a single onboarding journey — and can reference earlier disclosures naturally on later screens without re-asking. When a screen finishes, a structured summary of what was captured is written to a per-participant context bucket in Redis. When the next screen opens for that same participant, the bucket is read and woven into the assistant's system prompt before the first word is spoken. The participant feels heard. They don't repeat themselves. The handoff between screens is seamless even if a different staff member resumes the session, because the context is bound to the participant, not the operator.

The information that matters most for tone and continuity — name, date of birth, gender, goals, hobbies, interests — is preserved verbatim. Everything else captured on the screen is preserved losslessly under shorter aliases, so the prompt stays compact but no information is dropped. No LLM summarization is used in v1; everything is deterministic.

## User Stories

1. As a **participant** completing NDIS onboarding, I want the assistant on Screen 2 to know my name and goals from Screen 1, so that I don't have to introduce myself twice.
2. As a **participant** with anxiety about disclosing personal details, I want the assistant to remember sensitive things I've already shared, so that I'm not forced to repeat them at every step.
3. As a **participant**, I want the assistant on the medical screen to gently reference a hobby I mentioned earlier (e.g. "you mentioned gardening — does that come up in your weekly routine?"), so that the conversation feels natural and not transactional.
4. As a **participant** on a multi-day onboarding, I want the assistant tomorrow to still know what I said today, so that I can pause and resume without losing rapport.
5. As a **participant** who restarts onboarding more than seven days later, I expect a fresh start, so that I'm not surprised by the assistant referencing things I said long ago in a different context.
6. As a **support worker** taking over onboarding mid-flow for a participant another staff member started, I want the assistant to know what the participant has already shared, so that the handoff is invisible to the participant.
7. As a **support worker**, I never want context from one participant to leak into another participant's session, so that I can trust the system with sensitive disability information.
8. As a **tenant administrator**, I want absolute confidence that another tenant cannot read my participants' summaries, so that the multi-tenant guarantee remains intact.
9. As a **mobile app developer** integrating with the onboarding API, I want the prior-screen summaries to be populated automatically by the server when I create a new session, so that I don't have to track and resend them client-side.
10. As a **mobile app developer**, I want the option to override the auto-populated summaries by sending my own `prior_pages` in the create-session request, so that the app remains the source of truth when it has fresher data.
11. As a **backend engineer**, I want the cross-screen context feature to be toggleable with a single environment flag, so that I can disable it instantly if it causes prompt-budget issues in production.
12. As a **backend engineer**, I want the new Redis keys to be tenant-prefixed by construction, so that an attacker who guesses a participant ID cannot read another tenant's bucket.
13. As a **backend engineer**, I want the underlying summarization logic to be a pure function with no I/O, so that I can unit-test it exhaustively without standing up Redis or Gemini.
14. As an **assistant prompt author**, I want the prior-screen block rendered as readable narrative rather than a JSON dump, so that Gemini Live treats it as background tone rather than as instructions.
15. As an **assistant prompt author**, I want the prior-screen block hidden entirely on the very first screen of an onboarding journey, so that the prompt isn't bloated with empty placeholders.
16. As an **assistant prompt author**, I want to cap how many prior screens are inlined verbatim (default: last 5), with older ones rendered only as their compressed line, so that the system prompt cannot grow unboundedly.
17. As a **participant** mid-flow whose connection drops between screens, I want the next session to still see what I told the assistant on the screen I just left, so that a network blip doesn't cost me my place in the conversation.
18. As a **support worker** reviewing audit logs, I never want a participant's transcript or summary to be enumerable without already knowing both their tenant and participant identifiers, so that the bucket is unreachable from a guessed key alone.
19. As an **on-call engineer**, I want a debug command to inspect a participant's bucket so I can diagnose "the assistant forgot me" reports, so that support tickets are resolvable in minutes not hours.
20. As a **product owner**, I want the rollback path to be a single environment flag with no schema migration, so that we can ship boldly and retreat cheaply.
21. As a **QA tester**, I want a deterministic test that proves compress→decompress round-trips byte-equivalently, so that I can be certain "lossless" actually means lossless.
22. As a **security reviewer**, I want the GET state endpoint to validate that the caller owns the session being read, so that the latent isolation gap closes as part of this feature rather than lingering.
23. As a **support worker**, I want the assistant on the consent screen to know what concerns the participant raised on earlier screens, so that I can flag concerns the participant raised but the form fields didn't capture.
24. As a **support worker** filling in for a colleague, I want the bucket to be keyed to the participant rather than to me, so that my colleague's groundwork is not invisible to me.
25. As a **finance owner watching token spend**, I want v1 to use zero LLM calls for summarization, so that this feature has no per-step inference cost.

## Implementation Decisions

### Modules

Six modules in total — three new, three modified. The split is deliberate: one **deep** module owns all the summarization and rendering logic with a simple stateless interface, and a thin repository owns all the Redis I/O. Lifecycle hooks at the API boundary do the orchestration but contain no business logic.

- **Cross-Screen Context (deep, pure)** — the single source of truth for what a "step summary" looks like, how form-state values get split into verbatim and compressed buckets, how the compression encodes (key alias map) and decodes (round-trippable), and how a list of summaries renders into the natural-language prompt block. Stateless. No I/O. Driven by a hand-tuned constant table of verbatim field names and a deterministic key-alias table. Exported interface is tiny: build a summary from a completed FormState, render a list of summaries to prompt text. Everything else is internal.
- **User Context Repository** — the only thing that touches Redis for cross-screen state. Owns the Hash-per-participant of step summaries and the Set-per-participant of session IDs. Owns the TTL discipline (7 days, refreshed on every write). Tenant ID is a required positional argument on every method; there is no overload that omits it, so calls cannot accidentally cross tenants.
- **Cross-Screen Models** — Pydantic types that flow between the pure module and the repository: `StepSummary`, `CrossScreenContext`. Versioned schema with a top-level `schema_version` field so future migrations can be detected.
- **Prompt Builder integration (modify)** — adds a single `__CROSS_SCREEN_SUMMARY__` placeholder, rendered only when the bucket is non-empty. Injection point sits between the live state JSON and the current screen context, so the model reads it as background before the active screen's instructions.
- **Session Lifecycle hooks (modify routes + ws_routes)** — three integration points: on session create, hydrate `bootstrap.prior_pages` from the repo unless the client supplied it; on `/complete`, persist a `StepSummary` for the just-finished step; on clean WebSocket close (when no `/complete` came in), best-effort flush a summary for the same step. The flush-on-close path is idempotent on `(participant_id, step_number)` so a complete-followed-by-close does not write twice.
- **Auth guard (modify state_repo)** — `assert_session_owner(session_id, tenant_id, participant_id)`. Called from GET state, PUT state, and the new context paths. Returns a 403 on mismatch. Folded in here because closing the latent gap is cheaper while these call sites are already being touched.

### Identity & isolation

- The shared-context bucket key is `(tenant_id, participant_id)`. This was chosen so a colleague taking over a participant's onboarding sees the prior conversation. A stricter `(tenant_id, participant_id, user_id)` scoping was considered and rejected because operator handoff is the more common case than operator privacy.
- `tenant_id` is taken from the authenticated context, never from a request body. This eliminates tenant-spoofing via crafted JSON.
- Redis keys are tenant-prefixed by construction. Even if an attacker correctly guesses a `participant_id`, they still cannot read or enumerate without also knowing the `tenant_id`.
- The pre-existing convention of "guess the session UUID4 and read the transcript" is patched as a fold-in: the auth guard makes session reads require ownership.

### Storage

- Redis only. The onboarding service is Redis-only by hard architectural rule (the application backend is the database of record; this service holds ephemeral conversational state). No Postgres, no file. Multi-instance deploys keep working because Redis is the shared state.
- TTL is 7 days, refreshed on every write. This covers a multi-day onboarding journey while still giving stale buckets a natural expiry. Anything longer-horizon is the application backend's responsibility, not ours.

### Summarization rules

- **Verbatim fields**: `name`, `dob`, `gender`, `goals`, `hobbies`, `interests`. Their values pass through to the summary unchanged. These were chosen because they are the highest-signal fields for warmth and conversational continuity.
- **Compressed fields**: every other populated field. Encoded via a deterministic key-alias map (a constant table inside the pure module) plus compact JSON without whitespace, nulls, or empty arrays. New fields the alias table doesn't know about fall back to a deterministic three-letter abbreviation.
- **Lossless guarantee**: compression is byte-equivalent under decompress (modulo key order). This is asserted by a property test, not just an example test.
- **No LLM**: v1 spends zero inference tokens on summarization. v2 may revisit this once we have data on what the assistant actually misses.

### Prompt rendering

- Rendered as a readable narrative block titled "EARLIER IN THIS ONBOARDING (do not re-ask, reference naturally if relevant)". Gemini Live treats narrative system context better than nested JSON for tone purposes.
- Each prior step renders as a labeled paragraph: step number, step label, time-since-completion, verbatim block, then the compressed string. The newest 5 steps inline verbatim; older ones collapse to just the compressed line.
- Hidden entirely when the bucket is empty.

### API contract changes (additive only)

- **Create session response**: `bootstrap.prior_pages` is now auto-populated from the repo if the client did not supply it. If the client supplies `prior_pages`, the client wins (forward-compatibility, allows manual override during testing).
- **Complete session**: persists a `StepSummary` to the bucket before firing the existing webhook. Webhook contract is unchanged.
- **WebSocket close**: a successful close (after a finished step) writes a best-effort summary if `/complete` did not run. No new events on the WS protocol.
- **State endpoints**: GET and PUT now reject 403 when the caller does not own the session — a behavior change that hardens an existing latent gap.

### Rollback

- Environment flag `ONBOARDING_CROSS_SCREEN_CONTEXT_ENABLED` (default true). When false, the prompt-builder skips injection and the lifecycle hooks skip writes. No schema migration. Backout is a single env change and a restart.

## Testing Decisions

A good test here verifies external behavior — what calling code sees — not the internals of compression or rendering. We test that compress-then-decompress round-trips a payload byte-equivalently, not that compression chose any particular alias. We test that a populated bucket renders a prompt block containing the participant's name, not that the rendering used any particular punctuation.

### What gets tested

Per the user's decision: only the **Cross-Screen Context pure module** has dedicated unit tests in this PRD. The other modules ride on the existing test suite plus manual end-to-end verification.

For the pure module, the tests are:

1. **Round-trip property test**: any structurally valid FormState, when summarized and then decompressed, recovers a payload byte-equivalent to the original residual (modulo key order). This is the core "lossless" guarantee.
2. **Verbatim passthrough**: when the six verbatim fields are present in input, they appear unchanged in the summary's verbatim block.
3. **Empty FormState**: an empty FormState produces an empty summary object — never `None`, never an exception.
4. **Render snapshot**: rendering a small fixture list of summaries produces a stable, expected text shape (intent: catch accidental wording drift).
5. **Token-budget smoke**: rendering a typical fully-populated 6-step participant produces a prompt block under a documented size threshold (the test is a guard rail, not a strict assertion — the threshold is recorded in the PRD).

### Prior art in the repo

- `services/onboarding/tests/test_screen_context.py` — same flavor: pure module, validation + render text + payload-hash dedup. Tests for this PRD should follow the same shape: one test class per public function, fixtures for FormState living in the test file, no Redis.
- `services/onboarding/tests/test_resumption.py` — pattern for asserting deterministic Redis key construction; useful as a reference even though we don't write a new repo test, because integration coverage for the lifecycle hooks should follow the same shape if added later.

### What is intentionally not unit-tested

- The user context repository (Redis I/O) — covered by manual smoke + the existing `test_state_repo.py` style if expanded later.
- The route integration (POST session reads bucket, POST complete writes bucket) — covered by the manual end-to-end smoke described in the verification section.
- The auth guard — straightforward behavioral assertion that should be added when we touch state_repo tests, but not gated on this PRD.

## Out of Scope

- LLM-based transcript summarization. Deferred to v2; revisited only after deterministic v1 ships and we have signal on what it misses.
- Cross-tenant analytics, search, or admin views over the bucket.
- Storage horizons longer than seven days. The application backend is the database of record for participant data.
- Migrating in-flight onboarding sessions. Feature is forward-only — sessions that started before deploy complete with the old behavior.
- A new external API for the bucket. Reads happen at session create, writes happen at complete or clean WS close. There is no `GET /v1/onboarding/context/{participant_id}` endpoint in v1.
- Redis cluster sharding considerations. Single-node Redis is the operating assumption matching the rest of the service.
- Schema migration tooling for the bucket format. Versioning is a single field; if we ever need to migrate, that is a future PRD.

## Further Notes

- The choice to fold the auth guard into this PRD rather than spinning a separate ticket reflects the principle that adjacent latent gaps get closed when you're already touching the call site. The cost is a one-line PRD scope expansion; the benefit is one less ticket and one less attack surface in production.
- The verbatim field set (`name, dob, gender, goals, hobbies, interests`) was specified by the product owner. New verbatim fields require an explicit PRD update and a regenerated render-snapshot test, not an inline change.
- The compressed-key alias table is the only place where the on-disk shape is defined. Adding a field to FormState without updating the alias table works (the fallback rule kicks in), but landing a long-lived alias requires a one-line addition to the table.
- The seven-day TTL was chosen to comfortably cover the longest realistic onboarding journeys we've observed in production. If telemetry shows truncation in practice, raise it in a follow-up — not in this PRD.
- The 5-step verbatim cap exists to defend against unbounded prompt growth. If we ever land a 12-step onboarding flow, the cap defends the prompt budget without requiring code changes.

---

_This PRD is paired with a detailed implementation plan at `.claude/plans/no-graceful-muffin.md`._
