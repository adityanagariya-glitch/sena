# Voice Bridge Extraction Plan

**Status:** Proposed — awaiting decisions in §6 before execution
**Owner:** Backend
**Author:** generated from session 2026-05-21
**Target branch:** `feat/voice-bridge-extraction` (off `voice-assistance-optimization`)
**Estimated effort:** ~½ day (Phase 1: 30 min · Phase 2: 2 h · Phase 3–4: 1 h · Phase 5: verify)

---

## 1. Why

The onboarding service has the only working Gemini Live voice bridge in
the monorepo (`services/onboarding/src/onboarding/services/gemini_live.py`
+ ~13 related files). It carries 13 production-tested fixes (CONFIRM_REQUIRED
race, cross-section auto-promote, premature-entry guard, silence
watchdog, recitation ban, screen_field_status filter, …).

The user wants to reuse this same voice machinery in **many future
features**, not just one. Doing copy-paste per feature would:

- Fork the 13 production fixes immediately — first divergence is forever.
- Duplicate the silence-watchdog, transcript ring buffer, resumption
  handle, webhook retry across services.
- Make Gemini API model upgrades a `find -name "gemini_live.py" -exec sed`
  operation instead of one file edit.

The right move is a one-shot extraction into a shared library that every
voice-using service depends on.

---

## 2. Scope — what's truly generic vs domain-specific

### Generic (moves to `shared/voice_bridge/`)

| Current file | New location | Why generic |
|---|---|---|
| `services/onboarding/.../services/gemini_live.py` | `shared/voice_bridge/session.py` | Gemini Live WS bridge — audio I/O, turn events, no domain logic |
| `services/onboarding/.../services/screen_context.py` | `shared/voice_bridge/screen_context.py` | `ScreenStateV2` model — pure data shape |
| `services/onboarding/.../services/resumption.py` | `shared/voice_bridge/resumption.py` | Single-use resume handles in Redis |
| `services/onboarding/.../services/webhook.py` | `shared/voice_bridge/webhook.py` | 3-retry exp-backoff outbound webhook |
| `services/onboarding/.../services/grounding.py` | `shared/voice_bridge/grounding.py` | LiveConnectConfig tool wrapper for function_decls + Google Search |
| **(extracted)** silence-watchdog logic | `shared/voice_bridge/silence_watchdog.py` | Currently embedded in `gemini_live.py` lines 752–831 |
| **(extracted)** WS lock + handshake helpers | `shared/voice_bridge/ws.py` | Currently embedded in `api/ws_routes.py` |
| **(new)** | `shared/voice_bridge/protocols.py` | Typed protocol interfaces — the contract consumers implement |
| **(new)** | `shared/voice_bridge/events.py` | Canonical framework WS event-name constants |

### Domain-specific (stays per-service)

| File | Stays where | Why |
|---|---|---|
| `services/tools.py` | per-service | Each domain has its own voice-callable operations |
| `services/prompt_builder.py` | per-service | Each domain's prompt template + state-rendering logic |
| `models/form_state.py` | per-service | Each domain's state shape (form, case note, booking, …) |
| `models/schema_spec.py` | **stays in onboarding for now** — see §6 decision 4 | Form-shaped abstraction; may promote later |
| `services/validators/*` | per-service | Domain-specific field rules + cross-field invariants |
| `services/coverage.py`, `field_apply.py` | onboarding only | Voice-coverage allowlist concept is onboarding-specific |
| `services/cross_screen_context.py`, `repositories/user_context_repo.py` | **TBD — see §6 decision 2** | Multi-step participant memory — may promote |
| `prompts/onboarding_system.md` | per-service | Each domain has its own prompt; can copy onboarding's as a template |
| `api/routes.py`, `api/ws_routes.py` | per-service | REST shape is per-domain. WS endpoint becomes a 1-line `mount_voice_endpoint` call |
| `fixtures/schema_*.json` | per-service | Domain data |
| Tests | per-service | Test the consumer's wiring + the protocol contract |

---

## 3. The protocol contract

`shared/voice_bridge/protocols.py` — the four interfaces every voice
consumer must satisfy. Pure typing.Protocol, runtime-duck-typed.

