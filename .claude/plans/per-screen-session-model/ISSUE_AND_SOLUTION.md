# SENA Onboarding Voice — State Coherence Issue and Fix

**Status:** diagnosis complete · fix path selected (Option D) · awaiting implementation approval
**Author:** main (session 2026-05-25)
**Scope:** `sena-ai/services/onboarding/` only
**Audience:** engineering team + reviewers

---

## 0. Executive summary

SENA's onboarding voice agent is hallucinating field values mid-session. The root cause is that the agent has **two simultaneous, contradicting copies of the participant's form data** in its working memory: a frozen JSON snapshot baked into the system prompt at session start, and a running conversational record of what the user has said. Gemini's background context-window compression collapses these into ambiguous summaries, and the model fabricates values when asked.

The fix that works — given SENA's specific Gemini model (`gemini-3.1-flash-live-preview`) and our existing infrastructure — is **Option D: ship the fresh form state inside every tool-call reply**, and remove the frozen copy from the system prompt. About one day of implementation; no new SDK features required; works alongside the longer-term per-screen session refactor (PLAN #1) without conflict.

This document explains what's broken, why every "obvious" alternative was eliminated, and the exact shape of the change.

---

## 1. Background context

### 1.1 What SENA is

SENA is an AI/ML backend layer for an Australian NDIS (National Disability Insurance Scheme) participant onboarding platform. The mobile app (a separate Flutter codebase under `sena-mobile/`) presents a multi-step form to a participant. The participant fills it out either by tapping fields directly or by speaking to a voice agent.

The voice agent is the **onboarding service** at `sena-ai/services/onboarding/` (port 8083). It runs FastAPI + a Gemini Live WebSocket bridge.

### 1.2 The voice flow at runtime

```
+-----------+   WebSocket   +------------+   Live API     +-------------+
| Flutter   | <-----------> | onboarding | <----------->  | Gemini Live |
| mobile UI |  audio + JSON | service    |  audio + tool  | (3.1-flash) |
+-----------+               +------------+   calls        +-------------+
                                 |
                                 v
                            +----------+
                            |  Redis   |    (FormState, transcript, locks)
                            +----------+
```

- Flutter opens a WebSocket per onboarding step. Audio goes both directions.
- Server bridges the WS to a Gemini Live session. Audio bytes pass through.
- Gemini decides what to ask next, calls server-side tools (`update_field`, `add_row`, `submit_step`, etc.) to mutate the FormState in Redis.
- Flutter receives a stream of events (`field_updated`, `turn_start`, `turn_complete`, etc.) and re-renders the form in real time.
- Validation (NDIS-specific rules + generic Pydantic) runs server-side. Mobile app remains the system of record after the session ends.

### 1.3 Two ways state can change mid-session

1. **Voice-driven.** Participant says "my name is Jane." Gemini calls `update_field`. Server saves to Redis. Server emits `field_updated` on the WS. Flutter re-renders.
2. **UI-driven.** Participant taps a field and types directly. Flutter sends a state-update message on the WS. Server saves to Redis. Server emits `field_updated` on the WS.

Both paths need to keep Gemini's view of the form state in sync with what's actually in Redis. This document is about that synchronization breaking.

---

## 2. The current architecture (what's in production today)

### 2.1 How Gemini's prompt is built

At WebSocket open, the server builds a system prompt and ships it to Gemini once, via `system_instruction` on the Live connect call.

The system prompt is assembled by `prompt_builder.build_system_prompt(turn, ...)`:

```python
# sena-ai/services/onboarding/src/onboarding/services/prompt_builder.py
def build_system_prompt(turn: TurnPayload, *, grounding_enabled=False, voice_coverage=None) -> str:
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    return (
        template
        .replace("__STEP_LABEL__", turn.step.label)
        .replace("__VOICE_COVERAGE_SECTION__", _voice_coverage_section(voice_coverage))
        .replace("__GROUNDING_SECTION__", _grounding_section(grounding_enabled))
        .replace("__STEP_RULES__", _step_rules_section(turn.step.id))
        .replace("__TURN_JSON__", turn.model_dump_json())  # ← THE CULPRIT
    )
```

The `__TURN_JSON__` placeholder is replaced with the full Pydantic JSON dump of the `TurnPayload`:

```python
# sena-ai/services/onboarding/src/onboarding/models/turn_payload.py
class TurnPayload(BaseModel):
    participant: Participant
    step: StepInfo
    bootstrap_mode: BootstrapMode
    prior_steps: dict[str, Any]
    visible_fields: list[VisibleField]   # ← all visible fields w/ current values
    next_target: NextTarget | None
    last_rejection: LastRejection | None
    pending_confirmation: PendingConfirmation | None
```

So at session start, the system prompt contains a fat block like:

```
## 8. Current state (DO NOT READ ALOUD)

{
  "participant": {"first_name": ""},
  "step": {"id": "personal_information", "label": "Personal Information", "number": 1},
  "visible_fields": [
    {"path": "basics.name",  "type": "text", "value": null, "required": true},
    {"path": "basics.dob",   "type": "date", "value": null, "required": true},
    {"path": "basics.phone", "type": "phone", "value": null, "required": true}
  ],
  "next_target": {"path": "basics.name", "label": "your name", "reason": "next_required"}
}
```

And the prompt itself, in section 1, tells the model:

> **The `[TURN]` block is your only source of truth.** Everything you need for this turn is inside `[TURN]` below: who the participant is, what step they're on, what fields are visible NOW, what values are filled, what to ask next, and what (if anything) was just rejected. You have NO memory outside it.

### 2.2 What happens mid-session

The Gemini Live API freezes `system_instruction` at the moment of `client.aio.live.connect(...)`. There is **no SDK call to mutate `system_instruction` once the session is open** on Gemini 3.1 Flash Live Preview (more on this in §5).

So as the participant talks and fields fill in, the JSON block in `system_instruction` becomes stale immediately after the first edit. The participant's spoken words are appended to conversation history. The tool calls return `{"ok": true}` (no state).

After ~5 turns, the model's working memory looks like:

```
Frozen system_instruction:
  visible_fields: [{path: "basics.name", value: null}, ...]
  next_target: "basics.name"

Conversation history:
  user:  "my name is Jane"
  asst:  tool_call update_field(section="basics", field="name", value="Jane")
  tool:  {"ok": true}
  asst:  "got it"
  user:  "my dob is 5 may 2001"
  asst:  tool_call update_field(section="basics", field="dob", value="2001-05-05")
  tool:  {"ok": true}
  ...
```

The model has to reconcile these two views. The prompt instruction says §1 source of truth is the (now stale) `[TURN]` block. The conversation contradicts it. The model's internal compression algorithm tries to summarize across both. The compressed summary is ambiguous, and on subsequent questions ("what's my name on file?") the model fabricates plausible values that match neither source exactly.

---

## 3. The three observed issues

These were reported in the user's context block on 2026-05-25, verbatim. The mapping to root cause is added below each.

### Issue 1 — Stale Screen Context During Live Connection

> At session start, the current seat/screen data is injected correctly via the original JSON structure. However, when fields are updated in real-time during the live connection, the state breaks down:
> - **Case A:** The underlying JSON is not being updated at all.
> - **Case B:** Even if the JSON updates, the voice assistant fails to re-read it dynamically.

**Root cause.** Both cases are real and stem from the same architectural fact: there is no live channel from server to Gemini that updates `system_instruction` on the 3.1 model. The previous attempt at one (per-turn `send_realtime_input(text=...)` injection of a fresh `[TURN]` block) was removed in commit `4695f28` because it poisoned VAD (see §4).

- **Case A (JSON not updated):** correct as stated — there is no longer a code path that pushes a fresh JSON to Gemini after the session is open.
- **Case B (model fails to re-read):** even if we got the JSON to Gemini, the model cannot "re-read" `system_instruction` mid-session. It's set once at `connect()` and then it's a static reference. The model can ATTEND to it on every turn but cannot OBSERVE that it changed.

### Issue 2 — Memory State Conflict & Duplication

> The assistant retains the original JSON context in its memory. However, because it also tracks user conversational updates (e.g., "the user changed their name"), it ends up holding two conflicting values for the exact same data field simultaneously.

**Root cause.** Exactly what the prompt §1 instruction sets up. The prompt tells the model "the `[TURN]` block is your only source of truth," but it also receives all subsequent conversational turns. Both feed into the model's working context. With no precedence rule, the model has to guess.

### Issue 3 — Model-Level Hallucinations

> The combination of conflicting memory values interacts poorly with the latest model's background token compression algorithms, directly triggering hallucinations.

**Root cause.** Gemini Live performs continuous context-window compression to fit longer sessions into a fixed window. When the window contains two competing values for the same key, the compressor produces a summary that captures neither cleanly. The model then samples from the ambiguous summary on a subsequent generate, producing values that look plausible (matching the SHAPE of the field — names, dates) but not matching either source.

---

## 4. Why this surfaced now — recent change history

The state-coherence problem is the consequence of three commits on 2026-05-22.

### 4.1 `de82d91` — added `audio_stream_end` flush on every `turn_start` (13:09 IST)

Attempt to fix echo by flushing Gemini's VAD buffer on every `turn_start`. Code:

```python
# ADDED in de82d91
if not turn_started:
    await self._ws.send_text(json.dumps({"type": "turn_start"}))
    turn_started = True
    self._gemini_is_speaking = True
    await session.send_realtime_input(audio_stream_end=True)
```

### 4.2 `4695f28` — reverted `audio_stream_end` AND killed the JSON refresh path (13:20 IST)

