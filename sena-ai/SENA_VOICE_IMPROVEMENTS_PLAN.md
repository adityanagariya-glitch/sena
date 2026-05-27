# SENA Voice — Pattern Adoption Plan v2 (stay on Gemini Live)

**Audience:** SENA backend dev
**Tech-stack constraint:** keep `gemini-3.1-flash-live-preview` as the voice engine. No migration to Pipecat, Vertex, Twilio, or any other stack. We're learning the **approach**, not the transport.
**Source material:** healthcare-receptionist call bot at `sena-mobile/sena-mobile/{AGENTS.md,PIPELINE.md,prompt.py}`. Same problem space (multi-turn voice agent with tool calls into a domain backend), different architectural primitives.
**Status:** proposed — supersedes v1 after a second-pass read of `prompt.py` (1452 lines) surfaced ~15 patterns the first read missed.

---

## What this revision changes from v1

1. **Per-screen prompt swap is the foundation, not a workaround.** Every onboarding step = a fresh WS session = a fresh `LiveConnectConfig`. The system instruction and `function_declarations` can be different per screen at zero implementation cost. That collapses v1's "text injection at every turn" Pattern 2 into a session-create-time config change.
2. **VERIFICATION PROTOCOL is a template, not a single anti-pattern.** Their code uses the same structure in 3+ terminal-action prompts (BOOK, CANCEL, RESCHEDULE) with only the forbidden-verb list swapped. We should productize ours the same way.
3. **Rigid sectional template across all per-state prompts.** Every state prompt has the SAME sections in the same order: Task / Objective / Instructions / Communication Guidelines / Transfer Protocol / Current Context. Predictable structure = predictable model behaviour.
4. **Math expressions in prompts.** Their OVERLAP CHECK gives the model a literal Boolean expression to evaluate. We can do the same for our validators.
5. **Closed-set decision shortcuts.** Enumerate trigger phrases (transfer words, default-to-X intents) so the model isn't reasoning open-ended.
6. **Multi-attempt hard limits.** "After 2 failed confirmations, transfer." Counters, not principles.

The patterns below absorb every learning from a complete re-read.

---

## Context

The healthcare receptionist is a Pipecat + Bedrock Haiku 4.5 voice bot taking inbound clinic calls over Twilio. It manages 6 standard states + 3 doctor-away states + an emergency reflex, ~10 tools, multi-tenant clinic config, and zero recorded production hallucinations on the verbs we care about. Reading its prompts is the equivalent of reading a senior team's post-mortem-driven runbook for voice agent design.

Everything below assumes you've read the source files at least once.

---

## Gemini Live constraints (and how each constraint maps to a pattern)

| Constraint | Workaround we use |
|---|---|
| System instruction fixed per session | **Use the session boundary** — we open a fresh WS per onboarding step, so swap the prompt at `LiveConnectConfig` time. No mid-session swap needed. |
| `function_declarations` fixed per session | Same as above — different tool subset per step at connect time. |
| Mid-session sub-state changes (within a screen) | Inject text turns via `send_realtime_input(text=...)` (same channel as `[SILENCE TIMEOUT]`). |
| Response modality TEXT or AUDIO, not both | Router/classifier/safety calls happen via SEPARATE Gemini Flash REST calls, not on the Live session. |
| Connection lifetime ~10 min | Already handled by resumption. |
| No proactive audio | Pre-rendered greeting WAV streamed before bridge accepts user input. |
| Async function calling not supported | No change — keep synchronous tool dispatch. |

---

## Pattern catalogue (15 adopted, each mapped to file-level work)

### Pattern 1 — Per-step focused prompts (rigid sectional template)

**What they do:** every per-state prompt follows the exact same skeleton:

```
{base_prompt}                              ← shared 20-line core (role, tone, output rules)

## Task                                    ← one-paragraph scope statement
## OBJECTIVE                               ← optional, used by procedural prompts
### INSTRUCTIONS                           ← numbered procedural steps
## Communication Guidelines                ← formatting rules (dates in words, no number speech)
## Transfer Protocol                       ← when + how to escalate
## Current Context                         ← interpolated runtime values
   Call From: {call_from}
   Current Date: {current_time}
   Current Day: {current_day}
## Patient Details / Appointment Type Instructions / Doctor List / etc.
```

Adding a new state = filling in the template. The model has been pre-shaped by the predictable structure of every prior prompt — it knows where to look for which kind of guidance.

**Our adaptation:** split the current `onboarding_system.md` (663 lines, all-steps-in-one) into:

- `prompts/_base.md` — the shared ~80-line core (greeting cadence, JSON-as-Truth, tool-honesty, Tool-BEFORE-talk, screen-is-source-of-truth, Aussie tone) — included verbatim at the top of every step prompt
- `prompts/personal_information.md` — Steps 1 (~150 lines)
- `prompts/lifestyle_requirements.md` — Step 2 (~150 lines)
- `prompts/ndis_plan.md` — Step 3 (~200 lines — repeatable-heavy)
- `prompts/documents.md` — Step 4 (~120 lines)
- `prompts/medical.md` — Step 5 (~180 lines)
- `prompts/consent.md` — Step 6 (~100 lines)