```python
from typing import Protocol, Any

class ToolProvider(Protocol):
    """A domain's voice-callable tools."""
    @property
    def function_decls(self) -> list[dict]: ...
    @property
    def policy_block_decl(self) -> dict | None: ...
    async def dispatch(self, name: str, args: dict) -> dict: ...
    def set_turn_id(self, turn_id: int) -> None: ...

class StateRepo(Protocol):
    """Per-session state store. Onboarding uses FormState; future
    domains can use anything serialisable."""
    async def get_state(self, session_id: str) -> Any: ...
    async def save_state(self, state: Any, ttl_sec: int) -> None: ...
    async def append_transcript(self, session_id: str, entry: dict, ttl_sec: int) -> None: ...
    async def get_transcript(self, session_id: str) -> list[dict]: ...

class PromptBuilder(Protocol):
    """Produces the system instruction given the current state."""
    def build_system_prompt(
        self,
        state: Any,
        *,
        bootstrap: Any | None = None,
        screen_field_status: dict[str, str] | None = None,
        resume_context_text: str | None = None,
        cross_screen_text: str | None = None,
    ) -> str: ...

class SessionEmit(Protocol):
    """Callback for emitting WS events to the client."""
    async def __call__(self, event: dict) -> None: ...
```

`VoiceSession` (was `GeminiLiveSession`) constructor becomes:

```python
class VoiceSession:
    def __init__(
        self,
        *,
        session_id: str,
        websocket: WebSocket,
        tools: ToolProvider,
        repo: StateRepo,
        prompt_builder: PromptBuilder,
        emit: SessionEmit | None = None,
        model_id: str = "gemini-3.1-flash-live-preview",
        api_key: str,
        silence_timeout_sec: int = 8,
        resumption_handle: str | None = None,
        bootstrap: Any | None = None,
        readonly_paths: list[str] | None = None,
    ): ...
```

No more `from onboarding.* import ...` inside the bridge.

---

## 4. Framework events vs domain events

Each consumer can emit any event over the WS. But voice_bridge owns a
canonical **framework event vocabulary** — emitted by the bridge itself,
not the domain dispatcher:

| Framework event | Source | Triggered by |
|---|---|---|
| `ready` | voice_bridge | session live, after gemini_connected |
| `turn_start` | voice_bridge | Gemini began speaking |
| `turn_complete` | voice_bridge | Gemini finished turn |
| `interrupted` | voice_bridge | user barge-in detected |
| `user_said` | voice_bridge | input transcript |
| `agent_said` | voice_bridge | output transcript |
| `go_away` | voice_bridge | Gemini session closing |
| `resumable` | voice_bridge | resume handle issued |
| `error` | voice_bridge | any error |
| `state` | **domain** | full domain-state snapshot |

Domain events (e.g. `field_updated`, `row_added`, `row_deleted`,
`field_cleared`, `field_confirmed`, `validation_rejection`,
`schema_drift_detected`, `step_completed`, `escalated`,
`repeatable_section_entered/exited`, `field_advisory_warning`,
`field_skipped_warning`) all live in the consumer's `tools.py` —
emitted via the `emit()` callback the bridge passes into the dispatcher.

---

## 5. Migration phases

### Phase 1 — Move + rename (≈ 30 min, LOW risk)

Pure relocation. No logic changes.

1. Create `shared/voice_bridge/` package.
2. Move the 5 generic files into it (rename `gemini_live.py` → `session.py`).
3. Update onboarding's imports from `onboarding.services.gemini_live` →
   `voice_bridge.session` etc.
4. Run all 336 tests. Must remain green.
5. Commit: `refactor(voice_bridge): move generic files out of onboarding`

### Phase 2 — Protocol decouple (≈ 2 h, MEDIUM risk — the real work)

The hard part: `gemini_live.py` currently imports concrete things from
onboarding. Refactor the constructor to take protocol-typed
collaborators.

1. Add `shared/voice_bridge/protocols.py` with the four protocols.
2. Refactor `session.py` constructor to take `ToolProvider`, `StateRepo`,
   `PromptBuilder` as args. Remove all `from onboarding.*` imports.
3. Onboarding creates concrete `OnboardingToolProvider`,
   `OnboardingStateRepo`, `OnboardingPromptBuilder` wrappers (very thin)
   in a new `services/onboarding/.../voice_runner.py` that wires them
   into `VoiceSession`.
