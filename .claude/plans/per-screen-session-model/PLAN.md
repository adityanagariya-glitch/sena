# Per-Screen Live Session Model — PLAN

**Status:** draft
**Author:** sena-planner
**Date:** 2026-05-22
**Scope:** `services/onboarding/` only

---

## 1. Goal

Replace the current one-Gemini-Live-session-per-step model with one-session-per-screen, pre-warming the next screen's Live connection ~2s ahead of the Flutter screen transition so the audible pause at the cut is ~0s.

---

## 2. Architectural overview

### Old model — one session per step (~5 min monologue)

```
   step_start                                              step_end
       |                                                       |
       v                                                       v
   +------------------------------------------------------------+
   |  Single Gemini Live session (~800-line system prompt)      |
   |  All sections in one context; model decides ordering.      |
   +------------------------------------------------------------+
   ^ WS open                                              WS close ^
```

### New model — one session per screen, parallel pre-warm

```
                          screen_changed
                              (Flutter)
                                   |
   screenA              T-2s       |       T+0s             screenB
       |                 |         |         |                 |
       v                 v         v         v                 v
   +--------------------------------+
   | Live session A                 |
   | prompt = screenA-only          |   mic     close (drain)
   | owns mic + tools               |---cut---+
   +--------------------------------+         |
                       +-------------------------+--------------+
                       | Live session B                         |
                       | pre-warm: prompt + screenB schema only |
                       | (NO prior-screen summary yet -billing) |
                       | on cut: receive summary via            |
                       | send_realtime_input(text=PRIOR_SUMMARY)|
                       | then owns mic + tools                  |
                       +----------------------------------------+
                                ^
                                |
                       2-second overlap window
                       (both connected; only B receives audio after cut)
```

**Invariants during overlap:**
- ONE WebSocket between Flutter and server (single `assert_session_owner` holder, single `acquire_ws_lock`).
- TWO `genai.Client.aio.live.connect()` contexts inside `gemini_live.py`.
- ONE `b2g_router` task per WS owns `session.send_realtime_input(audio=...)`. It reads a `current_handle` reference; the flip is a single-statement assignment.

---

## 3. Locked design decisions

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Single WebSocket, two internal Live sessions during the 2s overlap. `state_repo.acquire_ws_lock` unchanged. | Overlap is implementation-internal to `gemini_live.py`; the WS lock guards the *client* connection. Avoids dual-holder lock semantics entirely. |
| D2 | `SectionSpec` gains optional `screen_id: str \| None`. Fallback when unset: `section.id` IS the screen_id (1:1). | Minimal-diff additive change; no new `ScreenSpec` model. Multi-section screens addressable via shared `screen_id`. |
| D3 | Back-navigation = full new Live session for the prior screen (same code path as forward). | Options (b)/(c) demand the model reason about partial state, which fights the prompt-shrink goal. Reuses forward-nav handoff machinery → smallest failure surface. |
| D4 | Server timeout = **300s wall-clock since last `screen_state`** OR **60s of voice inactivity**, whichever fires first → close stale Live session(s), emit WS `voice_paused`. NEVER auto-advance. | Preserves locked decision #1 (server does not infer boundaries). The timeout is GC, not handoff. |
| D5 | Pre-warm payload = system prompt + per-screen schema only. Prior-screen summary is injected as `send_realtime_input(text=...)` **after** the mic cut, on session B. | Per Gemini billing docs: context tokens are re-billed every turn. Injecting the summary during pre-warm and again post-cut would double-bill the largest variable component. |
| D6 | New session B owns tool dispatch the moment mic flips. Old session A's in-flight tool turns are **discarded** (not awaited) when its `aclose()` runs. | Tool effects already committed to FormState are durable in Redis. Discarding in-flight responses avoids ordering races on `field_updated` emissions to Flutter. |
| D7 | Rollback env var: `SENA_AI_ONBOARDING_PER_SCREEN_SESSIONS` (bool, default `false` during rollout). When false, `screen_changed` is a no-op. | Per principal-engineer rule 4 (minimal blast radius). |

---

## 4. Existing code to extend / libraries already installed

**No-reinvention audit**

