# PRD — SENA Onboarding Voice API: Remaining Phases (D-replacement, E, F)

**Status:** Draft
**Owner:** Backend AI layer (`SENA_AI/sena-ai/services/onboarding/`)
**Date:** 2026-04-28
**Relates to:** `.planning/ONBOARDING_VOICE_API_PLAN.md`, `HANDOFF_VOICE_ONBOARDING.md`, `.planning/paused_state_phase_d_camera_screen_ingress.md`

---

## Problem Statement

The SENA NDIS onboarding voice agent (port 8083, Gemini Live) lets a participant complete an onboarding step by speaking. Phases A–C are shipped: REST session lifecycle, WebSocket audio bridge, system prompt rendering, four function-calling tools (`update_field`, `get_session_context`, `advance_step`, `escalate_incident`). Tests pass (36/36 + 48/48). A browser test harness exists.

Three gaps remain that block production launch and the Flutter integration the parent app team is depending on:

1. **The agent has no idea what the participant is looking at.** The original plan was to ingest camera and screen frames as binary blobs over the WebSocket; that plan was scrapped because it required device-side capture work the office team owns and was disproportionate to the value. Without screen context, the agent cannot say "I see the date of birth field is already filled — is this correct?" or skip questions the app already answered, leading to redundant, frustrating dialogue.

2. **A dropped WebSocket loses the entire session.** Mobile networks drop. Apps backgrounds. Today, every reconnect is a fresh session: the agent forgets the participant's last turn, the form is preserved in Redis but the conversation context is not, and the participant has to repeat themselves. State-repo primitives for resumption handles exist but no caller wires them up.

3. **The agent cannot answer NDIS policy questions with current information.** During onboarding, participants ask things like "what counts as core supports?" or "how do I prove plan management?". Without grounding to live sources, the model either guesses (compliance risk) or says "I don't know" (poor UX). NDIS policy changes faster than the model's training cutoff.

4. **The Flutter team has no contract to integrate against.** OpenAPI is debug-only. The WS protocol is documented only in a markdown handoff. There is no Postman collection, no machine-readable WS schema, and no harness for testing screen state or resumption.

## Solution

Three feature buckets, all backend-only (Flutter side is read-only reference for this work):

1. **Screen state injection.** Replace Phase D's binary frame ingress with a lightweight JSON message Flutter sends over the existing WebSocket whenever the visible screen changes. Backend validates it, normalizes it into a short text snippet, and injects it into Gemini's live session as a text turn. Gemini now knows what the user is seeing and can adapt its prompts.

2. **Session resumption + optional Google Search grounding.** When a WebSocket disconnects mid-session, the server issues a short-lived resumption handle. The client reconnects with `?resume=<handle>` and the server rehydrates FormState plus replays the last few transcript turns as Gemini context, so the agent says "as I was saying…" instead of starting over. Google Search grounding is added as a Gemini tool, gated behind a single environment variable (`SENA_AI_ONBOARDING_GROUNDING_ENABLED`), default off, so it ships disabled and can be flipped on after compliance review.

3. **Production-ready protocol surface.** First-class OpenAPI metadata for REST, a versioned `WS_PROTOCOL.md` documenting every message type and close code, a Postman collection, and an updated test harness that exercises screen state, resumption, and the grounding toggle.

## User Stories

### Participants (end users, voice agent consumers)

1. As a participant, I want the agent to know which screen I'm looking at, so that I'm not asked questions the app already answered.
2. As a participant, I want the agent to acknowledge fields the app pre-filled, so that I can confirm or correct them instead of dictating from scratch.
3. As a participant, I want the agent to recover the conversation if my call drops, so that I don't have to start over after a network blip.
4. As a participant, I want the agent to remember the last thing it said before disconnect, so that the conversation feels continuous, not restarted.
5. As a participant, I want the agent to give me current, accurate information when I ask NDIS policy questions, so that I can trust the answers I'm getting (when grounding is enabled).
6. As a participant, I want the agent to escalate if I describe a safety issue, so that a human follows up — and this must keep working through screen state changes and resumption.