4. Extract silence-watchdog into `shared/voice_bridge/silence_watchdog.py`
   so it doesn't need to import domain state types.
5. Run all 336 tests. Must remain green.
6. Commit: `refactor(voice_bridge): inject domain via protocols`

### Phase 3 — Domain wrap (≈ 30 min, LOW risk)

Pin a clean entry point for each consumer.

1. `services/onboarding/.../voice_runner.py` — single file that
   constructs the onboarding-flavoured `VoiceSession`.
2. Onboarding `ws_routes.py` calls `voice_runner.build_session(...)`
   instead of constructing `GeminiLiveSession` directly.
3. Add a tiny example consumer skeleton at
   `services/_example_voice_consumer/` showing the 4 files a new domain
   must write (`tools.py`, `prompt_builder.py`, `models/state.py`,
   `api/routes.py`).
4. Tests stay green.
5. Commit: `feat(voice_bridge): voice_runner entry point + example consumer skeleton`

### Phase 4 — WS endpoint extraction (≈ 30 min, LOW risk)

1. `shared/voice_bridge/ws.py` exports
   `mount_voice_endpoint(app, prefix, session_factory)`.
2. Handles: per-session WS lock acquire/release, handshake (ready
   event), error close codes (1000, 1011, etc.), bootstrap injection.
3. Onboarding's `api/ws_routes.py` shrinks to a 5-line call.
4. Tests stay green.
5. Commit: `feat(voice_bridge): mount_voice_endpoint WS helper`

### Phase 5 — Verify (REQUIRED gate)

1. `python -m pytest services/onboarding/tests/ -x` — must be 336 passing.
2. Smoke test: spin up onboarding service locally, run one voice session,
   verify all WS events still flow, advance_step still fires webhook.
3. Diff `instruction_chars` before/after — should be unchanged (prompt
   builder still produces identical output).
4. If green: PR `feat/voice-bridge-extraction` → `voice-assistance-optimization`.

---

## 6. Decisions required before starting

These five questions block Phase 1. Confirm each, then I'll execute the
plan.

### 6.1 Path

**Question:** `sena-ai/shared/voice_bridge/` (sits next to existing
`sena-ai/shared/`)? Or elsewhere?

**Recommendation:** `sena-ai/shared/voice_bridge/`. Matches the existing
`shared/` convention; consumers import via `from voice_bridge import …`.

### 6.2 Cross-screen bucket scope

**Question:** Include `user_context_repo.py` + `cross_screen_context.py`
in voice_bridge, or leave onboarding-specific?

**Trade-off:** voice_bridge stays leaner if left out. But if a future
voice feature on the same `participant_id` needs to read the bucket,
keeping it inside the bridge means free wire-up.

**Recommendation:** keep onboarding-specific for now. The bucket key
includes `tenant_id`/`participant_id`, not session_id — so any service
can read it via the existing `UserContextRepo` even without it being in
voice_bridge.

### 6.3 WS event vocabulary

**Question:** Move all 23 events into voice_bridge as canonical
constants, or only the 9 framework events?

**Recommendation:** only the 9 framework events
(`ready`/`turn_start`/`turn_complete`/`interrupted`/`user_said`/
`agent_said`/`go_away`/`resumable`/`error`) plus `state` (which the
domain emits but always with the same name). Domain events stay
per-domain — the consumer decides what to emit when its tools mutate
its own state.

### 6.4 Schema model (`models/schema_spec.py`)

**Question:** Move `StepSchema` / `SectionSpec` / `FieldSpec` into
voice_bridge, keep in onboarding, or split?

**Recommendation:** keep in onboarding for Phase 1–5. If a second
voice feature reuses the form-shaped abstraction, promote it later. No
new consumer is being written yet, so promoting now is premature
abstraction.

### 6.5 Branch strategy

**Question:** New branch off `voice-assistance-optimization`, or do this
after the 13-commit stack lands on `main`?

**Recommendation:** new branch `feat/voice-bridge-extraction` off
`voice-assistance-optimization` NOW, while context is hot. Land
`voice-assistance-optimization` → `main` first if you prefer a clean
mainline. Either order works — but doing extraction soon means future
features cherry-pick a clean architecture, not the legacy import graph.

---

## 7. Definition of done

- [ ] Phases 1–4 complete, each as an atomic commit on
      `feat/voice-bridge-extraction`.