| Existing surface | What it already does | How we extend |
|------------------|----------------------|---------------|
| `services/gemini_live.py` :: `GeminiLiveSession` (~700 LOC) | Owns the single Live connection, b2g/g2b tasks, screen_state injection, tool dispatch, transcript appending. | Extract a `_LiveConnectionHandle` per Live connection; the existing class becomes the **router/pool** for two handles during overlap. |
| `services/prompt_builder.py` :: `build_system_prompt(schema, state, ...)` | Renders the system prompt with all sections of the step's schema. | Add an optional `screen_id: str \| None` parameter that filters `schema.sections` before rendering. No new function. |
| `services/cross_screen_context.py` :: `build_summary` + `render_for_prompt` | Already emits step-boundary summaries. | Reuse `build_summary` at screen-boundary granularity; new call site only, no new module. |
| `repositories/state_repo.py` :: `acquire_ws_lock` / `assert_session_owner` | WS-level locking + tenant ownership. | **Unchanged.** Overlap is internal to one WS holder. |
| `services/resumption.py` (per-step `issue_handle` / `redeem_handle`) | Connection-drop recovery at step boundary. | **Unchanged.** S12 is verify-only. |
| `api/ws_routes.py` (dispatch on `type` field) | Already routes `user_text`, `audio`, `screen_state`, `screen_state_v2`, `stop`. | Add two new branches: `screen_changed`, `screen_changing` (advisory pre-warm trigger). |
| `models/schema_spec.py` :: `SectionSpec` | Pydantic v2 section model. | Add `screen_id: str \| None = None` field. No new model. |
| `asyncio.Event` / `asyncio.gather` / `asyncio.TaskGroup` | stdlib | Used directly per principal-engineer rule 5. No custom state machine. |
| `google.genai.Client.aio.live.connect(...)` | Async ctx manager; supports parallel sessions (researcher confirmed Tier 1 = 50). | Held open across two concurrent `AsyncExitStack` entries. |

**New code required (and why no existing surface fits):**
- One **private** helper class `_LiveConnectionHandle` **inside** `gemini_live.py` (NOT a new file) — wraps the Gemini `session` + per-connection b2g task. Lives next to `GeminiLiveSession` because they share lifecycle and are never used independently.
- One new module: NONE.

---

## 5. Subtask DAG