### Mobile app developers (Flutter team — primary backend consumers)

7. As a Flutter developer, I want a stable WebSocket message schema for screen state, so that I can model `ScreenStateMessage` once and serialize it from any screen.
8. As a Flutter developer, I want the backend to silently ignore screen state messages it doesn't recognize, so that older app versions don't break the WS connection when the schema evolves.
9. As a Flutter developer, I want a documented "resume handle" lifecycle, so that I know when to issue, store, and discard handles in app state.
10. As a Flutter developer, I want the resumption handle returned in the `step_completed` envelope and on graceful close, so that I can capture it without parsing close codes.
11. As a Flutter developer, I want connecting with `?resume=<handle>` to either succeed and rehydrate, or fail with a specific close code (e.g. 4010 "resume_invalid"), so that I can handle expired handles without ambiguity.
12. As a Flutter developer, I want a Postman collection for all REST endpoints, so that I can exercise session create / state read / complete without running the app.
13. As a Flutter developer, I want OpenAPI / `/docs` enabled for staging, so that I can browse the schema while integrating.
14. As a Flutter developer, I want screen state injection to be idempotent — repeating the same payload should be a no-op — so that I can fire-and-forget on every screen rebuild without rate-limiting on the client.

### Backend developers (this repo)

15. As a backend developer, I want screen state validation isolated in a pure module, so that I can unit-test schema and rendering without standing up a WebSocket or Gemini session.
16. As a backend developer, I want resumption-handle policy in one module, so that TTL, single-use semantics, and replay-window decisions are not scattered across the WS handler.
17. As a backend developer, I want a single environment flag for grounding, so that I can flip it in staging without code changes and without per-step schema modifications.
18. As a backend developer, I want the Gemini tools list built by a single function, so that adding or removing tools (function declarations + Google Search) is one change, not three.
19. As a backend developer, I want the WS handler to remain readable as features grow, so that screen state, resumption, and existing audio/tool flows are dispatched through clearly-named branches, not nested conditionals.
20. As a backend developer, I want all new code paths covered by tests that exercise external behavior, so that refactors don't silently break the contract.

### Operators / org admins (webhook consumers)

21. As an org admin, I want the completion webhook to fire exactly once per step, regardless of how many resumes or reconnects happened, so that downstream systems aren't double-billed for the same step.
22. As an org admin, I want resumption handles to expire on a short TTL, so that an abandoned session can't be hijacked hours later.
23. As an org admin, I want grounding disabled by default, so that nothing leaves the controlled Gemini call to Google Search until compliance signs off.
24. As an org admin, I want every escalation to survive resumption, so that safety incidents are never lost when the WS reconnects.

### QA / test harness users

25. As a QA tester, I want the browser test harness to send a screen state message with a JSON editor, so that I can test the agent's response to a pre-filled field without running the Flutter app.
26. As a QA tester, I want the harness to display the issued resumption handle and offer a "reconnect with handle" button, so that I can verify rehydration without copy-pasting URLs.
27. As a QA tester, I want a toggle in the harness to enable grounding for a single session, so that I can compare grounded vs ungrounded responses side-by-side during compliance review.

### Compliance / security

28. As a compliance reviewer, I want screen state payloads logged at debug level only, so that participant-visible PII isn't persisted in production logs.
29. As a compliance reviewer, I want grounding disabled in production by default, so that a configuration mistake can't leak NDIS questions to a third-party search service.
30. As a compliance reviewer, I want resumption handles to be opaque, single-use UUIDs (not session_ids), so that handle exposure doesn't leak the underlying session identifier.

## Implementation Decisions

### Module boundaries