Each step prompt follows the rigid sectional template:
- `## Task` — one-paragraph scope for THIS step
- `## STEP CONTEXT` — bootstrap mode, prior_pages summary, screen state
- `### INSTRUCTIONS` — numbered procedure for this step
- `## Communication Guidelines` — only the bits that vary (medical step has different date-spelling needs than consent step)
- `## Anti-patterns specific to this step`
- `## Tools available this turn` — explicit list (also enforced via `function_declarations`)
- `## Current Context` — interpolated values

**Result:** the model loads ~230 lines per session (base + step) instead of 663. Attention is narrower, drift is lower, ad-hoc rule conflicts disappear.

**Affected files:**
- `services/onboarding/src/onboarding/prompts/` — split into 7 files
- `services/onboarding/src/onboarding/services/prompt_builder.py` — replace `_TEMPLATE_PATH` constant with `_resolve_template_for_step(step_id)` lookup
- `services/onboarding/src/onboarding/services/tool_registry.py` — NEW; returns the `FUNCTION_DECLS` subset for a given step

---

### Pattern 2 — Per-step tool subset

**What they do:** even though `agent.llm` has many tools attached, `PromptBuilder.push_context` only surfaces the tools relevant to the current state. They append `end_conversation` + `transfer_to_frontdesk` to every state.

**Our adaptation:** at session create, build `FUNCTION_DECLS` from the union of:
- **Always-on (5):** `update_field`, `clear_field`, `get_session_context`, `advance_step`, `escalate_incident`
- **Only when step has repeatable sections (4):** `add_repeatable_row`, `delete_repeatable_row`, `enter_repeatable_section`, `exit_repeatable_section`
- **Always-on edge case (1):** `request_unknown_section`

Check `schema.has_repeatable_sections()` (new property) — if `False`, drop the 4 repeatable tools entirely from the `LiveConnectConfig.tools` list. The model literally cannot call them.

**Affected files:**
- `services/onboarding/src/onboarding/models/schema_spec.py` — add `StepSchema.has_repeatable_sections` property
- `services/onboarding/src/onboarding/services/tool_registry.py` — `function_decls_for(schema)`
- `services/onboarding/src/onboarding/services/gemini_live.py` — replace `FUNCTION_DECLS` reference with `tool_registry.function_decls_for(self._schema)`

---

### Pattern 3 — Mechanical VERIFICATION PROTOCOL template

**What they do:** every terminal-action prompt (BOOK_APPOINTMENT, CANCEL_APPOINTMENT, RESCHEDULE_APPOINTMENT) has the SAME structure at the top:

```
## CRITICAL — TERMINAL ACTION RULE (read this FIRST every turn)

You are FORBIDDEN from saying any of these words/phrases to the user
unless the corresponding tool has already returned a successful result
in the conversation history above:

- "<forbidden verb 1>", "<forbidden verb 2>"  → requires successful `<tool_name>` result
- ...                                          → out of scope here

VERIFICATION PROTOCOL (do this silently before every reply):
1. Scan the conversation history for the most recent toolResult.
2. If the user has just confirmed (e.g. "<confirmation phrase 1>", "<confirmation phrase 2>"),
   and `<tool_name>` has NOT yet returned successfully,
   your NEXT output MUST be the `<tool_name>` tool call — NOT a sentence to the user.
3. Only after the tool returns success may you tell the user the action is done.
4. `<read-only tool 1>` and `<read-only tool 2>` are NOT terminal actions.
   Lookups never satisfy this rule.

If you are about to type "<forbidden verb>" and you cannot point to a successful
`<tool_name>` result above, STOP and emit the tool call instead.
```

It's a **template**. Each prompt fills in (forbidden verbs, tool name, read-only-tools-to-exclude). The structural sameness means the model encounters the same verification mindset across every state.

**Our adaptation:** define ONE template in `prompts/_partials/verification_protocol.md` and include it in:
- Step 3 (ndis_plan), Step 5 (medical) — `advance_step` is the terminal tool, forbidden verbs: "submitted", "saved", "done"
- ANY step with a repeatable section — for `add_repeatable_row` (forbidden: "added", "new row"), for `delete_repeatable_row` (forbidden: "removed", "deleted", "scratched"), for `clear_field` (forbidden: "cleared", "blanked")

**Implementation:** template file with `{forbidden_verbs}`, `{tool_name}`, `{readonly_tools}` slots. `prompt_builder._render_verification_protocol(spec)` renders it. Inline into each step prompt at build time.

**Affected files:**
- `services/onboarding/src/onboarding/prompts/_partials/verification_protocol.md` — NEW template
- `services/onboarding/src/onboarding/services/prompt_builder.py` — `_render_verification_protocol`

---

### Pattern 4 — "The tool call IS your reply" — zero-text-before-terminal-action rule