```yaml
plan_id: per-screen-session-model
subtasks:

  - id: S1
    title: "Add optional screen_id to SectionSpec; fallback = section.id"
    file_scope: ["sena-ai/services/onboarding/src/onboarding/models/schema_spec.py"]
    depends_on: []
    contract:
      adds: ["SectionSpec.screen_id: str | None = None", "SectionSpec.resolved_screen_id() -> str"]
    security_tier: 1
    test_requirement: "tests/test_schema_spec.py - load personal-details fixture; assert section without screen_id falls back to id."
    acceptance:
      - "All existing tests pass without schema fixture changes."
      - "New unit test covers explicit screen_id AND fallback."

  - id: S2
    title: "build_system_prompt gains screen_id filter; drops other-screen sections"
    file_scope: ["sena-ai/services/onboarding/src/onboarding/services/prompt_builder.py"]
    depends_on: [S1]
    contract:
      modifies: ["build_system_prompt(... screen_id: str | None = None ...)"]
    security_tier: 1
    test_requirement: "Extend test_prompt_builder.py - assert prompt for screen_id='basics' contains basics fields but NOT address fields."
    acceptance:
      - "Prompt length reduction >= 40% vs current monolithic on a 5-section step."
      - "screen_id=None reproduces today's output byte-for-byte (rollback safety)."

  - id: S3
    title: "cross_screen_context emits summary on screen boundary, not just step boundary"
    file_scope: ["sena-ai/services/onboarding/src/onboarding/services/cross_screen_context.py"]
    depends_on: [S1]
    contract:
      adds: ["build_summary(... since_screen: str | None = None ...)"]
    security_tier: 2
    test_requirement: "tests/test_cross_screen_context.py - fill basics + address; request summary at end of address; assert verbatim of both screens present."
    acceptance:
      - "Summary is compact (<= ~30 lines for a 5-screen step) per billing rationale."
      - "Existing step-boundary callers unaffected (default arg)."

  - id: S4
    title: "Add screen_changed message branch to ws_routes dispatcher"
    file_scope: ["sena-ai/services/onboarding/src/onboarding/api/ws_routes.py"]
    depends_on: []
    contract:
      adds: ["WS inbound type 'screen_changed' { screen_id: str, prev_screen_id?: str }"]
      modifies: ["b2g loop dispatch table"]
    security_tier: 2
    test_requirement: "tests/test_ws_routes.py - send screen_changed with mismatched session ownership header; assert 1008 close + assert_session_owner raised."
    acceptance:
      - "Unknown screen_id rejected with WS error event (not connection close)."
      - "Feature-flag off (D7) → screen_changed is acknowledged but no handoff fires."

  - id: S5
    title: "Extract _LiveConnectionHandle private class in gemini_live.py"
    file_scope: ["sena-ai/services/onboarding/src/onboarding/services/gemini_live.py"]
    depends_on: []
    contract:
      adds: ["class _LiveConnectionHandle (session, screen_id, b2g_task, aclose())"]
    security_tier: 3
    test_requirement: "tests/test_gemini_live.py - open-then-close a handle against a fake genai client; assert task cancelled and exit-stack popped."
    acceptance:
      - "GeminiLiveSession's current behaviour is preserved (single handle in old mode)."
      - "Handle exposes only: session, screen_id, aclose()."

  - id: S6
    title: "Router task: single send_realtime_input(audio=...) consumer with swappable target"
    file_scope: ["sena-ai/services/onboarding/src/onboarding/services/gemini_live.py"]
    depends_on: [S5]
    contract:
      adds: ["GeminiLiveSession._current_handle: _LiveConnectionHandle", "GeminiLiveSession._swap_active(new_handle)"]
    security_tier: 3
    test_requirement: "tests/test_gemini_live.py::test_router_atomic_swap - feed 100 audio frames while swap fires mid-stream; assert no frame lost AND no frame double-sent."
    acceptance:
      - "Swap is a single-statement assignment; no asyncio.Event needed (only one consumer)."
      - "Old handle stops receiving audio the instant swap returns."

  - id: S7
    title: "Pre-warm: open session B minimally on the lookahead trigger"
    file_scope: ["sena-ai/services/onboarding/src/onboarding/services/gemini_live.py"]
    depends_on: [S2, S5]
    contract:
      adds: ["GeminiLiveSession._prewarm(next_screen_id) -> _LiveConnectionHandle"]
    security_tier: 3
    test_requirement: "tests/test_gemini_live.py::test_prewarm_payload_minimal - mock genai client; assert connect() payload includes system_prompt + screen schema but NEITHER prior-screen summary NOR transcript replay."
    acceptance:
      - "Pre-warm completes in <2s in mock (success criterion is bytes-shape, not wall-clock)."
      - "If pre-warm fails, old session continues; handoff falls back to cold-start on screen_changed (logged WARNING)."

  - id: S8
    title: "Cut: mic swap + summary injection on session B + drain-and-close session A"
    file_scope: ["sena-ai/services/onboarding/src/onboarding/services/gemini_live.py"]
    depends_on: [S3, S6, S7]
    contract:
      adds: ["GeminiLiveSession._handoff(screen_changed_msg) coroutine"]
    security_tier: 3
    test_requirement: "tests/test_gemini_live.py::test_handoff_sequence - assert ORDER: (1) swap router, (2) send_realtime_input(text=PRIOR_SCREENS_SUMMARY) on B, (3) aclose() on A. Tool calls in flight on A are discarded."
    acceptance:
      - "Old handle aclose() runs concurrently with first user audio frame on B (no blocking)."
      - "PRIOR_SCREENS_SUMMARY text is rendered by cross_screen_context.render_for_prompt, prefixed with 'PRIOR_SCREENS_SUMMARY:'."

  - id: S9
    title: "Pre-warm trigger: screen_changing advisory message"
    file_scope: ["sena-ai/services/onboarding/src/onboarding/services/gemini_live.py", "sena-ai/services/onboarding/src/onboarding/api/ws_routes.py"]
    depends_on: [S7]
    contract:
      adds: ["WS inbound type 'screen_changing' { next_screen_id, eta_ms }"]
    security_tier: 2
    test_requirement: "tests/test_gemini_live.py::test_prewarm_triggered_by_screen_changing - assert _prewarm called with the right screen_id; subsequent screen_changed completes without re-connecting."
    acceptance:
      - "If screen_changing never arrives, screen_changed still works (cold-start handoff path)."
      - "screen_changing is advisory ONLY - server never tears down on it."

  - id: S10
    title: "Timeout / GC: stale Live session cleanup when Flutter goes silent"
    file_scope: ["sena-ai/services/onboarding/src/onboarding/services/gemini_live.py", "sena-ai/services/onboarding/src/onboarding/core/settings.py"]
    depends_on: [S5]
    contract:
      adds: ["GeminiLiveSession._gc_loop() background task; settings.live_session_idle_timeout_sec=300, voice_inactivity_timeout_sec=60"]
    security_tier: 2
    test_requirement: "tests/test_gemini_live.py::test_idle_timeout - fast-forward time; assert WS receives voice_paused; assert handle aclose() ran. NO advance_step fired."
    acceptance:
      - "Timeout closes the Live connection but does NOT close the WS - Flutter can recover."
      - "Per D4, advance_step is never triggered by GC."

  - id: S11
    title: "Back-navigation: screen_changed to a prior screen behaves as new session"
    file_scope: ["sena-ai/services/onboarding/src/onboarding/services/gemini_live.py"]
    depends_on: [S8]
    contract:
      modifies: ["GeminiLiveSession._handoff - no special-casing prior vs next"]
    security_tier: 2
    test_requirement: "tests/test_gemini_live.py::test_back_nav_reuses_forward_path - assert handoff to screen_id already in PRIOR_SCREENS_SUMMARY still injects summary and opens fresh session."
    acceptance:
      - "Per D3, the path is byte-identical to forward navigation."
      - "Prompt for back-nav screen receives current FormState values for that section (already filled)."

  - id: S12
    title: "Resumption (services/resumption.py) verify-and-document - NO code change"
    file_scope: ["sena-ai/services/onboarding/src/onboarding/services/resumption.py"]
    depends_on: []
    contract:
      adds: ["module docstring update documenting per-screen interaction"]
    security_tier: 1
    test_requirement: "Existing resumption tests still pass; add one comment-only docstring assertion in a smoke test."
    acceptance:
      - "Confirmed: resumption_handle remains per-step (issued on advance_step, redeemed on WS reconnect)."
      - "Per-screen handoff does NOT issue handles (pre-warm is in-process)."

  - id: S13
    title: "Rollback flag: SENA_AI_ONBOARDING_PER_SCREEN_SESSIONS env var"
    file_scope: ["sena-ai/services/onboarding/src/onboarding/core/settings.py", "sena-ai/services/onboarding/src/onboarding/services/gemini_live.py"]
    depends_on: [S4, S8]
    contract:
      adds: ["settings.per_screen_sessions: bool = False"]
    security_tier: 1
    test_requirement: "tests/test_settings.py - toggle env, assert handoff branch is skipped; old single-session behaviour preserved."
    acceptance:
      - "Flag off → no behavioural change vs main."
      - "Flag on → S4-S11 active."

  - id: S14
    title: "Audit log: transcript continuity across screen boundary"
    file_scope: ["sena-ai/services/onboarding/src/onboarding/services/gemini_live.py", "sena-ai/services/onboarding/src/onboarding/repositories/state_repo.py (read-only)"]
    depends_on: [S8]
    contract:
      modifies: ["transcript append in g2b - both A's tail and B's first turns land in same Redis transcript key"]
    security_tier: 2
    test_requirement: "tests/test_gemini_live.py::test_transcript_continuity - assert transcript has BOTH A's final user turn AND B's first model turn under same session_id."
    acceptance:
      - "Single Redis transcript key per session_id across all screen handoffs."
      - "NDIS audit trail unbroken - confirmed by S15."

  - id: S15
    title: "Integration test: full step traversal with 3 screen handoffs under feature flag"
    file_scope: ["sena-ai/services/onboarding/tests/test_per_screen_integration.py"]
    depends_on: [S13, S14]
    contract:
      adds: ["test_per_screen_full_step_traversal"]
    security_tier: 2
    test_requirement: "End-to-end with fakeredis + fake genai client - drive 3 screen_changed events; assert: (a) 4 LiveConnectionHandles opened total (1 initial + 3), (b) at most 2 alive at any tick, (c) advance_step gated on validators NOT screen count."
    acceptance:
      - "Passes under flag=true; SKIPs under flag=false."
      - "No regression on existing test_tools.py / test_validators.py."
```