| # | Module | Type | Responsibility |
|---|--------|------|---------------|
| 1 | `services/screen_context.py` | New, pure | Pydantic `ScreenStateMessage` model + `render_injection_text(state, schema) -> str`. No IO. |
| 2 | `services/resumption.py` | New, deep | `issue_handle(session_id) -> str`, `redeem_handle(handle) -> str \| None`, `build_replay_context(state, last_n) -> str`. Wraps existing state-repo primitives. |
| 3 | `services/grounding.py` | New, small | `build_live_tools(function_decls, *, grounding_enabled: bool) -> list[Tool]`. Pure. |
| 4 | `services/gemini_live.py` | Modify | Replace static `FUNCTION_DECLS` array with call to `build_live_tools(...)`. Add `inject_text_turn(text)` method using `session.send_realtime_input(text=...)`. |
| 5 | `api/ws_routes.py` | Modify | Dispatch new `screen_state` message type. Accept `?resume=<handle>` query param. Issue handle on graceful close. New close code 4010 for invalid resume. |
| 6 | `api/routes.py` | Modify | OpenAPI metadata pass: `response_model`, descriptions, examples on every endpoint. |
| 7 | `core/settings.py` | Modify | Add `grounding_enabled: bool = False`, `resumption_handle_ttl_sec: int = 600`, `resumption_replay_turns: int = 4`, `screen_state_max_bytes: int = 8192`. |
| 8 | `main.py` | Modify | Enable `/docs` and `/redoc` unconditionally (production-ready protocol surface). Keep `/openapi.json` always exposed. |
| 9 | `prompts/onboarding_system.md` | Modify | Add a "Screen Context" section instructing the model how to use injected screen state (acknowledge prefills, skip filled fields, reference visible fields by name). |
| 10 | `test_harness.html` | Modify | Add: screen-state JSON editor + send button; resumption handle display + "reconnect with handle"; grounding toggle (UI only — backend honors env flag). |
| 11 | `docs/WS_PROTOCOL.md` | New | Machine-checkable message catalog (every `type`, every close code, sequence diagrams, error taxonomy, schema versioning policy). |
| 12 | `docs/postman_collection.json` | New | All REST endpoints + sample bodies + environment variables (base URL, session id). |

### `screen_state` message contract (server-side)

```json
{
  "type": "screen_state",
  "data": {
    "current_screen": "personal_information",
    "visible_fields": ["full_name", "date_of_birth", "phone"],
    "prefilled": { "full_name": "John Smith" },
    "app_context": "user is on step 1 of 5"
  }
}
```

- `data.current_screen`: optional string (≤ 64 chars)
- `data.visible_fields`: optional `list[str]` (≤ 32 entries)
- `data.prefilled`: optional `dict[str, Any]` (values coerced to string for injection)
- `data.app_context`: optional string (≤ 256 chars)
- Total payload size: hard cap from `settings.screen_state_max_bytes` (default 8 KB). Over-cap → `error` event with `code="screen_state_too_large"`, message dropped, WS stays open.
- Unknown keys in `data`: silently ignored (forward-compat).
- Idempotency: identical consecutive payloads (deep-equal) are dropped server-side without re-injecting.

### Injection rendering (deterministic text)

`render_injection_text` produces a single line, e.g.:

```
[SCREEN] section=personal_information; visible=full_name,date_of_birth,phone; prefilled={full_name=John Smith}; note="user is on step 1 of 5".
```

Injected into Gemini via `session.send_realtime_input(text=...)`. Goes ahead of next user audio turn. Not stored in transcript (debug log only). System prompt is updated to instruct: when a `[SCREEN] ...` line appears, use it to skip questions about already-filled fields and acknowledge them once.

### Resumption protocol