**What they say** (BOOK_APPOINTMENT_PROMPT line 1008-1011):

> After the caller confirms (yes / okay / book it / proceed / sure / go ahead), your IMMEDIATE next output is a `book_appointment` tool call. Do NOT speak first. Do NOT say "booking now". Do NOT acknowledge. Just call the tool. Speak only after the tool result returns.

**Our adaptation:** add a verbatim version of this rule to our advance_step section + every repeatable-row terminal action. Phrase exactly: "After the participant confirms, your IMMEDIATE next output is the `advance_step` tool call. The tool call IS your reply to the confirmation."

This is stronger than today's "Tool-BEFORE-talk" mandate because it's mechanical — there's no thinking step in the middle.

**Affected files:**
- `services/onboarding/src/onboarding/prompts/_partials/tool_is_the_reply.md` — NEW
- Inline into ndis_plan, medical, advance_step sections of each step prompt

---

### Pattern 5 — Disambiguation NOTE callouts

**What they do** (CANCEL_APPOINTMENT line 1218-1222):

> NOTE: A patient selecting WHICH appointment to cancel (e.g., "the one on Friday", "the second one") is NOT a cancellation confirmation — it is a selection. After they select, you MUST still present the selected appointment's details (date, time, doctor) and ask explicitly: "Shall I go ahead and cancel that?" Only call `cancel_appointment` after that explicit confirmation.

This is a NOTE callout disambiguating two user moves that LOOK like confirmation but aren't. They've collected ambiguities from production transcripts and baked the rules into the prompt.

**Our adaptation:** add NOTE callouts for our top 3 disambiguation traps:
- **"Continue" mid-row vs add new row** (already Rule 22 — make it a NOTE callout in the repeatable-section step prompts).
- **"Yes" to a low-confidence captured value vs "yes" to a new value** — pending_confirmation lock should phrase the "yes" handling as a NOTE callout.
- **"Skip" on optional vs "skip" on the whole section** — Rule 5/14 territory.

**Affected files:**
- `services/onboarding/src/onboarding/prompts/_partials/note_callouts.md` — collected
- Inlined where relevant per step

---

### Pattern 6 — MULTI-BOOKING VERIFICATION recipe (count + match + list separately + honesty)

**What they do** (BOOK_APPOINTMENT line 1013-1028):

> **BOOKING COUNT INVARIANT** (read this before EVERY confirmation sentence):
> Before you emit ANY text containing "booked", "confirmed", "done", or any equivalent, COUNT:
>   (a) How many booking tool calls have you made in this turn?
>       Booking tools are: `book_appointment`, `book_appointment_with_nurse`. Nothing else counts.
>   (b) How many does the appointment type require?
> If (a) < (b), you are NOT done. Your VERY NEXT output is the missing booking tool call — NOT a confirmation sentence.
>
> **MULTI-BOOKING VERIFICATION** (when two booking tool calls are required):
> 1. After EVERY booking tool call, check whether ALL required bookings have a successful tool result in this turn.
> 2. Read back the `date_time` argument you passed to each booking tool. Verify each time matches what you offered AND matches the other booking's time.
> 3. If only ONE booking succeeded, do NOT say "both are booked".
> 4. The final confirmation must list each appointment SEPARATELY with its own time and provider (so any mismatch is visible to the caller).
>
> **HONESTY ON UNCERTAINTY**: If a tool result is missing, errored, or you are not certain a booking succeeded, SAY SO plainly. Never state something is booked when you only intended to book it.

This is a complete recipe: COUNT → MATCH → LIST SEPARATELY → BE HONEST.

**Our adaptation:** apply to:
- **`advance_step` invariant** — "Before saying 'submitted', verify a successful `advance_step` result exists. If not, your next output IS `advance_step(...)`."
- **Compound `update_field` invariant** (our Rule 15) — "Count update_field calls in this turn. If the user named N field values and N > calls made, your next output is the missing `update_field`."
- **Honesty on uncertainty** — new top-level rule paired with Tool-BEFORE-talk: "If you don't see a successful tool result for an action you intended, SAY SO. Do not claim the action succeeded."

**Affected files:**
- `services/onboarding/src/onboarding/prompts/_partials/count_invariant.md` — NEW template (with `{action}`, `{tool_name}`, `{verbs}` slots)
- Inlined into step prompts where applicable

---

### Pattern 7 — Math expressions in prompts (closed-form rules)

**What they do** (BOOK_APPOINTMENT line 1029):

> **OVERLAP CHECK**: Before booking, verify that no two same-day appointments overlap. Two slots overlap if: slot_A_start < (slot_B_start + slot_B_duration_minutes) AND slot_B_start < (slot_A_start + slot_A_duration_minutes). This check applies regardless of which slot was found first.

The model is given a literal Boolean expression and told to evaluate it. No vague "make sure they don't overlap".