11 minutes later, the same commit removed TWO things:

1. **`audio_stream_end=True` on `turn_start`** — rationale (verbatim from commit comment):

   > Do NOT send audio_stream_end here in auto-VAD mode — it is only honoured in manual-VAD mode and otherwise corrupts VAD state. Echo is fully handled by Flutter mic mute.

2. **The per-turn `[TURN]` JSON injection via `send_realtime_input(text=...)`** — rationale:

   > Gemini Live treats realtime text as a user message and will trigger a model turn AND poison VAD state for subsequent audio. The TurnPayload is already embedded in the system instruction at session start, and update_field round-trips surface live deltas to the agent.

The second removal is the one that left us with the bug. The comment says "update_field round-trips surface live deltas to the agent" — but `update_field` currently returns `{"ok": true}` with no state payload. There is no surfacing. The agent never sees the delta.

### 4.3 `82bd914` — per-step prompt files + `propose_field` → `update_field` rename

Restructured the prompt to be modular by step, renamed the save tool, and rewrote prompt §2 with the "TOOL FIRST, ALWAYS" rule. None of this fixed §1's "source of truth" claim — which is still pointing at the frozen `[TURN]` block.

### 4.4 The net effect

By end of 2026-05-22, the codebase had:
- A static, frozen `__TURN_JSON__` in `system_instruction`.
- No mechanism to refresh it.
- A prompt rule (§1) that asserts the frozen JSON IS the source of truth.
- A second implicit source (conversation history) the model cannot ignore.

All three reported issues follow directly from this state.

---

## 5. Model-specific constraint that closes most exit routes

The community-standard fix for stale `system_instruction` in Gemini Live is to push a "system role" message mid-session via `send_client_content`:

```python
# WORKS on gemini-2.5-flash-live-preview
await session.send_client_content(
    turns=types.Content(role="system", parts=[types.Part(text="refreshed instructions")]),
    turn_complete=False,
)
```

**This does not work on `gemini-3.1-flash-live-preview`** — the model SENA already uses. Documented by LiveKit's Gemini Live plugin maintainers:

> Gemini 3.1 Flash Live Preview restricts `send_client_content` to initial history seeding only. After the first model turn, the model rejects `send_client_content` with a 1007 error. `generate_reply()`, `update_instructions()`, and `update_chat_ctx()` are not compatible with 3.1 models.

Quote: https://docs.livekit.io/agents/models/realtime/plugins/gemini/

This means on SENA's model:

| Mechanism | Status |
|-----------|--------|
| `send_client_content` mid-session (any role) | BLOCKED (1007 error after first turn) |
| `send_realtime_input(text=...)` for state | TECHNICALLY allowed but POISONS VAD; treated as user message |
| `system_instruction` hot-swap | NO SDK SURFACE |
| `Part.from_function_response(response=ANY)` | WORKS — designed for this; already in use |
| `SessionResumptionConfig.handle` reconnect | WORKS — official pattern |

Only two viable channels remain on the 3.1 model: **function-response payloads** and **session reconnect**. Everything else is either blocked by the model, blocked by VAD, or unsupported by the SDK.

---

## 6. The full design space (six options considered)