**DAG edges:** `S1→S2, S1→S3, S2→S7, S3→S8, S5→S6, S6→S7, S5→S10, S7→S8, S7→S9, S8→S11, S8→S14, {S4,S8}→S13, {S13,S14}→S15`.

---

## 6. Threat model (STRIDE)

| Threat | Cat | Surface | Mitigation | Residual |
|--------|-----|---------|------------|----------|
| Tenant isolation breach during overlap | I | Two Live sessions on same `session_id` could in principle receive each other's audio. | D1 — single WS holder; `assert_session_owner` checked at WS open and per inbound message; the two Live sessions are internal to one authorised holder; no cross-session Redis touch. | None — by construction, no second tenant can attach. |
| Replay / double-billing | I, R | Same prior-screen summary tokens charged twice if injected during pre-warm AND after cut. | D5 + S7 acceptance test enforces pre-warm payload contains NO summary. | Tokens for system prompt + per-screen schema billed across two sessions during 2s overlap. Acceptable: each is ~150 lines, billed once per session. |
| Partial handoff — new opens, old never closes | A | Bug in S8 ordering; exception between swap and aclose. | S8 uses `asyncio.TaskGroup` so aclose() is in a finally block; S10 GC catches strays after 300s. | A leaked Live session sits idle ≤ 300s; user gets `voice_paused`. |
| Back-nav inconsistency | T | User edits prior-screen field by voice; model didn't see latest FormState. | D3 — full new session reads current FormState in prompt build; screen schema is current; PRIOR_SCREENS_SUMMARY reflects what's actually in FormState. | None — same path as forward nav. |
| Flutter never emits `screen_changed` | A | UI bug / app crash — voice continues against wrong screen prompt. | D4 — 300s wall-clock + 60s voice-inactivity GC; emits `voice_paused`; NEVER auto-advances (preserves human-in-the-loop). | Up to 60s of stale-screen voice before GC fires. Acceptable. |
| In-flight tool race during cut | E | Old session calls `update_field` mid-cut; new session calls same field; ordering ambiguous. | D6 — old session's pending tool turns discarded; FormState effects already committed are durable; `field_updated` emitted once per actual write. | Possible duplicate `field_updated` if both wrote the same field in the same instant — handler is idempotent (last-write-wins on hash). |
| Pre-warm failure cascades | D | Gemini quota exceeded → pre-warm raises → no handoff possible. | S7 acceptance: pre-warm failure logged as WARNING, falls back to cold-start handoff on `screen_changed`. | Audible pause returns to current behaviour (~2s) — graceful degradation. |
| `assert_session_owner` bypass via 2nd connection | S | Attacker opens second WS for same session_id. | `acquire_ws_lock` rejects second WS (existing behaviour, unchanged by D1). | None. |