**Our adaptation:** identify our cross-field invariants that benefit from explicit math:
- **Plan dates:** "Plan_end is after plan_start if plan_end > plan_start (ISO date comparison)."
- **Support schedule time order:** "end_time > start_time. Two slots on the same day overlap if A.start < B.end AND B.start < A.end."
- **NDIS number length:** "ndis_number is valid only if `len(digits_only) == 9` AND every character is a digit."
- **Funding amount cap:** "funding fields accept positive integers with `len(integer_part) ≤ 9` digits."

These already live in our Python validators. Add the math expressions to the prompt too, so the model can pre-validate before tool calls and avoid unnecessary `validation_rejection` round trips.

**Affected files:**
- New section in each step prompt: `## Inline validation rules` with the closed-form expressions
- Reuses existing validator code paths server-side (no logic change there)

---

### Pattern 8 — Closed-set decision shortcuts

**What they do:**

- **TRANSFER WORD LIST** (CALL_PURPOSE_PROMPT line 760): enumerate exact trigger phrases for immediate transfer ("receptionist", "operator", "person", "human", "staff member", "front desk", "doc", "doctor", "someone"). Closed enum.
- **DEFAULT TO X AND DO NOT ASK** (CALL_PURPOSE_PROMPT line 778): enumerate phrases that trigger a default ("see a doctor", "want to see doctor", "talk to the doctor", "general checkup", "follow-up", "not feeling well", "I have issues") → default `reason="general consultation"`, do NOT ask follow-up. Closed enum.
- **EMERGENCY symptom list** (EMERGENCY_PROMPT line 329-336): only 6 symptoms count as emergencies — chest pain, difficulty breathing, altered consciousness, fitting, uncontrollable bleeding, spinal injury. Closed enum.

The model isn't reasoning open-ended for these decisions. It's matching against a closed set.

**Our adaptation:** identify our open-ended decisions and close them.
- **"Start from scratch" triggers** (our Rule 16): close the enum — "start over", "start from scratch", "redo this", "redo from the beginning", "start again", "let's restart". List them.
- **"Continue" mid-row triggers** (our Rule 22): "continue", "yes", "go on", "next", "keep going", "carry on", "next field".
- **"Remove the X" triggers for clear_field vs delete_repeatable_row** (Rule 18b): already has this table — make it more exhaustive by mining production transcripts for variants.
- **"Skip" intent** for optional fields: "skip", "no thanks", "I'd rather not", "leave it blank", "next", "move on".

**Affected files:**
- `services/onboarding/src/onboarding/prompts/_partials/closed_set_triggers.md` — NEW
- Reference into Rules 5, 14, 16, 18b, 22

---

### Pattern 9 — Procedural STEP-BY-STEP runbooks

**What they do:** PATIENT_IDENTIFICATION_PROMPT (line 851-927) and BOOK_APPOINTMENT_PROMPT (line 974-1033) are linear scripts: `### STEP 1`, `### STEP 2`, `### STEP 3`. Each step has sub-conditions ("IF no record found", "IF multiple records"). The model walks the script top-to-bottom like a runbook.

Inside PATIENT_IDENTIFICATION's STEP 1 there's even a nested mini state machine ("count linked records → if >1 ask which → if 1 confirm → if 0 proceed to STEP 2 → if previously-asked-no, check other records").

**Our adaptation:** rewrite the per-step prompts as procedural runbooks where natural. Today our prompt is rule-based with cross-references. Procedural is more reliable for the model.

For Step 1 (personal_information), the runbook would look like:

```
### STEP 1: ACKNOWLEDGE PRE-FILLED DATA
IF current_page_values contains name AND phone:
   → Verify both in one sentence. Ask "Are these correct?". Wait for yes.
   → If user corrects, update_field with corrected value, re-confirm.
IF current_page_values contains email AND email is in readonly_paths:
   → State once: "Your email {email} is locked from your account."
   → Move immediately to next field. Do NOT ask user about email.

### STEP 2: COLLECT MISSING REQUIRED FIELDS (basics section)
Walk basics fields in schema order. Use Rule 10 readback pattern after each.

### STEP 3: COLLECT HOME ADDRESS
Walk home_address fields. ...

### STEP 4: SERVICE ADDRESS DECISION
Ask "Is your service address the same as home?"
IF yes → set service_same_as_home=true; service_address auto-copies.
IF no → walk service_address fields.

### STEP 5: EMERGENCY CONTACTS (repeatable, min=1)
Pin focus with enter_repeatable_section(intent="first").
Walk item_fields. After row complete: ask "Add another?".
IF yes → add_repeatable_row + enter_repeatable_section(intent="next").
IF no → exit_repeatable_section.

### STEP 6: CONFIRMATION + ADVANCE
After all required filled: read back summary. Ask "Submit?".
On explicit "yes" → advance_step. The tool call IS your reply.
```

The model has clear next-action semantics at every point.

**Affected files:** every step prompt gets a procedural runbook section after the rules.

---

### Pattern 10 — Sub-state machine inside one step

**What they do** (PATIENT_IDENTIFICATION_PROMPT STEP 1, line 853-878): inside ONE script step, a mini decision tree:

```
Count Patient ID entries in "Linked Patient Record" section.
IF >1 entries:
  → ask which one (mention every name + dob in words)
  → on selection, IMMEDIATELY confirm_details
  → on "none of them", proceed to STEP 2
IF =1 entry:
  → ask "Is this booking for {name} with dob {dob}?"
  → on YES, confirm_details
  → on NO, proceed to STEP 2
IF =0 entries:
  → skip to STEP 2 directly
IF history shows "asked about one, said no":
  → check other linked records → ask about them
  → only proceed to STEP 2 once all are exhausted
```

This is a state machine inside a step. We have similar branching (e.g. "have we already asked about this section before this resumption?") that's currently scattered across our prompt.

**Our adaptation:** for STEP 5 (emergency contacts repeatable) in Step 1, add explicit mini-state-machine:

```
LET row_count = state.repeatable_rows["emergency_contacts"]
IF row_count == 0:
  → "Now let's add your first emergency contact. What's their name?"
IF row_count >= 1 AND last_row_is_incomplete:
  → "We've got the name {name} for that contact — what's their phone?"
IF row_count >= 1 AND last_row_is_complete AND row_count < max:
  → "Would you like to add another emergency contact?"
IF row_count == max:
  → exit_repeatable_section; move on
```

The model walks the tree instead of inferring from `[LIVE_STATE_JSON]`.

**Affected files:** each step prompt with repeatables (personal_information, ndis_plan, medical) gets a sub-state-machine block.

---

### Pattern 11 — Date formatting split: speak vs tool param

**What they do** (PATIENT_IDENTIFICATION_PROMPT line 837-846):

> ### For Conversational Responses (Speaking to Users)
> - ALWAYS mention dates in words: date month year (e.g., "first January nineteen ninety")
> - NEVER use numbers for dates (e.g., say "third October" NOT "third ten")
>
> ### For Tool Calls and Structured Data
> - ALWAYS use standard date format: YYYY-MM-DD (e.g., "1990-01-01")
> - ISO 8601 for all date parameters in function calls
> - Only apply word-based formatting in your conversational responses, NOT in tool parameters

Explicit two-format rule. The model knows when to use which.

**Our adaptation:** add this same split to our communication-guidelines block in step prompts that have date fields (Step 1 birthdate, Step 3 plan_start/plan_end, Step 5 medication start_date). Today our prompt says "read dates in plain words" but doesn't explicitly contrast with tool format.

**Affected files:** `prompts/_base.md` or per-step prompts.

---

### Pattern 12 — Multi-attempt hard limits

**What they do** (PATIENT_IDENTIFICATION_PROMPT line 898-902, 916-917):

> **If no record found**:
>   - Allow only 1 additional attempt
>   - **If still not found**: "I'm having trouble locating the record. Let me transfer you to our front desk who can assist you better." Transfer to human.
>
> ...
>
> - After 2 failed confirmations, say: "I want to make sure I get this right. Let me transfer you to our front desk who can help verify your information."

Hard counters. Not "if user struggles, escalate" (vague) but "after 2 failed, transfer" (mechanical).

**Our adaptation:** add hard counters to our retry-prone flows:
- **CONFIRM_REQUIRED retries:** after 2 failed confirmations of the same field, fall back to letting the user spell it OR escalate.
- **Enum option re-asks (Rule 13):** after 2 failed enum selections on the same field, read the FULL list instead of 2-3 examples.
- **Field validator rejections:** after 3 rejections on the same field, ask the user to type it via Flutter instead of speaking.

**Affected files:**
- `services/onboarding/src/onboarding/models/form_state.py` — track `field_attempt_count` per (section, field)
- `services/onboarding/src/onboarding/services/tools.py` — increment on reject
- Step prompts — surface the counter as a hard limit

---

### Pattern 13 — Sentinel data for missing context

**What they do** (prompt.py line 75-84):

```python
if patient_data:
    patient_refurnished_appointment = f"""
        PATIENT_ID: {patient_data.patient_id}
        FIRST_NAME: {patient_data.firstname}
        ...
    """
else:
    patient_refurnished_appointment = "NO PATIENT DATA AVAILABLE, END THE CALL."
    logger.error("DOCTOR AWAY CALL: Patient Data not found.")
```

When required data is missing, they inject a SENTINEL STRING into the prompt that tells the model exactly what to do ("END THE CALL"). The model can't accidentally proceed with empty data.

**Our adaptation:** when our bootstrap is corrupted or critical fields are missing, inject sentinels:
- `participant_display_name` missing AND step ≠ 1 → inject `"NO PARTICIPANT NAME AVAILABLE — open with generic greeting, do NOT invent a name"` directly into the prompt (instead of relying on the empty token).
- `schema.step_id` unknown → inject `"UNKNOWN STEP — call advance_step(error=\"schema_drift\") and end the session"`.

**Affected files:** `services/onboarding/src/onboarding/services/prompt_builder.py` — explicit sentinel for missing-state cases.

---