- [ ] All 336 onboarding tests still pass.
- [ ] `gemini_live.py` (now `session.py`) has ZERO imports from
      `onboarding.*`.
- [ ] An example consumer skeleton lives at
      `services/_example_voice_consumer/` with the 4 files a future
      domain must write.
- [ ] `shared/voice_bridge/README.md` documents:
      - the 4 protocols
      - how to mount a voice endpoint
      - the framework event vocabulary
      - a copy of the example consumer
- [ ] PR opened against `voice-assistance-optimization` (or `main` if
      that's already merged).
- [ ] Manual smoke test of an onboarding session passes (one full step
      end-to-end).

---

## 8. Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Circular import while protocol-decoupling Phase 2 | Medium | Move slowly — extract one domain dep at a time, run tests each step |
| Test suite has hidden coupling to old import paths | Medium | The 336 tests live in `services/onboarding/tests/`; mostly use `from onboarding.services.tools import ToolDispatcher` etc. — those imports need updating |
| Silence-watchdog state lifecycle gets confused during extraction | Low | Watchdog already has clean state (`_silence_warned`, `_silence_exhausted`, `_last_audio_at`) — extract as-is, no behaviour change |
| Resume-handle Redis key namespace conflicts across consumers | Low | Keys already include `tenant_id`; voice_bridge doesn't change key construction |
| WS lock collision between consumers on same Redis | Low | Lock key includes `session_id` (unique). No collision possible |
| Future consumer writes a non-async dispatcher | Medium | Protocol is typed `async def dispatch` — mypy + runtime fail clearly |

---

## 9. What every future voice consumer writes

To add a new voice-driven feature anywhere in the monorepo, a developer
writes exactly 4 files:

```
services/new_feature/
├── src/new_feature/
│   ├── tools.py            ← implements ToolProvider
│   ├── prompt_builder.py   ← implements PromptBuilder
│   ├── models/state.py     ← their domain state model
│   └── api/routes.py       ← REST + a single mount_voice_endpoint(...) call
└── prompts/system.md       ← their domain's system prompt
```

Everything else (audio relay, transcript events, silence watchdog,
resumption, webhook delivery, screen-state filtering, Gemini Live
bridge, error handling, framework WS events) comes free from
`voice_bridge`.

---

## 10. Out of scope

- Migrating any other service today. Onboarding is the only voice
  consumer right now; we extract the framework but only re-wire
  onboarding.
- Changing the Gemini model. Still `gemini-3.1-flash-live-preview`.
- Changing the WS event payload shapes. Existing Flutter clients keep
  working unchanged.
- Rewriting validators. Each domain owns its own field/cross-field
  validators.
- Documentation rewrites of the system prompt. The prompt belongs to
  each consumer — we just slim a copy as a template if needed.

---

## 11. Reference files (what to read before starting)

| Concern | File | Lines |
|---|---|---|
| Current Gemini bridge | `services/onboarding/src/onboarding/services/gemini_live.py` | ~830 |
| Silence watchdog (to extract) | `services/onboarding/src/onboarding/services/gemini_live.py` | 752–831 |
| Tool dispatcher (stays domain) | `services/onboarding/src/onboarding/services/tools.py` | ~2000 |
| Screen state (to move) | `services/onboarding/src/onboarding/services/screen_context.py` | ~180 |
| Resumption (to move) | `services/onboarding/src/onboarding/services/resumption.py` | small |
| Webhook (to move) | `services/onboarding/src/onboarding/services/webhook.py` | small |
| Grounding (to move) | `services/onboarding/src/onboarding/services/grounding.py` | small |
| WS endpoint (helpers to extract) | `services/onboarding/src/onboarding/api/ws_routes.py` | small |
| State repo (stays domain — but the pattern is reusable) | `services/onboarding/src/onboarding/repositories/state_repo.py` | small |
| API event vocabulary | `.claude/rules/api.md` | the full table |
| System prompt structure | `services/onboarding/src/onboarding/prompts/onboarding_system.md` | 663 lines (post-strip) |

---

## 12. Next action

User confirms §6 decisions → I open `feat/voice-bridge-extraction` →
execute Phase 1. Each phase commits atomically with tests green before
proceeding to the next.

If any decision in §6 needs more discussion, surface it as a comment on
this plan file — don't merge without alignment.