---

## 7. NDIS compliance check

| Requirement | How preserved |
|-------------|---------------|
| Australian data residency | No change. Gemini Live region pinned via existing `GEMINI_REGION=australia-southeast1` for both A and B handles. |
| Human-in-the-loop on participant records | `advance_step` validator gate unchanged. `screen_changed` does NOT advance step. Per D4, GC does NOT advance. Per S15 acceptance, integration test asserts this. |
| Audit trail continuity | S14 — single Redis transcript key per `session_id` spans all screen handoffs. |
| Tenant isolation | D1 keeps single WS holder; `assert_session_owner` and `acquire_ws_lock` paths unchanged. |
| No participant data in prompt without consent | Prior-screen summary is the same data already in FormState for this participant in this tenant; no cross-tenant or cross-participant data crosses the prompt boundary. |
| No auto-submit | `advance_step` still requires `confirmation_transcript`; per-screen model does not touch this. |

---

## 8. Rollback plan

- **Flag:** `SENA_AI_ONBOARDING_PER_SCREEN_SESSIONS` (`bool`, env-driven via `pydantic-settings`).
- **Default during rollout:** `false`.
- **Effect when false:** `screen_changed` and `screen_changing` WS messages are acknowledged and ignored; `GeminiLiveSession` runs in current single-session-per-step mode. Functionally byte-identical to main.
- **Effect when true:** Full new behaviour active.
- **Promotion criteria:** S15 integration green in staging for ≥ 7 days under flag=true via a single tenant; voice_paused rate < 0.5%; no audit-trail gaps. Then flip default to `true` in a separate PR.
- **Hot rollback:** flip env var, restart pod. No Redis schema migration to undo. No DB migration at all.

---

## 9. Open questions

1. **`screen_changing` advisory — does Flutter commit to emitting it consistently?** If not, S9 becomes optional and audible pause regresses to ~2s on every transition (acceptable per S7 fallback). Needs `sena-mobile` confirmation.
2. **Multi-section screens in current schema?** If every screen is 1:1 with a `SectionSpec`, the `screen_id` field added in S1 may go unused for months. Keep it (zero cost) but flag for schema team.
3. **N:1 screen→section mapping** — `validate_step_complete` still runs against the full `StepSchema` at `advance_step` time. Confirmed-not-blocking: server-side validators see the whole schema. Listed for traceability.
4. **Pre-warm cost at idle tiers** — Free tier (3 concurrent) could hit cap during overlap. Not blocking production (prod tier ≥ 1). Flag for env-tier-aware pre-warm disable if Free-tier demos resurface.
5. **`screen_state` v1/v2 ordering with `screen_changed`** — when both arrive in the same WS turn, which wins? Suggest: `screen_changed` first; subsequent `screen_state` is bound to the new screen. Needs explicit ordering test in S15.
6. **Resumption mid-overlap** — does redeemed handle land on A or B? Per S12, resumption is per-step; redeem path replays last `screen_state` which determines screen. Verify in S15.