### Pattern 14 — DECISION FLOWCHART ASCII art + EDGE CASES + CRITICAL REMINDERS

**What they do** (ROUTER_PROMPT line 538-630):

- **DECISION FLOWCHART** — ASCII tree showing the routing tree. The router LLM walks the tree.
- **EDGE CASES** — explicit recipes for ambiguous user inputs ("user asks about hours mid-booking → GENERAL_INQUIRY", "user provides reason upfront → still IDENTIFY_CALL_PURPOSE first", "tool call in progress → wait").
- **CRITICAL REMINDERS** — 6 numbered anti-shortcut reminders at the end of the prompt, contradicting the model's default reasoning ("NEVER skip IDENTIFY_CALL_PURPOSE", "NEVER route without call_purpose").

This is the format of a hard-earned production prompt. Each rule corresponds to a real production bug.

**Our adaptation:** add these three sections to each per-step prompt:
- **DECISION FLOWCHART** — ASCII tree for the step's branching (when to enter a repeatable, when to advance_step).
- **EDGE CASES** — collected ambiguities per step (e.g. for Step 3 NDIS Plan: "user picks Self Managed but later mentions plan manager → re-confirm plan_management, don't write plan_manager fields").
- **CRITICAL REMINDERS** — anti-shortcut rules at the end. Our equivalent today is the anti-pattern citations.

**Affected files:** each per-step prompt.

---

### Pattern 15 — Letter-spelling in confirmation

**What they do** (PATIENT_IDENTIFICATION_PROMPT line 914):

> "Let me confirm the details: First name [spell like J-O-H-N] <break time="0.5s" /> Last name [spell like D-O-E], date of birth [repeat DOB in full words], and contact number [read number]. Is that correct?"