- **Handle issuance:** server issues an opaque UUID4 (not the session_id) on every successful WS close *that did not already complete the step*. Sent in a final envelope `{"type":"resumable","handle":"<uuid>","ttl_sec":600}` immediately before close. On `step_completed` close, no handle issued (terminal state).
- **Storage:** Redis key `sena:onboarding:resumption:{handle}` → `session_id`, TTL = `settings.resumption_handle_ttl_sec`. Single-use: redeemed handle is deleted on lookup (atomic `GETDEL`).
- **Reconnect:** `WS /ws/onboarding/{session_id}?resume=<handle>`. Server validates: handle exists AND maps to this session_id. Mismatch or expired → close 4010 with reason `resume_invalid`.
- **Rehydration on resume:**
  1. Load FormState from Redis (existing path).
  2. Pull last `settings.resumption_replay_turns` (default 4) entries from the transcript list.
  3. After Gemini connection opens, inject a single text turn:
     `[RESUME] last turns: user="..."; agent="..."; user="..."; agent="...". Continue from where you left off.`
  4. WS lock acquired as normal.
- **No replay on first connect** (new session). `?resume` ignored if FormState not found → close 4004 (existing).

### Grounding gating

- Single env var: `SENA_AI_ONBOARDING_GROUNDING_ENABLED` → `settings.grounding_enabled: bool` (default `False`).
- `build_live_tools(function_decls, *, grounding_enabled)`:
  - Always returns `[Tool(function_declarations=function_decls)]`.
  - If `grounding_enabled`: appends `Tool(google_search=GoogleSearch())`.
- Composition is mutually compatible: function-calling + Google Search both work on `gemini-3.1-flash-live-preview`.
- No per-step schema flag, no per-tenant override in this PRD. Future work if compliance asks for per-tenant control.
- System prompt updated to mention Google Search availability *only when* the prompt builder is told grounding is on. (Prompt builder gains a `grounding_enabled: bool` parameter.)

### Webhook idempotency

- Today, `advance_step` fires the webhook then sets `state.completed = True`. After this PRD, also early-return from `advance_step` if `state.completed` is already `True` — protects against resume-then-re-advance.
- Webhook payload unchanged (already includes `session_id`, `step_id`, full FormState).

### New / changed envelope shapes (server → client)

| Envelope | Trigger | Shape |
|----------|---------|-------|
| `resumable` | About to close, step not complete | `{type, handle, ttl_sec}` |
| `screen_state_ack` *(optional, debug only)* | After successful screen_state ingest | `{type, accepted: true}` (only when `settings.debug`) |
| `error code="screen_state_too_large"` | Payload exceeds cap | existing error shape |
| `error code="screen_state_invalid"` | Pydantic validation fails | existing error shape |

### New WS close code

| Code | Meaning |
|------|---------|
| 4010 | `resume_invalid` — handle missing, expired, or mapped to a different session_id |

### Settings additions

```python
# core/settings.py
grounding_enabled: bool = False                 # SENA_AI_ONBOARDING_GROUNDING_ENABLED
resumption_handle_ttl_sec: int = 600            # SENA_AI_ONBOARDING_RESUMPTION_TTL
resumption_replay_turns: int = 4                # SENA_AI_ONBOARDING_REPLAY_TURNS
screen_state_max_bytes: int = 8192              # SENA_AI_ONBOARDING_SCREEN_MAX_BYTES
```

### OpenAPI / docs