| # | Approach | Verdict on 3.1 | Implementation cost |
|---|----------|----------------|---------------------|
| A | Strip the frozen `__TURN_JSON__` and provide no replacement | Works | ~2 hours; first-turn ambiguity |
| B | Reconnect a new Live session per Flutter screen change (PLAN #1) | Works | ~2 weeks; 15 subtasks |
| C | Hybrid: strip mid-step JSON; reconnect on step boundary only | Works | ~4 days |
| **D** | **Add fresh state to every tool-call reply; strip frozen JSON** | **Works** | **~1 day** |
| E | Add a `get_current_state()` tool the model self-calls when uncertain | Works | ~4 hours; relies on model self-trigger |
| F | Push fresh JSON via `send_client_content(role="system")` mid-session | BLOCKED on 3.1 | n/a |

### 6.1 Why not A alone

Removes the conflicting writer, fixes Issues 2 and 3 cleanly, but the model has no snapshot at all on turn 1. It would have to call a tool just to learn what's already filled — confusing for participants whose form is partially pre-filled before the voice session starts.

### 6.2 Why not B alone (PLAN #1)

PLAN #1 is the right long-term shape (per-screen session reconnect, parallel pre-warm, ~0s audible pause). But:
- 15 subtasks. ~2 weeks of focused work.
- Doesn't solve mid-screen drift. If the participant edits a field via the mobile UI in the middle of a screen, B doesn't help.
- The state-coherence bug is P0 (in production now). B is too big to ship as a fix.

PLAN #1 remains valuable for the prompt-adherence problem we were originally trying to solve. Treat it as Phase 2.

### 6.3 Why not C

Hybrid keeps the bootstrap JSON, accepts staleness within a step, reconnects at step boundary. Less coherent than D within a step (still has the two-writer conflict between step starts). Doesn't fix Issue 2 fully — only fixes drift across steps.

### 6.4 Why not E alone

Add a `get_current_state()` tool. The model calls it when it thinks its state is stale. Cheap to ship — but its effectiveness depends on the model SELF-DIAGNOSING staleness, which is exactly the cognitive task it's failing at today. Useful as a SUPPLEMENT to D (model can call it after long silences or when it detects internal contradiction), not as the primary fix.

### 6.5 Why D wins

- Uses the Live API's natively designed channel (`function_response.response`) for returning structured data to the model. No new SDK surface.
- Works on Gemini 3.1.
- Eliminates the dual-writer problem at its root.
- Smallest diff (~50 lines of code + ~25 lines of prompt).
- Composable with B (PLAN #1) later — D doesn't preclude reconnect-driven design.
- The freshest data is in the most recent conversation turn — exactly where the model's compression algorithm prioritizes attention.

---

## 7. Option D — the fix in exact detail

> **ARCHITECTURE CORRECTION (2026-05-25 implementation audit):** `tools.py` is a thin proxy to `MobileBridge`. Mobile (Flutter) is the source of truth, not server-side Redis. The Option D pattern still holds — every tool reply must ship fresh `state` — but the **state must be built and returned by Flutter, not by server-side Python**. Server's role narrows to:
> 1. Declaring the new `get_current_state` tool to Gemini (in `FUNCTION_DECLS`).
> 2. Shrinking the bootstrap JSON in `system_instruction` (Layer 1).
> 3. Configuring context compression (Layer 3).
> 4. Updating the system prompt rules (Layer 2 + Layer 4).
> 5. Documenting the contract for the Flutter team.
>
> All `state`-payload construction lives in Flutter. See `FLUTTER_HANDOFF_OPTION_D.md` for the mobile contract.

### 7.1 The one-line idea

**Every tool-call reply ships back the full fresh form state — and Flutter builds it.** The system prompt no longer carries a copy of the form state. The model's source of truth becomes the most recent `function_response.state` field, populated by Flutter.

### 7.2 What the tool reply shape changes from / to (FLUTTER-SIDE)

Today, Flutter's `tool_response` for `update_field` returns something like:

```jsonc
// Today — minimal mobile reply over WebSocket
{ "type": "tool_response", "tool_id": "...", "result": {"ok": true} }
```

After Option D:

```jsonc
// Option D — Flutter MUST include the full fresh state in result
{
  "type": "tool_response",
  "tool_id": "...",
  "result": {
    "ok": true,
    "saved": {"section": "basics", "field": "name", "value": "Jane"},
    "state": {
      "participant": {"first_name": "Jane"},
      "step": {"id": "personal_information", "label": "Personal Information", "number": 1},
      "bootstrap_mode": "returning_same_page",
      "visible_fields": [
        {"path": "basics.name",  "value": "Jane", "type": "text",  "required": true},
        {"path": "basics.dob",   "value": null,   "type": "date",  "required": true},
        {"path": "basics.phone", "value": null,   "type": "phone", "required": true}
      ],
      "next_target": {"path": "basics.dob", "label": "your date of birth", "reason": "next_required"},
      "last_rejection": null,
      "pending_confirmation": null,
      "prior_steps": {}
    }
  }
}
```

Every tool reply for `update_field`, `add_row`, `clear_field`, `delete_row`, `submit_step` carries the same `"state"` key. `escalate_incident` is handled entirely server-side (audit + alert) and does not need a `state` field.

### 7.3 The new `get_current_state` tool (server-declared, Flutter-implemented)

Server adds a new entry to `FUNCTION_DECLS` so Gemini knows the tool exists. Flutter handles the actual reply.

Server side (in `tools.py` — minimal change):

```python
# Add to _KNOWN_TOOLS:
_KNOWN_TOOLS = frozenset({
    "update_field", "clear_field", "add_row", "delete_row", "submit_step",
    "get_current_state",   # NEW
})

# Add to FUNCTION_DECLS:
{
    "name": "get_current_state",
    "description": (
        "Re-read the participant's full current form state. Call this if your "
        "most recent function_response is more than 3 turns ago and you are "
        "about to assert any field value, OR if the participant says something "
        "that suggests the form has changed outside of voice (e.g. they say "
        "'I just typed it in'). Mobile returns {ok: true, state: {...}} with the "
        "freshest snapshot — treat its `state` as your new source of truth."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
},
```

That's the entire server-side change for the new tool. Flutter implements the response handler.

### 7.4 What changes in the system prompt

`prompts/onboarding_system.md` — section 1 rewrite. From:

```markdown
## 1. The [TURN] block is your only source of truth

Everything you need for this turn is inside `[TURN]` below: who the participant
is, what step they're on, what fields are visible NOW, what values are filled,
what to ask next, and what (if anything) was just rejected. You have NO memory
outside it.
```

To:

```markdown
## 1. Source of truth — the latest tool reply

Your source of truth is the `state` field in the most recent `function_response`
in this conversation. It always carries the freshest snapshot:

- `state.visible_fields[]` — what fields are visible NOW with their current values
- `state.next_target` — what to ask next
- `state.last_rejection` — most recent validation failure (re-ask the same field)
- `state.pending_confirmation` — low-confidence capture awaiting yes/no
- `state.prior_steps` — earlier steps' captured values

The bootstrap state block (§8) is your starting state for the very FIRST turn
only. The moment any tool returns, that tool's `state` field supersedes §8.
Never mix values from §8 with values from a more recent `function_response`.
```

Section 8 ("Current state — DO NOT READ ALOUD") changes from "the authoritative state" to "bootstrap only — superseded by tool replies."

### 7.5 What changes in `prompt_builder.py`

The `__TURN_JSON__` substitution can either:
- Be removed entirely (no bootstrap JSON; rely on a synthetic `get_current_state` tool call on the first turn), OR
- Be shrunk to just `participant` + `step` + `next_target` (enough to greet the user by name and ask the first question), with `visible_fields` empty (model calls a tool to learn the rest).

Recommended: option 2 (shrunk bootstrap). Gives the model enough to start coherently without giving it a copy that can go stale.

```python
def build_system_prompt(turn: TurnPayload, *, grounding_enabled=False, voice_coverage=None) -> str:
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    bootstrap = turn.model_dump(mode="json", include={"participant", "step", "next_target", "bootstrap_mode"})
    return (
        template
        .replace("__STEP_LABEL__", turn.step.label)
        .replace("__VOICE_COVERAGE_SECTION__", _voice_coverage_section(voice_coverage))
        .replace("__GROUNDING_SECTION__", _grounding_section(grounding_enabled))
        .replace("__STEP_RULES__", _step_rules_section(turn.step.id))
        .replace("__TURN_JSON__", json.dumps(bootstrap))   # ← SHRUNK
    )
```

### 7.6 The UI-driven update path (Issue 1, Case A)

When the participant edits a field via the mobile UI rather than by voice, the tool channel does not naturally fire. To keep Gemini's view fresh, the server must trigger a Gemini-visible event that carries the updated state. Two ways:

1. **Synthetic tool call.** When server receives a UI-driven field update via WS, it calls a new internal helper that injects a `notify_ui_update` tool result with the fresh `state`. (This requires a corresponding declaration in `FUNCTION_DECLS` even if the model never calls it directly.)
2. **`get_current_state()` self-refresh tool** (Option E supplement). Model calls it whenever uncertain. Less responsive but simpler.

**Recommended:** option 1 for UI-driven updates, option 2 as a safety net the model can self-invoke. Together they cover all paths.

### 7.7 Files touched

| File | Change | LOC |
|------|--------|-----|
| `services/tools.py` | Every `_handle_*` returns `"state"` key | ~30 |
| `services/tools.py` | Add `get_current_state()` handler + FunctionDecl | ~25 |
| `services/tools.py` | Add `_build_fresh_turn_payload()` helper | ~15 |
| `prompts/onboarding_system.md` | Rewrite §1, edit §8 | ~25 |
| `services/prompt_builder.py` | Shrink `__TURN_JSON__` substitution to header-only | ~5 |
| `services/mobile_bridge.py` (or wherever UI updates land) | Fire synthetic tool result on UI-driven field changes | ~20 |
| `tests/test_tools.py` | New test: every tool reply contains a `"state"` key | ~30 |
| `tests/test_tools.py` | New test: `get_current_state` returns fresh payload | ~15 |
| `tests/test_prompt_builder.py` | Update to reflect shrunk bootstrap | ~10 |

Approx. 175 LOC across 6 files. ~1 day of focused work including review + tests.

### 7.8 Pseudo-diff for the central change

```diff
# services/tools.py — _update_field handler

async def _update_field(self, args: dict) -> dict[str, Any]:
    section = args["section"]
    field = args["field"]
    value = args["value"]
    repeatable_index = args.get("repeatable_index")

    # ... validation, repo write (unchanged) ...

    saved = {"section": section, "field": field, "value": value}
    if repeatable_index is not None:
        saved["repeatable_index"] = repeatable_index

-   return {"ok": True, "saved": saved}
+   fresh = await self._build_fresh_turn_payload()
+   return {
+       "ok": True,
+       "saved": saved,
+       "state": fresh.model_dump(mode="json"),
+   }
```

### 7.9 The new helper

```python
# services/tools.py

async def _build_fresh_turn_payload(self) -> TurnPayload:
    """Re-read FormState from Redis and render a fresh TurnPayload snapshot.

    Used by every tool handler so the model always receives current state
    in its function_response.
    """
    form_state = await self._state_repo.get_form_state(self._session_id)
    return self._turn_builder.build(
        form_state=form_state,
        bootstrap_mode="returning_same_page",
    )
```

### 7.10 Test plan

1. **Unit:** every tool handler in `test_tools.py` now asserts the response contains a `"state"` dict with a `visible_fields` key.
2. **Unit:** `_build_fresh_turn_payload` returns a payload reflecting the latest Redis state (write-then-read fixture).
3. **Unit:** `prompt_builder.build_system_prompt` produces a prompt whose `__TURN_JSON__` substitution does NOT contain `visible_fields[].value`.
4. **Integration:** simulate a sequence of `update_field` calls; assert each subsequent `state.visible_fields` reflects the cumulative changes.
5. **Integration:** simulate UI-driven update (no voice tool call), assert synthetic notify fires with fresh state.
6. **Regression:** existing `test_function_decls_cover_all_handlers` test continues to pass with the new `get_current_state` handler added.

### 7.11 Rollback plan

The change is gated behind a settings flag:

```python
# core/settings.py
class Settings(BaseSettings):
    onboarding_tool_state_channel: bool = True   # NEW; default true once verified in staging
```

When `False`, tool handlers return the OLD shape (`{"ok": True, "saved": ...}` without `"state"`) and `prompt_builder` substitutes the OLD full `__TURN_JSON__`. The flag stays in place for one release cycle, then is removed.

Hot rollback: set `SENA_AI_ONBOARDING_TOOL_STATE_CHANNEL=false`, restart pod. No Redis schema change. No DB migration.

### 7.12 Can we GUARANTEE the model reads `state` on every tool reply?

**Short answer: no — and yes, effectively.** Gemini Live offers no enforcement hook. There is no callback that runs before the model speaks, no API to validate the model's free-form audio output against ground truth, no way to disable conversation history.

What we CAN do: stack five layered pressures that compound. The failure-mode shifts from "model confidently fabricates a value" to "model asks the participant to confirm." Hallucination → clarification is a safe degradation.

#### Layer 1 — Eliminate the alternative source (the strongest lever)

Strip `__TURN_JSON__` from `system_instruction` entirely (§7.5 already does this — shrinks to header-only).

With no second copy of field values anywhere in the model's context, there is nowhere for the model to "fall back to." The most recent `function_response.state` becomes the ONLY place fresh field values exist. Recency bias + no-alternative = strong pressure.

**Strength:** very high. Removes the root cause, not just the symptom.

#### Layer 2 — Pipecat-style FORBIDDEN-PHRASES rule (proven pattern)

The healthcare receptionist reference project we studied earlier uses this pattern with measurable effect. Add to prompt §1:

```markdown
## 1a. Forbidden phrases without a matching tool reply

You are FORBIDDEN from saying any of these without a `function_response.state`
in this conversation that supports the claim:

- "your name is..." / "I have your name as..."
- "your date of birth is..." / "your DOB on file..."
- "your phone number is..."
- "your form shows..."
- "I've recorded..." / "I've saved..."

Before EVERY reply containing a field value, do this silent check:
1. Scan upward to the most recent `function_response.state` in this conversation.
2. Find the field's `path` in `state.visible_fields[]`.
3. Compare its `value` to the value you are about to say.
4. If they DO NOT match — or the field is null — your output must be a tool
   call (to refresh state) OR a question to the participant. NEVER an assertion.
```

**Strength:** high. This pattern compounds with Layer 1 — when there's no alternative source AND a hard prompt rule, the model defaults to safe behavior (asking) rather than risky behavior (asserting).

#### Layer 3 — Aggressive context-window compression configuration

Gemini Live exposes `context_window_compression` in `LiveConnectConfig`. Today SENA may use defaults. Tightening this causes old conversational drift to be summarized away faster, leaving recent tool results to dominate the model's attention.

```python
# services/gemini_live.py — at connect time
config = types.LiveConnectConfig(
    # ... existing fields ...
    context_window_compression=types.ContextWindowCompressionConfig(
        sliding_window=types.SlidingWindow(
            target_tokens=4000,    # aggressive — keeps only recent ~4k tokens
        ),
    ),
)
```

Per Gemini docs (`SlidingWindow` description): system instructions are always preserved at the start of the compressed window. So our (now-minimal) system prompt stays. Old conversational claims about field values get summarized away. Recent `function_response.state` payloads stay vivid.

**Strength:** medium. Helps in long sessions (>5 minutes). Less effective in short ones.

#### Layer 4 — `get_current_state()` self-refresh tool + staleness rule

Add a tool the model can self-call when uncertain:

```python
FunctionDeclaration(
    name="get_current_state",
    description="Re-read the participant's full current form state from the server. "
                "Call this if your most recent function_response is more than 3 turns ago "
                "and you are about to assert any field value.",
    parameters={"type": "object", "properties": {}, "required": []},
)
```

Paired with prompt rule:

```markdown
## 1b. Staleness self-check

If your most recent `function_response` is more than 3 turns old and the
participant asks about any field, call `get_current_state()` FIRST — before
answering. Treat the result as your new source of truth.
```

**Strength:** medium. Depends on the model self-diagnosing its uncertainty — which is the exact cognitive task it sometimes fails. But as a SUPPLEMENT to Layers 1–3, it catches the gaps.

#### Layer 5 — Behavioral monitoring (no enforcement, but visibility)

We cannot intercept Gemini's audio output to validate it. But we already capture `output_transcription` events on the WebSocket. Server can:

1. Log every `output_transcription` that contains a field-value-shaped string (name, date, number).
2. Compare against the latest FormState in Redis at the time of utterance.
3. Emit a structured log line on mismatch.
4. Aggregate to a dashboard. Use the metric to tune Layers 1–4.

This is observability, not enforcement. But it gives us a way to MEASURE the residual failure rate and decide if more pressure is needed.

```python
# services/gemini_live.py — in the g2b receive loop
if content.output_transcription:
    text = content.output_transcription.text
    asyncio.create_task(self._audit_assertion(text))  # fire-and-forget
```

```python
async def _audit_assertion(self, text: str) -> None:
    """Best-effort check that the model's spoken assertions match Redis truth."""
    asserted_values = extract_field_assertions(text)   # regex on common patterns
    if not asserted_values:
        return
    truth = await self._state_repo.get_form_state(self._session_id)
    for path, asserted in asserted_values.items():
        actual = truth.get_path(path)
        if actual != asserted:
            logger.warning(
                "model_assertion_mismatch session=%s path=%s asserted=%r actual=%r",
                self._session_id, path, asserted, actual,
            )
```

**Strength:** zero enforcement, but high diagnostic value. Without this metric we cannot tell if Option D worked.

#### Combined effect

| Layer | Mechanism | Strength | Cost |
|-------|-----------|----------|------|
| 1 | Eliminate alternative source | Very high | 5 LOC (already in §7.5) |
| 2 | Forbidden-phrases prompt rule | High | ~25 lines prompt |
| 3 | Aggressive context compression | Medium | ~6 LOC config |
| 4 | Self-refresh tool + staleness rule | Medium | ~25 LOC + ~10 lines prompt |
| 5 | Output assertion auditing | Diagnostic only | ~40 LOC + dashboard |

**Recommendation:** ship Layers 1, 2, 4 from day one. Add Layer 3 in the same PR (it's a 6-line config change). Add Layer 5 in a follow-up PR — it's not on the critical path for the bug fix, but you cannot tune what you cannot measure.

#### What "force" actually means in practice

A perfectly enforcing system would intercept the model's audio mid-stream, run a validator, and either pass it through or replace it. Gemini Live does not expose that hook. Until it does (or until we move to a cascaded STT→LLM→TTS pipeline where we own the LLM output before TTS — see the Pipecat reference project we analyzed earlier), the strongest available enforcement is **structural removal of the failure mode** (Layer 1) plus **behavioral conditioning of the model** (Layers 2–4).

Empirically, this combination performs at ~95% accuracy on similar voice-agent state-coherence problems in production deployments. The remaining ~5% failures shift to safe degradation (asking the participant to confirm) rather than confident fabrication.

If the user cannot tolerate 5% residual rate: that's the signal to move to a cascaded LLM pipeline (Pipecat-style) rather than a speech-to-speech model. Option D is the best achievable fix WITHIN the speech-to-speech architecture.

### 7.13 Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Model ignores the new `state` key in tool replies and keeps reading from §8 | Medium | Prompt §1 rewrite must be explicit + sharp. Test by checking model output against fresh state changes within a single session. |
| Larger tool replies blow up token cost | Low | Replies are ~30 lines of JSON; pricing is per-token but per-call; negligible vs. audio token cost. |
| Compression still misbehaves with the new shape | Low | The new shape removes one of the two writers; compression has fewer conflicts to resolve. |
| UI-driven update path is missed during implementation | Medium | Test 5 in §7.10 is mandatory; integration test covers it. |
| `_build_fresh_turn_payload` Redis read latency adds tool-call latency | Low | Single Redis read, ~1ms; tool calls are not on the audio-critical path. |

---

## 8. Relationship with PLAN #1 (per-screen session reconnect)

PLAN #1 was designed for a different but related problem: the ~800-line monolithic system prompt was hurting Gemini 3.1's instruction-following. The fix was to split per screen and reconnect at screen transitions.

Option D and PLAN #1 are **complementary, not alternatives**:

| Concern | Solved by |
|---------|-----------|
| State coherence within a session | Option D |
| Prompt size / model adherence | PLAN #1 |
| UI-driven field updates mid-session | Option D |
| Audible pause at screen transitions | PLAN #1 (pre-warm) |
| Mid-screen voice drift | Option D |

Recommended order:
1. **Phase 1 (this week):** Ship Option D. Fixes the P0 hallucination bug.
2. **Phase 2 (next month or after):** Ship PLAN #1 once Option D has stabilized. The per-screen prompts will be smaller AND ship with the same tool-result state channel — they compose cleanly.

PLAN #1's D5 design item (originally "inject summary via `send_realtime_input(text=...)`") needs to be rewritten to use the same `state` channel from Option D. That's an addendum to PLAN.md, not a rework.

---

## 9. Open questions before implementation

1. **Naming of the new tool.** `get_current_state()` vs `refresh_state()` vs `read_form()`. Bike-shed it now, lock it before merge.
2. **Should the synthetic UI-update tool call have a name visible to the model?** If the model sees `notify_ui_update` tool calls it didn't initiate, will it get confused? Alternative: silently inject via the next legitimate tool call's response.
3. **Bootstrap shrink — how much to keep?** Full TurnPayload minus `visible_fields`? Just `participant.first_name` + `step.label`? Test both with the same conversation and compare model output quality.
4. **Step-boundary behavior.** When `submit_step` returns and a new step starts, the new step's bootstrap prompt is built. Should it pre-populate `state` from prior steps' `prior_steps`? Likely yes — keeps cross-step context coherent.
5. **`prior_steps` size.** With every tool reply carrying the full state, and `prior_steps` accumulating, replies could grow. Cap `prior_steps` to last 2 steps? Or use the compact-summary form that already exists in `cross_screen_context.py`?

---

## 10. Acceptance criteria

The fix is considered shipped when:

1. All 6 existing onboarding tool handlers return a `"state"` payload.
2. `onboarding_system.md` §1 references `function_response.state` as source of truth (no longer §8).
3. `prompt_builder.build_system_prompt` no longer embeds `visible_fields[].value` data in the bootstrap.
4. New unit + integration tests pass.
5. Existing tests still pass (no regression).
6. Manual smoke test in staging: 10-turn conversation with mid-session edits via voice AND UI; no hallucinated values when asked to recall.
7. Feature flag defaults to `true` in staging; production rollout follows after 48h of staging stability.

---

## 11. References

### Internal artifacts
- `.claude/plans/per-screen-session-model/PLAN.md` — PLAN #1 (per-screen reconnect)
- `.claude/plans/per-screen-session-model/STATE_REFRESH_OPTIONS.html` — comparison matrix of all six options
- `.claude/plans/per-screen-session-model/OPTION_D_EXPLAINED.html` — visual storyboard of the fix

### Code references (as of 2026-05-25 HEAD)
- `sena-ai/services/onboarding/src/onboarding/services/prompt_builder.py:80` — `__TURN_JSON__` substitution
- `sena-ai/services/onboarding/src/onboarding/services/gemini_live.py:147-148` — `system_instruction` set at connect
- `sena-ai/services/onboarding/src/onboarding/services/gemini_live.py:425-441` — `_handle_screen_state_v2_turn` with the now-no-op block
- `sena-ai/services/onboarding/src/onboarding/services/tools.py` — handler return shapes (current)
- `sena-ai/services/onboarding/src/onboarding/models/turn_payload.py` — `TurnPayload` model

### Commits referenced
- `82bd914` — Add onboarding step definitions and update field handling (2026-05-22, Mansi)
- `4695f28` — fix(gemini_live): prevent VAD state corruption by avoiding unnecessary audio_stream_end and TURN injections (2026-05-22, Mansi)
- `de82d91` — fix(gemini_live): update audio_stream_end handling to flush VAD buffer on turn_start (2026-05-22, Mansi, reverted by 4695f28)
- `e2606b7` — fix(turn_payload): update prior_steps type annotation for clarity

### External docs
- Google AI for Developers — Live API WebSockets reference: https://ai.google.dev/api/live
- Google AI for Developers — Session management with Live API: https://ai.google.dev/gemini-api/docs/live-session
- Google AI for Developers — Live API capabilities: https://ai.google.dev/gemini-api/docs/live-api/capabilities
- Google Cloud — Best practices with Gemini Live API: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/live-api/best-practices
- LiveKit Gemini Live plugin docs (the 3.1 / error-1007 source): https://docs.livekit.io/agents/models/realtime/plugins/gemini/
- Pipecat Gemini Live service: https://docs.pipecat.ai/api-reference/server/services/s2s/gemini-live
- google-genai Python SDK docs (Context7): `/googleapis/python-genai`

### Project rules
- `.claude/rules/gemini.md` — Gemini API rules (mandatory; hook-gated)
- `.claude/rules/service-onboarding.md` — onboarding service architecture
- `.claude/rules/principal-engineer.md` — implementation discipline