Spell names back letter-by-letter on confirmation. Catches ASR errors that flow through verbal readback (e.g. "Aditya" heard back as "Aditya" sounds fine but the spelling is what's stored).

**Our adaptation:** add letter-spelling to our Rule 10 readback pattern when the field is `basics.full_name`, `emergency_contacts[].name`, or any text field that the participant might want spelt correctly:

> Turn 1 (you, after update_field succeeds):
> "I've got first name {spell-out value}, is that right?"

We use SSML markers like `<break time="0.3s"/>` between letters. Gemini Live supports SSML in TTS output for `audio_transcription` configs.

**Affected files:**
- `prompts/_base.md` Rule 10 — add letter-spelling section
- `services/onboarding/src/onboarding/services/tools.py` `_update_field` — emit a `readback_format: "spell"` hint in the `field_updated` event for name-shaped fields

---

## Adopted from v1 (unchanged)

| v1 pattern | Status |
|---|---|
| External router classifier (Flash REST, enum output) | **KEEP** — but downscope: run ONCE per session create to confirm step_id matches user intent, not per turn. Saves cost. |
| Parallel safety reflex (Flash classifier) | **KEEP** — run per user-transcript chunk, independent of Live model. |
| Function-call audio masking | **KEEP** — pre-rendered "let me check" WAV streamed during slow tools (especially `advance_step`). |
| Pre-rendered greeting WAV | **KEEP** — biggest perceived-latency win. Stream before bridge accepts user input. |
| STT name hint in prompt | **KEEP** — add the bootstrap name to a `## TRANSCRIPTION HINTS` block in `_base.md`. |

---

## Patterns NOT adopted (and why)

| Pattern | Why skip |
|---|---|
| Pipecat as transport | Tech-stack constraint — stay on Gemini Live SDK |
| `_no_rerun_tools` flag | We already handle `advance_step` as terminal via `step_completed = True` |
| Two-layer integration base | Folds into the voice_bridge extraction plan; not in this plan |
| In-memory slot cache | Domain-specific to appointments; our cross-screen bucket already covers analogous needs |
| Outbound calls / AMD | Out of scope — we're inbound (Flutter WS) only |
| Phonetic name matching (Metaphone/Soundex) | Domain-specific; the STT hint pattern is the lighter equivalent |
| Bedrock Claude Haiku for billing sub-call | We don't have an analogous reasoning-heavy domain sub-call yet |

---

## Phased implementation

### Phase A — Prompt mechanics (≈ 4 h, LOW risk)

Mechanical-rule rewrites in the existing monolith. Tests cover.

1. Adopt **Pattern 3 (VERIFICATION PROTOCOL template)** for `advance_step`, `add_repeatable_row`, `delete_repeatable_row`, `clear_field` — write each as the explicit forbidden-verbs + scan-history + tool-call-is-reply structure.
2. Adopt **Pattern 4 (tool call IS your reply)** verbatim.
3. Adopt **Pattern 6 (count invariant + honesty on uncertainty)** for `advance_step` and Rule 15 compound updates.
4. Adopt **Pattern 7 (math expressions)** for cross-field invariants — plan dates, support schedule overlap, NDIS digit count, funding cap.
5. Adopt **Pattern 8 (closed-set triggers)** — enumerate trigger phrases for Rule 16 (start-from-scratch), Rule 22 (continue), Rule 18b (clear/delete).
6. Adopt **Pattern 11 (date format split)** — explicit speak vs tool-param rules.
7. Adopt **Pattern 15 (letter-spelling)** — Rule 10 enhancement.

Run all 336 tests after each change. Commit per pattern.

### Phase B — Per-step prompt split (≈ 6 h, MEDIUM risk)

The structural refactor. **Pattern 1 + Pattern 2 + Pattern 9 + Pattern 10 + Pattern 14**.

1. Create `prompts/_base.md` from the current shared sections.
2. Create one prompt file per step (6 files) following the rigid sectional template.
3. Each step prompt gets: TASK, STEP CONTEXT, INSTRUCTIONS (procedural runbook), Communication Guidelines (only deltas from base), Anti-patterns (specific), Tools available, Current Context, DECISION FLOWCHART, EDGE CASES, CRITICAL REMINDERS.
4. New module `services/onboarding/src/onboarding/services/tool_registry.py` returns the `FUNCTION_DECLS` subset per step (based on `schema.has_repeatable_sections`).
5. `prompt_builder.build_system_prompt` resolves the template by `schema.step_id`.
6. Test: each step prompt produces a renderable system instruction; the existing test suite passes; new tests verify per-step prompt selection.
7. Smoke test in dev: run one session per step, verify no regressions in `instruction_chars` (expect each step's prompt to be 25-40% smaller than today's monolith).

### Phase C — Sentinels + multi-attempt limits (≈ 3 h, LOW risk)

Pattern 12 + Pattern 13.

1. `FormState` gains `field_attempt_count: dict[str, int]` (key = `section.field`).
2. `tools._update_field` increments on rejection; resets on success.
3. Per-step prompts surface the counter via a "Pending issues" block injection (only when count > 0).
4. After 2 failed confirmations: inject a hard fallback directive.
5. Sentinel strings injected by `prompt_builder` when bootstrap data is corrupted.

### Phase D — Pre-rendered greeting + audio masking (≈ 6 h, MEDIUM risk — touches Flutter)

v1 patterns 6 + 5. Unchanged from v1.

1. `services/pre_greeting.py` — TTS render + Redis cache.
2. `api/routes.py` calls it on session create.
3. `api/ws_routes.py` emits `pre_greeting_audio` WS event.
4. Pre-rendered "let me check" WAV streamed during slow tool calls (audio masking).
5. Document new WS events in `.claude/rules/api.md`.
6. Flutter handoff doc for the playback queue.

Feature-flagged. Backend-side first, Flutter flips the flag when ready.

### Phase E — Per-session router classifier + safety reflex (≈ 4 h, MEDIUM risk)

Downscoped from v1.

1. `services/router_classifier.py` — Gemini Flash REST, enum output. Runs ONCE per session create to validate step_id matches user-stated intent (catches the "user opened wrong screen" case). NOT per turn.
2. `services/safety_classifier.py` — runs per user transcript chunk, async. Enum: `SAFE | ESCALATE_SOFT | ESCALATE_HARD`. On ESCALATE_HARD, server calls `escalate_incident` directly.
3. New WS event `safety_escalated`.
4. Feature flags.

### Phase F — Mid-session sub-state injector (≈ 3 h, MEDIUM risk)

Only after Phase B lands. Sub-states within a step (e.g. "now collecting row 2 of emergency_contacts, missing phone and email") get text injections via `send_realtime_input(text=...)` after each successful tool dispatch.

1. `services/state_injector.py` — pure function `compute_sub_state_directive(state, schema, last_tool_result) -> str | None`.
2. Wire into `gemini_live.py` after each successful dispatch.
3. Track `last_injected_substate` per session; debounce.

---

## File-level impact summary

| File | Phase | Change |
|---|---|---|
| `prompts/_base.md` | B | NEW — shared core |
| `prompts/_partials/verification_protocol.md` | A | NEW — template with slots |
| `prompts/_partials/count_invariant.md` | A | NEW — template |
| `prompts/_partials/tool_is_the_reply.md` | A | NEW — verbatim block |
| `prompts/_partials/closed_set_triggers.md` | A | NEW — enum lists |
| `prompts/personal_information.md` | B | NEW |
| `prompts/lifestyle_requirements.md` | B | NEW |
| `prompts/ndis_plan.md` | B | NEW |
| `prompts/documents.md` | B | NEW |
| `prompts/medical.md` | B | NEW |
| `prompts/consent.md` | B | NEW |
| `prompts/onboarding_system.md` | B | DELETE after migration verified |
| `services/prompt_builder.py` | A, B, C, F | template resolver, sentinel injector, sub-state directive |
| `services/tool_registry.py` | B | NEW |
| `services/state_injector.py` | F | NEW |
| `services/router_classifier.py` | E | NEW |
| `services/safety_classifier.py` | E | NEW |
| `services/pre_greeting.py` | D | NEW |
| `services/gemini_live.py` | D, E, F | pre-greeting stream, classifier tasks, sub-state hook |
| `services/tools.py` | A, C | mechanical rules in handlers, field_attempt_count tracking |
| `models/schema_spec.py` | B | `has_repeatable_sections` property |
| `models/form_state.py` | C | `field_attempt_count` field |
| `core/settings.py` | A-F | feature flags + env vars |
| `api/routes.py` | D, E | pre-greeting render, router classifier at session create |
| `api/ws_routes.py` | D | emit `pre_greeting_audio` |
| `.claude/rules/api.md` | D, E | new event types documented |

---

## New env vars + feature flags

```
SENA_AI_VOICE_PROMPT_SPLIT_ENABLED=false              # Phase B
SENA_AI_VOICE_PRE_GREETING_ENABLED=false              # Phase D
SENA_AI_VOICE_PRE_GREETING_TTS_PROVIDER=google_tts    # Phase D
SENA_AI_VOICE_PRE_GREETING_CACHE_TTL_SEC=604800       # Phase D
SENA_AI_VOICE_AUDIO_MASKING_ENABLED=false             # Phase D
SENA_AI_VOICE_ROUTER_AT_SESSION_CREATE_ENABLED=false  # Phase E
SENA_AI_VOICE_SAFETY_CLASSIFIER_ENABLED=false         # Phase E
SENA_AI_VOICE_SUBSTATE_INJECTOR_ENABLED=false         # Phase F
SENA_AI_VOICE_ROUTER_MODEL_ID=gemini-3-flash-preview
SENA_AI_VOICE_MAX_FIELD_ATTEMPTS=2                    # Phase C
```

Each phase ships behind its own flag. Rollback is one env-var flip.

---

## Verification gates per phase

| Phase | How to verify |
|---|---|
| A | All 336 tests pass; manually verify 5 production-anti-pattern scenarios from session logs — agent emits tool call before any "saved/done/cancelled" verb |
| B | All 336 tests pass; new tests verify per-step prompt selection; `instruction_chars` drops 25-40% per session; smoke test one session per step |
| C | New test: simulate 3 rejected `update_field`s on the same field → confirm hard fallback fires; sentinel injection visible in built prompts |
| D | Connect WS in dev; `pre_greeting_audio` arrives within 250ms; audio masking plays during a slow `advance_step`; Flutter playback smoke |
| E | Inject a self-harm test transcript → `safety_escalated` fires + `escalate_incident` ran server-side without the Live model calling it; router validates step_id at session create |
| F | Enable in dev; run a 6-section session per step; verify `state_directive_injected` logs align with state transitions; no Live model reconnects |

---

## Quantified expected outcomes

| Metric | Baseline | Target |
|---|---|---|
| `instruction_chars` per session | ~59k | ~30-35k (per-step prompts) |
| Tool-honesty drift per 100 sessions | ~4 | <1 |
| Time-to-first-audio | ~2.5s | ~250ms |
| `advance_step` dead-air | 1-5s | <500ms (filler covers) |
| Repeated `CONFIRM_REQUIRED` on same field (>2 attempts) | tracked but not handled | server-side hard fallback at 2 |
| Safety signals caught when agent missed | 0 | tracked via `safety_escalated` events |
| Session creates per-screen-prompt selection | n/a | 100% |

---

## Out of scope

- voice_bridge extraction → `sena-ai/VOICE_BRIDGE_EXTRACTION_PLAN.md`
- Case-note voice integration → pending Ultraplan PR
- Migration off Gemini Live (ruled out by user)
- Migration to Pipecat (ruled out by user)
- Multi-model split of the Live session itself (Live = one model per session)

---

## Decisions required before starting Phase A

1. **Per-step prompt file format** — Markdown with Jinja-style `{{slots}}`, or Python `str.format()` with `{slot}` syntax? (Receptionist project uses `format_map`; we'd match for stack consistency.)
2. **`_base.md` vs `_partials/`** — single shared base file, or partials per concern (verification_protocol.md, count_invariant.md, ...)? My recommendation: BOTH. `_base.md` is included verbatim at top of every step prompt. `_partials/` are template fragments rendered by `prompt_builder` with slot substitution.
3. **`field_attempt_count` persistence** — store in FormState (lives in Redis with the session) or in-memory only on the dispatcher (resets on resumption)? My take: FormState — survives Gemini Live reconnects.
4. **Router classifier scope** — Phase E should it ONLY validate step_id at session create, or also be available for mid-session reroutes (rare but possible)? My take: only at session create for now. Mid-session reroute is Phase G+.
5. **Hard limit on `MAX_FIELD_ATTEMPTS`** — 2 (their pattern) or 3? Voice is harder than form; 3 attempts gives the participant more room. My recommendation: 3 default, env-configurable.
6. **Branch strategy** — one branch `feat/voice-pattern-adoption-v2` with phased commits, or one branch per phase? My take: one branch, 6 atomic commits, each behind its own flag. Flip flags independently.

Once those six are answered, Phase A is ready to start.
