# SENA Voice Architecture — Complete Guide

> Unified architecture doc explaining how the voice services (case_review, onboarding) work, what each file does, which APIs are exposed, and how the recent input-token-reduction changes fit together.

---

## Table of Contents
1. [Overview](#overview)
2. [The Three Voice Services](#the-three-voice-services)
3. [Shared Voice Engine](#shared-voice-engine) — the foundation
4. [case_review Voice (Gemini Live WebSocket)](#case_review-voice--gemini-live-websocket)
5. [onboarding Voice (Gemini Live WebSocket)](#onboarding-voice--gemini-live-websocket)
6. [Data Flow — A Complete Example](#data-flow--a-complete-example)
7. [Recent Input-Reduction Work](#recent-input-reduction-work)
8. [File-by-File Reference](#file-by-file-reference)
9. [API Matrix](#api-matrix)

---

## Overview

SENA has **two independent voice services**, both powered by **Google Gemini Live** (WebSocket bidirectional voice streaming):

1. **case_review** — Support workers dictate shift case notes post-shift. The agent guides them through required fields (summary, activities, wellbeing, safety, outcomes, feedback, incident). Speech → Structured NDIS case note.

2. **onboarding** — Participants or staff complete onboarding forms via voice. The agent asks questions field-by-field, collects values, and validates. Speech → Structured enrollment data (name, DOB, address, emergency contacts, etc.).

**Both services share a common Gemini Live engine** (`shared/src/sena_common/voice/`), which handles:
- WebSocket lifecycle (connect, send audio, receive audio/tool calls)
- Tool dispatching (update_field, submit_step, etc.)
- Form state management (Redis-backed — both services persist to Redis)
- Screen delta tracking (12x token saving by only sending changed fields)
- Lazy prompt-fragment injection (on-demand rule loading)

---

## The Three Voice Services

### 1. case_review/voice (Dictation + Analysis)

**Where**: `/home/main/SENA/services/case_review/voice/`

**What it does**:
- REST endpoint creates a voice session
- WebSocket (`/ws/case-review/voice/{session_id}`) opens a Gemini Live session
- Worker speaks their shift; agent guides them through the case-note form
- After session: form is finalized and sent to `/v1/case-review/incidents/analyze` for restrictive-practice detection

**Key files**:
- `prompts/` — the system prompt (base template + step-specific rules)
- `prompts/fragments.py` — on-demand rules (lazy-loaded when conditions trigger)
- `prompts/steps/staff_case_note.py` — the only multi-field step; rules for each field
- `casenote_schema.py` — schema definition (17 fields across 5 sections)
- `tool_decls.py` — the 7 tools the agent can call
- `drafter.py` — standalone endpoint that converts raw transcript → form fields

**REST APIs**:
```
POST   /v1/case-review/voice/session          — create session, get ws_url
POST   /v1/case-review/voice/draft            — transcript → initial_values
WS     /ws/case-review/voice/{session_id}     — Gemini Live session
```

**WebSocket users**:
- Flutter app (iOS/Android) — opens the WS when user taps "Dictate Case Note"

---

### 2. onboarding/voice (Collection + Bootstrap)

**Where**: `/home/main/SENA/services/onboarding/api/routes.py`

**What it does**:
- REST endpoint creates a voice session
- WebSocket (`/ws/onboarding/{session_id}`) opens a Gemini Live session
- Participant/staff speaks their details; agent collects and validates
- After session: form is submitted to app backend via signed webhook

**Key files**:
- `prompts/onboarding_system.py` — the 206-line base system prompt (rules for field extraction, Aussie phrasing, error handling)
- `prompts/steps/` — step-specific rules (one per onboarding page)
- `voice/prompt_builder.py` — builds the system prompt by injecting step rules (onboarding uses its own fork, not shared)
- `voice/gemini_live.py` — onboarding's own Gemini Live session handler (not shared; separate from case_review)
- `api/routes.py` — session create, state get/put, complete, errors

**REST APIs**:
```
POST   /v1/onboarding/session                 — create session, get ws_url
GET    /v1/onboarding/session/{id}/state      — read form state
PUT    /v1/onboarding/session/{id}/state      — update form state (non-voice)
POST   /v1/onboarding/session/{id}/complete   — mark complete, fire webhook
WS     /ws/onboarding/{session_id}            — Gemini Live session
```

**WebSocket users**:
- Flutter app (iOS/Android) — opens the WS when user enters onboarding flow

---

### 3. shared/src/sena_common/voice (The Common Engine)

**Where**: `/home/main/SENA/services/shared/src/sena_common/voice/`

**What it does**:
- Wraps Google Gemini Live WebSocket into a stateful session manager
- Handles tool calls, form state updates, delta-screen tracking, fragment injection
- Used by **case_review** only (onboarding uses its own fork)

**Key files**:
- **`gemini_live.py`** — the main `GeminiLiveSession` class
  - Manages WebSocket lifecycle
  - Sends/receives audio frames
  - Dispatches tool calls
  - Tracks screen delta (only sends changed fields)
  - Injects lazy-load fragments (rules that appear on-demand)
  
- **`prompt_builder.py`** — builds the system prompt
  - Takes a `TurnPayload` (current form state + visible fields)
  - Injects step rules (callable-based, so rules can reference visible fields)
  - Optionally appends fragment pointers
  - Returns the full system prompt
  
- **`prompt_fragments.py`** (NEW — added this session)
  - `PromptFragment` dataclass (key, text, pointer, trigger condition)
  - `FragmentRegistry` — a named set of fragments
  - `InjectedFragmentTracker` — tracks which fragments have been injected (fires once)
  - Implements the on-demand rule loading mechanism
  
- **`screen_delta.py`** — delta tracking
  - `ScreenDeltaTracker` — remembers baseline state
  - `ScreenStateDelta` — computes added/removed/changed fields
  - Saves ~12x tokens by only mentioning new fields to the agent
  
- **`turn_payload.py`** — the state model
  - `TurnPayload` — what the agent receives each turn (visible fields, next target, etc.)
  - `Participant`, `StepInfo`, `VisibleField` — models for form metadata

- **`form_state.py`** — form state model
  - `FormState` — the agent's working state (field values, validation errors, etc.)

- **`state_repo.py`** — form storage
  - `FormStateRepo` — Redis-backed storage. **Both** case_review (shared engine, Redis db=1) and onboarding (its own fork, Redis db=0) persist to Redis; there is no in-memory backend in production.

- **`tool_dispatcher.py`** — tool call handling
  - Routes tool calls (update_field, submit_step, etc.) to the right handler
  - Waits for tool responses from the client before continuing

---

## Shared Voice Engine

### How it works — the lifecycle

```
1. SERVICE creates TurnPayload from form schema + current state
   ├─ visible_fields = all schema fields that exist in current step
   ├─ next_target = which field to ask next
   └─ prior_steps = (optional) context from earlier steps

2. SERVICE calls build_system_prompt(turn_payload, registry=...)
   ├─ Renders the system-prompt template
   ├─ Injects step rules (may reference visible_fields)
   └─ Optionally appends fragment pointers (on-demand rules)
   → RETURNS full prompt (e.g., 6,000–13,000 chars)

3. SERVICE creates GeminiLiveSession with:
   ├─ system_instruction (from step 2)
   ├─ fragment_registry (optional; for lazy-load rules)
   ├─ form_state_repo (where to read/write state)
   └─ tool_dispatcher (how to handle tool calls)
   
4. GeminiLiveSession.run() — the event loop:
   ├─ await session.send_realtime_input(text=system_prompt)
   │
   ├─ LOOP: until form submitted or session ends
   │  ├─ Receive audio frame from WebSocket
   │  ├─ Send to Gemini Live (streaming)
   │  ├─ Receive tool_call from Gemini (e.g., update_field)
   │  │  ├─ Dispatch to handler (update form_state in Redis)
   │  │  ├─ Compute screen delta (what changed?)
   │  │  ├─ Inject on-demand fragments if trigger satisfied (e.g., injury field appeared)
   │  │  └─ Send tool result back to Gemini
   │  │
   │  ├─ Receive audio response from Gemini
   │  └─ Send audio back to client (WebSocket)
   │
   └─ Session ends (user said "submit" or timeout)
      → form_state is in Redis/repo; client reads it
```

### Key optimizations already built in

**Screen Delta Tracking** (`screen_delta.py`)
- Every turn, compare field state before/after
- Only mention ADDED fields to the agent (not all fields)
- Saves ~12x tokens (agent ignores unchanged fields; only new ones trigger re-processing)
- Example:
  ```
  Turn 1: visible_fields = [name, dob, address]
  agent fills: name="Jane"
  delta.added = {name: "Jane"}  ← agent only sees this
  
  Turn 2: user says nothing new
  delta.added = {}  ← NO delta mention; agent continues naturally
  
  Turn 3: user fills address
  delta.added = {address: "123 Main St"}  ← agent sees this
  ```

**Lazy Prompt Fragments** (`prompt_fragments.py` — NEW this session)
- Some rules are only relevant when a condition is met
- Example: "How to capture injury details" rule only needed if `anyInjuries` field exists on screen
- Instead of carrying rule in system prompt every turn (cost = 200 tokens × 50 turns = 10K tokens), we:
  1. Put a 1-line pointer in the prompt ("injuryDetails rule available")
  2. Wait for the field to appear on screen
  3. Inject the full rule just-in-time (only that turn, only when needed)
- Savings: avoid carrying the rule 49 out of 50 turns; pay only when the field appears
- Trade-off: only worth it if rule is BIG relative to pointer cost (case_review's injury rule is small, so savings are marginal)

---

## case_review Voice — Gemini Live WebSocket

### Session lifecycle

```
1. Flask/FastAPI backend calls: POST /v1/case-review/voice/session
   → Creates FormState in Redis with empty case-note form
   → Returns: session_id + ws_url (e.g., /ws/case-review/voice/abc123)

2. Flutter app opens: WSS /ws/case-review/voice/abc123
   ├─ Sends "hello" handshake
   ├─ voice_routes.py receives on @voice_router.websocket(...)
   ├─ Acquires WS lock (one session per session_id)
   ├─ Builds TurnPayload from Redis state
   ├─ Calls build_system_prompt(turn, registry=_VOICE_REGISTRY, fragment_registry=CASE_NOTE_FRAGMENTS)
   ├─ Creates GeminiLiveSession
   └─ Starts the event loop

3. Agent guides through fields:
   ├─ "Tell me about the shift summary"
   ├─ User: "Started well, became difficult"
   ├─ Agent calls: update_field(section="summary", field="summaryOfShift", value="...")
   ├─ voice_routes.py: save to Redis, compute delta
   ├─ Agent injects fragments if conditions met (e.g., if anyInjuries→true, inject injury rule)
   └─ Repeat until form complete

4. User or backend calls: POST /v1/case-review/incidents/analyze
   ├─ Reads finalized form from request body
   ├─ Runs triage → evaluator → incident draft (the full RP pipeline)
   └─ Returns structured verdict + risk analysis

### File breakdown

**`voice/prompts/registry.py`**
```python
STEPS = {
    "staff_case_note": text_from_steps.staff_case_note  # only one multi-field step
}
```

**`voice/prompts/steps/staff_case_note.py`**
- 17 field rules bundled into one `STAFF_CASE_NOTE_RULES` string
- Each rule is a 1–2 sentence instruction for that field
- Example: `summaryOfShift: "Recap the shift in 1–2 sentences..."`
- Previously baked into the system prompt every turn; now selected at prompt-build time

**`voice/prompts/fragments.py`** (NEW — added this session)
```python
_INJURY_DETAILS = PromptFragment(
    key="case_review.injuryDetails",
    pointer="injuryDetails: how to record injury specifics — loads if an injury is reported.",
    text="When the participant is injured...",
    triggers_on=field_present("safetyAndHealth.injuryDetails")
)
CASE_NOTE_FRAGMENTS = FragmentRegistry(fragments=[_INJURY_DETAILS, ...])
```
- The injury rule used to live in `staff_case_note.py`; now deferred
- Only injected on-demand when the `anyInjuries` toggle creates the `injuryDetails` field on screen
- Saves: keeping the rule out of the always-on prompt (though savings are small because the rule itself is small)

**`api/voice_routes.py`**
```python
@voice_router.websocket("/ws/case-review/voice/{session_id}")
async def case_review_voice_ws(websocket, session_id):
    # 1. Build initial turn from Redis state
    initial_turn = _build_initial_turn(state)
    
    # 2. Build system prompt WITHOUT fragment pointers
    #    (we skip fragment_registry here; the table row serves as pointer)
    system_instruction = build_system_prompt(
        initial_turn,
        registry=_VOICE_REGISTRY,
        voice_coverage=CASE_NOTE_SCHEMA.voice_coverage,
        # NOTE: fragment_registry NOT passed — see comment above
    )
    
    # 3. Create Gemini Live session WITH fragment registry
    #    (fragments are injected at runtime when fields appear)
    live = GeminiLiveSession(
        ...,
        fragment_registry=CASE_NOTE_FRAGMENTS,
    )
    await live.run()
```

---

## onboarding Voice — Gemini Live WebSocket

### Session lifecycle

```
1. Backend calls: POST /v1/onboarding/session { participant_id, step, schema, bootstrap }
   → Creates FormState in Redis with step schema + any bootstrap data
   → Returns: session_id + ws_url

2. Flutter app opens: WSS /ws/onboarding/{session_id}
   ├─ Sends "hello" handshake
   ├─ api/routes.py receives on @router.websocket(...)
   ├─ Acquires WS lock
   ├─ Builds TurnPayload from Redis state (NEW — includes compressed prior_steps)
   ├─ Calls build_system_prompt (onboarding's own, not shared)
   ├─ Creates GeminiLiveSession (onboarding's own fork)
   └─ Starts event loop

3. Agent asks questions field-by-field:
   ├─ "What's your full name?"
   ├─ User: "Jane Citizen"
   ├─ Agent calls: update_field(section="basics", field="full_name", value="Jane Citizen")
   ├─ Voice handler: save to Redis, compute delta
   ├─ Agent continues: "Date of birth?"
   └─ Repeat until all fields collected (or user submits early)

4. User or backend calls: POST /v1/onboarding/session/{id}/complete
   ├─ Reads form from Redis
   ├─ Fires webhook: `onboarding.session.completed` → app backend
   └─ Data persisted by backend

### File breakdown

**`api/routes.py`** (THE ONLY FILE WE EDITED FOR INPUT REDUCTION)
```python
_PRIOR_STEPS_RENDER_CAP = 5  # NEW — cap step count
_IDENTITY_KEYS = ("name", "dob", "gender")  # NEW — identity dedup keys

# In create_session():
# ...
# NEW: compress prior_steps before rendering in prompt
recent_summaries = sorted(bucket.summaries, key=lambda s: s.step_number)[-_PRIOR_STEPS_RENDER_CAP:]
hydrated_prior = {
    f"step:{s.step_number}": {
        **{k: v for k, v in s.verbatim.items()
           if k not in _IDENTITY_KEYS and v not in (None, "", [], {})},
        "_step_label": s.step_label,
    }
    for s in recent_summaries
}
# Dedup identity into one _participant block
_participant = {}
if current_name: _participant["name"] = current_name
# ... (fetch most-recent dob/gender from last few summaries)
if _participant:
    hydrated_prior["_participant"] = _participant
```
- **What changed**: `prior_steps` in the system prompt went from 879 → 333 chars (62% smaller)
- **Why**: identity fields (name/dob/gender) repeated in every step; now deduplicated once
- **Impact**: Every turn billed; 50-turn session saves ~6,850–13,700 tokens

**`prompts/onboarding_system.py`** (206-line base template)
- The "always-on" system prompt (3,673 tokens)
- Includes all the Aussie phrasing, error handling, field-walk logic
- Baked in every turn
- No changes this session; it's the bulk of the always-on cost

**`voice/prompt_builder.py`** (onboarding's own, NOT shared)
```python
def build_system_prompt(turn_payload, registry=None):
    # Builds the prompt by:
    # 1. Starting with TEMPLATE
    # 2. Injecting step rules
    # 3. Appending hydrated_prior (the compressed prior_steps)
    # DOES NOT use fragment_registry (onboarding has no lazy-load rules)
```

**`voice/gemini_live.py`** (onboarding's own fork, NOT shared)
- Separate implementation from case_review's shared one
- Handles WebSocket lifecycle, tool dispatch, delta tracking
- Does NOT include fragment injection (no lazy fragments in onboarding yet)

---

## Data Flow — A Complete Example

### Example: Case Review Voice Session

**User:** Support worker finishes a shift and opens the Flutter app.

```
1. FLUTTER: Opens /v1/case-review/voice/session
   REQUEST: { client_id: "c_123", shift_id: "s_456", initial_values: {} }
   RESPONSE: { session_id: "sess_abc", ws_url: "/ws/case-review/voice/sess_abc" }

2. FLASK: Saves FormState to Redis:
   ```
   key: sena:case_review:sess_abc
   {
     session_id: "sess_abc",
     participant_id: "c_123",
     step_id: "staff_case_note",
     values: {},  # empty; worker hasn't said anything yet
     schema: CASE_NOTE_SCHEMA
   }
   ```

3. FLUTTER: Opens WSS /ws/case-review/voice/sess_abc
   FLASK: voice_routes.py receives WebSocket.accept()
   
   a. Loads FormState from Redis
   b. Builds TurnPayload:
      ```python
      TurnPayload(
          participant=Participant(first_name="", display_name=""),
          step=StepInfo(id="staff_case_note", label="Case Note", number=1),
          visible_fields=[
              VisibleField(path="summary.summaryOfShift", label="Summary of Shift", ...),
              VisibleField(path="activitiesAndSkill.assisted", label="What did you assist with?", ...),
              # ... 17 total fields
          ],
          prior_steps={},  # no prior steps for new shift
          next_target=NextTarget(path="summary.summaryOfShift", reason="next_required"),
      )
      ```
   
   c. Calls build_system_prompt(turn_payload, registry=_VOICE_REGISTRY):
      ```
      Returns ~13,200-char system prompt:
      - Base template (greeting, tools, voice rules)
      - Step rules for staff_case_note (one 1–2-sentence rule per field)
      - [NO fragment pointers — table rows serve as implicit pointers]
      - TurnPayload injected as JSON (visible_fields, next_target, etc.)
      ```
   
   d. Creates GeminiLiveSession:
      ```python
      live = GeminiLiveSession(
          websocket=websocket,
          session_id="sess_abc",
          system_instruction=system_prompt,
          fragment_registry=CASE_NOTE_FRAGMENTS,  # ← on-demand rules
          ...
      )
      ```
   
   e. Sends system_instruction to Gemini Live:
      ```
      // To Gemini:
      {
          "type": "setup",
          "system_instruction": "[full prompt from step c]"
      }
      ```

4. GEMINI: Sets up the session and sends first response:
   ```
   // To Flutter (via WebSocket):
   {
       "type": "audio",
       "data": "PCM16 24kHz mono...",  // Agent says: "Hi, I'm Sena. Let's record your shift..."
   }
   ```

5. FLUTTER: User speaks into microphone:
   ```
   "The shift was good, no major issues. I helped with morning routine and lunch."
   ```
   Captures audio and sends to server:
   ```
   WEBSOCKET BINARY: PCM16 16kHz mono frames (streaming)
   ```

6. GEMINI LIVE: Receives audio, processes, returns tool call:
   ```
   // Gemini to voice_routes.py:
   {
       "type": "function_call",
       "function": "update_field",
       "id": "call_001",
       "arguments": {
           "section": "summary",
           "field": "summaryOfShift",
           "value": "Good shift; no major issues. Helped with morning routine and lunch."
       }
   }
   ```

7. VOICE_ROUTES: Handles the tool call:
   a. Updates Redis FormState:
      ```
      key: sena:case_review:sess_abc
      values.summary.summaryOfShift = "Good shift; no major issues..."
      ```
   
   b. Computes screen delta (ScreenDeltaTracker):
      ```
      delta.added = {
          "summary.summaryOfShift": "Good shift..."
      }
      // Other fields unchanged; not mentioned
      ```
   
   c. Checks: does any fragment trigger match?
      ```python
      for frag in fragment_tracker.fragments_to_inject({"added": delta.added}, state_dict):
          # Only triggers on conditions like: field_present("safetyAndHealth.injuryDetails")
          # Since no injury field appeared, no fragment fires here
          pass
      ```
   
   d. Sends tool response + delta back to Gemini:
      ```python
      // To Gemini:
      {
          "type": "function_response",
          "id": "call_001",
          "output": {
              "success": true,
              "state": {
                  "visible_fields": [...],
                  "delta": {"added": {"summary.summaryOfShift": "Good shift..."}},
              }
          }
      }
      ```

8. GEMINI: Continues with the conversation:
   ```
   "Great, I've noted that. Now, tell me about activities and skills — what did the participant do?"
   // Sends audio response back
   ```

9. FLUTTER: User speaks again:
   ```
   "She practiced personal care skills independently, made lunch choices..."
   ```

10. VOICE_ROUTES: Update another field; check fragments again...
    ```
    delta.added = {
        "activitiesAndSkill.practisedSkill": "She practiced personal care..."
    }
    // Still no injury field → no fragment triggers
    ```

11. (... loop continues, field by field ...)

12. Eventually, user says:
    ```
    "There was an incident. The client was injured when he fell."
    ```
    
    This causes `safetyAndHealth.anyInjuries` to be set to TRUE, which makes
    the `safetyAndHealth.injuryDetails` field appear on screen.

    Now:
    ```python
    delta.added = {"safetyAndHealth.injuryDetails": null}
    // Fragment trigger fires! field_present("safetyAndHealth.injuryDetails") = TRUE
    ```
    
    voice_routes.py:
    ```python
    for frag in fragment_tracker.fragments_to_inject({"added": {...}}, state):
        # _INJURY_DETAILS fragment matches!
        # Fire once (InjectedFragmentTracker prevents re-fire)
        // To Gemini:
        await session.send_realtime_input(text="""
        [RULE: case_review.injuryDetails]
        When the participant is injured, walk me through...
        """)
    ```

    This is the full "how to capture injury details" rule, injected
    just-in-time on the turn when the injury field appears.

13. (... more fields ...)

14. User completes form or says "submit":
    ```
    FLASK: all form fields filled
    FLUTTER: calls finalize_note() tool
    FLASK: form_state in Redis is complete
    ```

15. FLUTTER: Backend reads form from Redis and calls:
    ```
    POST /v1/case-review/incidents/analyze
    {
        "case_note_form": {
            "summary": {"summaryOfShift": "Good shift; no major issues..."},
            "activitiesAndSkill": {"practisedSkill": "..."},
            ...
            "safetyAndHealth": {"anyInjuries": true, "injuryDetails": "..."},
            ...
        }
    }
    ```

16. FLASK: Runs the full RP pipeline:
    - Triage (Haiku): is there a restrictive practice?
    - RAG: fetch NDIS policy
    - Evaluator (Sonnet): structured verdict
    - Incident Draft: generate report if needed
    
    Returns: verdict + risk analysis

---

## Recent Input-Reduction Work

### What changed (this session)

#### Part A — case_review fragment framework

**Problem**: The system prompt is billed every turn. Some rules are only relevant under a condition.

**Solution**: Lazy-load rules that don't apply until a field appears.

**Implementation**:
1. Created `shared/.../voice/prompt_fragments.py` — the framework
   - `PromptFragment`: key + text + pointer + trigger condition
   - `FragmentRegistry`: named set of fragments
   - `InjectedFragmentTracker`: fires each fragment once, resets on session resume

2. Extended `shared/.../voice/prompt_builder.py`
   - Added `fragment_registry` kwarg (keyword-only, default None)
   - Optionally appends fragment pointers to the prompt

3. Extended `shared/.../voice/gemini_live.py`
   - Added `fragment_registry` kwarg to constructor
   - In `_handle_screen_state()`, after delta computation, checks: does any fragment trigger match?
   - If yes, sends the fragment text to Gemini as a `[RULE: ...]` message

4. Created `case_review/voice/prompts/fragments.py`
   - One fragment: `_INJURY_DETAILS` (how to capture injury details)
   - Triggers on: `field_present("safetyAndHealth.injuryDetails")`
   - Exported as `CASE_NOTE_FRAGMENTS`

5. Modified `case_review/api/voice_routes.py`
   - Pass `fragment_registry=CASE_NOTE_FRAGMENTS` to `GeminiLiveSession` constructor
   - Do NOT pass it to `build_system_prompt()` (the table row in staff_case_note.py serves as the pointer)

**Token math**:
- Original: injury rule in system prompt every turn (always-on cost)
- New: rule only sent when injury field appears (conditional cost)
- Savings per session: small (the rule is only ~120 chars; savings are ~67 chars/turn)
- Per-session (50 turns): ~3,350 tokens saved (modest)

#### Part C — onboarding prior_pages compression

**Problem**: When collecting onboarding data across 7 steps, earlier steps' context is carried forward. But identity fields (name/dob/gender) are repeated in every step's summary — that's dead weight the prompt mentions even though the mode rules say "always use visible_fields for identity".

**Solution**: Dedup identity into one block; drop empty/null values; cap to 5 most-recent steps.

**Implementation** (`onboarding/api/routes.py`):
```python
_PRIOR_STEPS_RENDER_CAP = 5
_IDENTITY_KEYS = ("name", "dob", "gender")

# In create_session():
recent_summaries = sorted(bucket.summaries, key=...)[-_PRIOR_STEPS_RENDER_CAP:]
hydrated_prior = {
    f"step:{s.step_number}": {
        **{k: v for k, v in s.verbatim.items()
           if k not in _IDENTITY_KEYS and v not in (None, "", [], {})},
        "_step_label": s.step_label,
    }
    for s in recent_summaries
}
# Extract identity once, at the top
_participant = {...}
if _participant:
    hydrated_prior["_participant"] = _participant
```

**Token math**:
- Original: 879 chars for prior_steps (identity repeated 7 times)
- New: 333 chars (identity once + nulls dropped + capped to 5 steps)
- Savings: 546 chars ≈ **137 tokens per turn**
- Per-session (50 turns): **~6,850 tokens saved**
- Per-session (100 turns): **~13,700 tokens saved**

**Why this matters**: `prior_pages` is billed every turn. When a session spans 5–7 steps, deduping the identity fields is the biggest single-target optimisation available without touching the hardened anti-hallucination base template.

---

## File-by-File Reference

### Shared Voice Engine (`services/shared/src/sena_common/voice/`)

| File | Purpose | Key Classes/Functions |
|------|---------|----------------------|
| `__init__.py` | Public exports | `GeminiLiveSession`, `FormStateRepo`, `build_system_prompt` |
| `gemini_live.py` | Main WebSocket session handler | `GeminiLiveSession` (lifecycle, audio, tool dispatch, delta tracking, fragment injection) |
| `prompt_builder.py` | System prompt assembly | `build_system_prompt()` — injects step rules + fragments |
| `prompt_fragments.py` | On-demand rule framework | `PromptFragment`, `FragmentRegistry`, `InjectedFragmentTracker` |
| `screen_delta.py` | Delta computation | `ScreenDeltaTracker`, `ScreenStateDelta` — 12x token saving |
| `turn_payload.py` | State model | `TurnPayload`, `Participant`, `StepInfo`, `VisibleField` |
| `form_state.py` | Form state model | `FormState` (field values, validation errors) |
| `state_repo.py` | Form storage (Redis-backed) | `FormStateRepo` — Redis persistence, tenant-scoped keys |
| `mobile_bridge.py` | Tool call routing | `MobileBridge` — proxies tool calls to the mobile client, waits for responses |

### case_review Voice (`services/case_review/voice/`)

| File | Purpose |
|------|---------|
| `prompts/registry.py` | Entry point: `STEPS` dict (only one: `staff_case_note`) |
| `prompts/steps/staff_case_note.py` | The 17-field rules (previously always-on; now selectable) |
| `prompts/fragments.py` | On-demand fragments (`_INJURY_DETAILS` + registry) |
| `casenote_schema.py` | Schema definition (17 fields across 5 sections) |
| `tool_decls.py` | The 7 tools the agent can call |
| `drafter.py` | Standalone: transcript → form fields (Sonnet) |

### case_review API (`services/case_review/api/`)

| File | Purpose |
|------|---------|
| `voice_routes.py` | Voice endpoints: create session, WebSocket handler |
| `unified_incident_routes.py` | POST /incidents/analyze (runs the full RP pipeline) |

### onboarding Voice (`services/onboarding/voice/`)

| File | Purpose |
|------|---------|
| `prompt_builder.py` | Onboarding's own (not shared) — builds system prompt |
| `gemini_live.py` | Onboarding's own (not shared) — WebSocket session handler |
| `prompts/onboarding_system.py` | Base template (206 lines, 3,673 tokens) |
| `prompts/steps/` | Step-specific rules (one per onboarding page) |

### onboarding API (`services/onboarding/api/`)

| File | Purpose |
|------|---------|
| `routes.py` | Session CRUD, state get/put, complete, WebSocket handler |
| `deps.py` | Auth + dependency injection |

---

## API Matrix

### case_review Voice APIs

| Method | Endpoint | What it does | Returns |
|--------|----------|-------------|---------|
| POST | `/v1/case-review/voice/session` | Create voice session, get ws_url | `{session_id, ws_url}` |
| POST | `/v1/case-review/voice/draft` | Raw transcript → form fields | `{initial_values, gaps_note, token_usage}` |
| WS | `/ws/case-review/voice/{session_id}` | Gemini Live dictation | Audio + tool calls + responses |

### case_review Analysis APIs

| Method | Endpoint | What it does | Returns |
|--------|----------|-------------|---------|
| POST | `/v1/case-review/incidents/analyze` | Full RP pipeline | `{verdict, detected_practice, incident_draft, token_usage}` |
| POST | `/v1/case-review/context` | Rolling case-note summary | `{summary, prior_notes}` |
| POST | `/v1/case-review/classify` | Classify paragraph into fields | `{classified_fields, token_usage}` |

### onboarding Voice APIs

| Method | Endpoint | What it does | Returns |
|--------|----------|-------------|---------|
| POST | `/v1/onboarding/session` | Create session, get ws_url | `{session_id, ws_url, expires_at}` |
| GET | `/v1/onboarding/session/{id}/state` | Read current form state | `{FormState}` |
| PUT | `/v1/onboarding/session/{id}/state` | Update state (non-voice) | `{FormState}` |
| POST | `/v1/onboarding/session/{id}/complete` | Mark complete, fire webhook | `{completed, webhook_delivered}` |
| WS | `/ws/onboarding/{session_id}` | Gemini Live form collection | Audio + tool calls + responses |

---

## Key Takeaways

### Why the architecture is structured this way

1. **Shared engine** — Both services (case_review + onboarding) need Gemini Live WebSocket handling, form state management, tool dispatch, and delta tracking. Rather than duplicate, they share `sena_common.voice`.

2. **Independent prompt/fragment registries** — Each service has different rules. case_review has staff_case_note rules + injury fragments. onboarding has step-specific rules + no fragments (yet).

3. **case_review uses shared, onboarding forks** — case_review fully integrates the shared engine. onboarding has its own `prompt_builder.py` and `gemini_live.py` forks (legacy; not migrated to shared). This isolation is intentional: onboarding's fork uses different Redis, different state shape, different tool set.

4. **Recent optimisations target the two highest-cost always-on components**:
   - **onboarding** → `prior_steps` dedup (Part C): -62%, every turn, every session
   - **case_review** → lazy fragments (Part A/B): -67 chars/turn, only on conditionals

### What NOT to change without careful testing

1. **Base system prompts** (case_review `staff_case_note.py` + onboarding `onboarding_system.py`) — These are hardened to prevent hallucinations. Trimming them requires behavior A/B testing on real voice sessions.

2. **Tool dispatch logic** — Both services depend on tool calls to update form state. Changing tool names, arguments, or response handling will break the agent.

3. **Field walk order** — The agent relies on `visible_fields` being in schema order + `next_target` guidance to avoid skipping fields. Reordering breaks the UX.

### What's safe to change

1. **Adding fragments** — New on-demand rules can be added to `case_review/voice/prompts/fragments.py` without affecting existing behavior (optional; fragment_registry=None reproduces old behavior).

2. **Compressing prior_steps further** — If more `_IDENTITY_KEYS` are identified, they can be deduped the same way. If more null keys can safely be dropped, update `_PRIOR_STEPS_RENDER_CAP`.

3. **Adjusting fragment triggers** — If you want a fragment to fire on a different condition, change the `triggers_on` predicate. Verify the new condition with a test session.

---

## Integration checklist

Before deploying changes to either service:

- [ ] All imports resolve (shared + service-specific)
- [ ] Fragment triggers tested in isolation (unit tests)
- [ ] WebSocket lifecycle tested on real voice (manual)
- [ ] Token usage logged and compared (before/after)
- [ ] No hallucination regressions (sample 5+ real sessions)
- [ ] Webhook delivery confirmed (onboarding)
- [ ] Incident pipeline still works (case_review)