- `/docs`, `/redoc`, `/openapi.json` unconditionally exposed. (Auth is dev-header for now — no leak risk.)
- Every REST route: `response_model`, `summary`, `description`, at least one `examples` payload in `Body(...)`.
- WebSocket protocol: not in OpenAPI (FastAPI doesn't model WS). Documented in `docs/WS_PROTOCOL.md` as the canonical source. Linked from the OpenAPI top-level `description`.
- Postman collection committed at `docs/postman_collection.json`. Variables: `{{base_url}}`, `{{session_id}}`, `{{tenant_id}}`, `{{participant_id}}`. Import-and-run.

### Architectural decisions

- **No new persistence layer.** Resumption uses the existing Redis primitives in `state_repo.py`. No Postgres added.
- **Pure modules where feasible.** `screen_context`, `grounding` are pure (no IO). `resumption` is one thin layer over Redis. The WS handler stays the integration seam — no business logic added there.
- **No Flutter changes in this PRD.** Frontend is read-only reference. The Flutter team consumes the protocol; they are not a dependency for this PRD's completion.
- **No schema changes to `StepSchema`.** Grounding is a runtime flag, not a per-step capability, in v1.
- **Backwards compatible.** Today's clients that don't send `screen_state` and don't use `?resume` continue to work without modification.

## Testing Decisions

### What makes a good test (this PRD's bar)

A good test exercises **observable behavior at a module's seam**, not implementation:

- For pure modules (`screen_context`, `grounding`): given input X, assert output Y. No mocks. Many small cases over enums/edge cases.
- For Redis-backed modules (`resumption`): use `fakeredis` (already in dev deps if tests rely on it; add otherwise). Assert key lifecycle (TTL, single-use, atomic redemption) by interacting through the public API only — never by reading internal Redis keys directly.
- For WS routes: integration tests with FastAPI's TestClient or `httpx_ws` against a stubbed `GeminiLiveSession` (a fake class implementing the same protocol the real one does). Assert the message envelopes the server sends, the close codes, the side-effect on Redis (FormState + handle key) — not internal handler call ordering.
- For the system-prompt change: snapshot test on `build_system_prompt(...)` output asserting the "Screen Context" / "Resume Context" / "Grounding" sections render correctly under each combination of inputs.

Tests that mirror implementation (mock every collaborator, assert call sequences) are explicitly out of scope — they break on every refactor and add no safety.

### Modules with required test coverage

| Module | Test type | Cases |
|--------|-----------|-------|
| `screen_context.py` | Unit (pure) | Valid payload → expected injection string; missing optional fields; oversize → `screen_state_too_large`; invalid types → `screen_state_invalid`; unknown keys ignored; idempotency hash equality. |
| `resumption.py` | Unit + fakeredis integration | Issue → redeem round-trip; double-redeem returns None; expired handle returns None; `build_replay_context` with 0 / fewer-than-N / N+ transcript entries; replay text format. |
| `grounding.py` | Unit (pure) | Flag off → 1 tool (function_declarations); flag on → 2 tools (function_declarations + google_search); function_decls list passed through unchanged. |
| `ws_routes.py` | Integration | (a) Fresh connect: existing happy path still passes (regression). (b) Send `screen_state` → server logs injection, no client-visible output unless debug. (c) Disconnect mid-step → server emits `resumable` envelope before close. (d) Reconnect with valid handle → FormState rehydrated, replay context injected, single-use handle is consumed (re-redeem fails). (e) Reconnect with bad handle → close 4010. (f) Reconnect with handle for different session_id → close 4010. (g) `step_completed` close → no handle issued. (h) Webhook fires exactly once across resume-then-advance scenario. |
| `gemini_live.py` mods | Light unit | `build_live_tools` is wired in (assertion against config object), `inject_text_turn` calls `send_realtime_input(text=...)` not `send_client_content`. Mock the session. |
| `prompt_builder.py` | Snapshot | Output diffs across {grounding off, grounding on} × {fresh, with screen state, with resume context}. |

### Prior art

- Phase A tests (36/36) for REST + state repo — pattern to mirror for `resumption.py` (fakeredis, atomic semantics).
- Phase C tests (48/48) for `tools.py` — pattern to mirror for `screen_context.py` and `grounding.py` (pure-module tests with extensive case tables).
- Existing WS tests (whatever Phase B shipped) — pattern to extend for new envelope shapes and close code 4010.

### Coverage targets

- New pure modules: 100% line.
- `resumption.py`: 100% line, all branches.
- `ws_routes.py` new branches: 100% — every new close code, every new envelope, every new dispatch path tested.
- Snapshot tests: any prompt-builder change committed alongside its updated snapshot (no auto-accept in CI).

## Out of Scope

- **Flutter / Dart code.** The mobile team consumes the protocol documented here. No code in `sena-mobile/lib/**` is modified by this PRD; the project hook actively blocks writes outside `SENA_AI/`.
- **Camera and screen frame ingress** (original Phase D). Officially replaced by `screen_state` JSON. The paused state document remains in `.planning/` for historical reference but is not implemented.
- **JWT auth.** Stays in dev-header mode. JWT is a known seam, separate workstream.
- **Per-tenant grounding override.** v1 is one global flag. Per-tenant work happens after compliance signs off on the global flag in production.
- **Per-step schema fields for grounding** (`grounding_enabled` on `StepSchema`). Not added — see "Grounding gating" decision above.
- **Postgres for resumption.** Redis only. If TTL semantics ever require durability, separate workstream.
- **Audio codec changes.** PCM16 16 kHz in / 24 kHz out unchanged.
- **Multi-step session** within one WS. One step per WS remains the contract.
- **Live grounding sources beyond Google Search** (Vertex Search, custom RAG over `ndis_wiki/`). Future work.
- **Rate limiting on `screen_state`.** Idempotency dedupe is sufficient for v1; if abuse appears, add token-bucket later.
- **WS protocol JSON Schema / AsyncAPI artifact.** Markdown doc is canonical for v1; if a client asks for a machine-readable spec, add later.
- **Postman environment for staging / prod.** Shipping the dev-header collection only; staging variables can be set per-developer.

## Further Notes

### Implementation sequencing (recommended)

1. **Phase D-replacement first** (`screen_context.py`, prompt update, WS dispatch, harness UI, tests). Self-contained, no dep on resumption work, unblocks Flutter integration immediately.
2. **Phase E grounding** (`grounding.py`, settings flag, `gemini_live.py` mod, prompt update). Tiny but unblocks compliance review timeline. Ships disabled.
3. **Phase E resumption** (`resumption.py`, WS query param, close code 4010, `resumable` envelope, replay context, harness UI, tests). Largest behavioral change; do last so 1 and 2 stabilize first.
4. **Phase F docs** (OpenAPI metadata pass, `WS_PROTOCOL.md`, Postman collection, harness polish). Done after behavior is settled so docs don't lag.

Each item above ships as one PR with its own tests and `.claude/issues-solved/` entries if anything bites.

### Risks

- **Gemini Live token budget.** Injecting `[SCREEN]` and `[RESUME]` text turns adds tokens. Mitigation: hard caps on payload size, capped replay window (4 turns by default), monitor session token count if it becomes an issue.
- **Resumption handle leak.** If a handle is logged in plaintext, anyone with log access can resume. Mitigation: log only the *first 8 chars* of handles, never the full UUID.
- **Webhook double-fire** under racy resume. Mitigation: idempotency check on `state.completed` in `advance_step` (see decisions).
- **Google Search compliance.** Default off; enabling needs a separate go/no-go review. PRD scope ends at flag-and-tool wiring.
- **Schema drift between Flutter and backend.** Backend silently ignores unknown keys; backend-required keys are documented in `WS_PROTOCOL.md` and asserted by Pydantic. Adding a new required field is a breaking change requiring `prompt_version` bump.

### Done criteria

- All four module test suites green.
- Existing 36/36 (Phase A) and 48/48 (Phase C) tests still green.
- Test harness exercises all three new flows manually (screen state, resume, grounding-on).
- `/docs` renders cleanly (no missing summaries / response models).
- `WS_PROTOCOL.md` and `docs/postman_collection.json` reviewed by Flutter dev.
- `SENA_AI_ONBOARDING_GROUNDING_ENABLED=false` confirmed default.
- Webhook double-fire test passes.
- `.claude/tasks/TASKS.md` Task #9 status updated to "DONE — phases A–F shipped 2026-04-XX".
- `HANDOFF_VOICE_ONBOARDING.md` updated: "What needs to happen next" section becomes "What's done".
