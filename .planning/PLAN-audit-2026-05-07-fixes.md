---
title: Forensic Audit 2026-05-07 — Backend Implementation Plan
status: pending — awaiting execution
author: Forensic-audit subagent + planner
created: 2026-05-07
audience: Sonnet (or any model) — execute in order, do not skip steps
companion_doc: ../FLUTTER_DEV_HANDOFF.md (Addendum 2026-05-07 — Issues #18-#22)
---

# Forensic Audit 2026-05-07 — Backend Implementation Plan

> **Scope:** This plan covers ONLY backend (`sena-ai/services/onboarding/`) fixes for the 7 anti-pattern instances identified by the forensic audit on 2026-05-07. Flutter-side fixes are in `FLUTTER_DEV_HANDOFF.md` Addendum 2026-05-07 (Issues #18-#22).
>
> **Total backend changes:** 7 surgical edits across 5 files + 1 new helper module + 4 new tests.
>
> **Verification gate:** `pytest services/onboarding/tests/ --ignore=services/onboarding/tests/test_cross_screen_context.py --ignore=services/onboarding/tests/test_validators.py -x -q` must remain ≥78 passing after each step. Pre-existing import errors in those two ignored files are unrelated.

---

## 0. Anti-Pattern Map (read first)

| Code | Anti-Pattern | Definition |
|------|--------------|------------|
| AP-2 | Prompt-vs-Schema Drift | Prompt asserts behaviour the schema doesn't enforce; the model obeys the prompt |
| AP-3 | Context Boundary Leak | Personalisation tokens buried in `[LIVE_STATE_JSON]` data, not interpolated as a directive |
| AP-4 | Trust-the-Model Termination | Control-plane action gated only by prose prompt rule, no server arg check |
| AP-5 | Producer-Without-Schema-Contract | New events shipped without typed contract |

---

## 1. Sequential Steps (DO IN THIS ORDER)

### STEP 1 — Add `next_optional_field` helper (AP-2 anchor for Rule 5)

**Why:** Rule 5 in the system prompt currently says "iterate the optional fields" with no anchor — the model picks any or none. Add a deterministic next-optional pointer mirroring `next_required_field`.

**Files:**
- Touch: `services/onboarding/src/onboarding/services/validators/sequencing.py` (likely; or wherever `next_required_field` lives — Grep for `def next_required_field` first)
- New tests: extend the existing sequencing test file with two new cases

**Implementation:**

```python
# In services/validators/sequencing.py (or sibling — match existing layout)

def next_optional_field(schema: "StepSchema", state: "FormState") -> dict | None:
    """First optional (required=False) field with no value, in schema order.

    Rule-5 anchor: returns deterministic next optional so the prompt model
    iterates them predictably. Mirrors next_required_field shape.
    Returns None when every optional is filled (or the step has none).
    """
    for section in schema.sections:
        is_rep = getattr(section, "is_repeatable", False)
        fields = section.item_fields if is_rep else (section.fields or [])
        sec_vals = state.values.get(section.id) or {}
        if is_rep:
            row = (sec_vals[0] if isinstance(sec_vals, list) and sec_vals else {})
        else:
            row = sec_vals if isinstance(sec_vals, dict) else {}
        for field in fields:
            if field.required:
                continue
            raw = row.get(field.id) if isinstance(row, dict) else None
            if not _has_value(raw):
                return {
                    "section_id": section.id,
                    "field_id": field.id,
                    "label": field.label,
                }
    return None
```

**Tests to add (in same test file as `next_required_field`):**

1. `test_next_optional_field_returns_first_empty_optional_in_schema_order`
2. `test_next_optional_field_returns_none_when_all_optionals_filled`

**Acceptance:** new helper exported, tests green.

**Estimated diff size:** ~30 lines added.

---

### STEP 2 — Interpolate `__PARTICIPANT_NAME__` + `__NEXT_OPTIONAL_FIELD__` tokens (AP-3 + AP-2)

**Why:**
- AP-3: `bootstrap.participant_display_name` is currently buried inside `[LIVE_STATE_JSON]`. The model treats it as data, not a salutation directive. Personalisation drops on new screens because the prompt has no top-level greeting instruction tied to the name.
- AP-2: hooks `next_optional_field` into the prompt so Rule 5 has an anchor.

**Files:**
- Touch: `services/onboarding/src/onboarding/services/prompt_builder.py`

**Implementation steps:**

1. **Inside `build_system_prompt(...)`, before the existing `.replace(...)` chain, compute the new values:**

   ```python
   from onboarding.services.validators.sequencing import next_optional_field

   participant_name = (
       bootstrap.participant_display_name
       if bootstrap and bootstrap.participant_display_name
       else "unknown"
   )

   next_opt = next_optional_field(schema, state)
   next_opt_text = (
       f"{next_opt['section_id']}.{next_opt['field_id']} ({next_opt['label']})"
       if next_opt else ""
   )
   ```

2. **Add to the `.replace` chain:**

   ```python
   .replace("__PARTICIPANT_NAME__", participant_name)
   .replace("__NEXT_OPTIONAL_FIELD__", next_opt_text)
   ```

3. **Add tests** to `tests/test_prompt_builder.py`:
   - `test_participant_name_token_interpolated_when_present`
   - `test_participant_name_token_falls_back_to_unknown_when_missing`
   - `test_next_optional_field_token_interpolated`
   - `test_next_optional_field_token_empty_when_none_remain`

**Acceptance:** prompt-builder test cases pass; manual `print(prompt)` shows the name at the top, not buried.

**Estimated diff size:** ~15 lines in `prompt_builder.py`, ~40 lines tests.

---

### STEP 3 — Update `prompts/onboarding_system.md` (AP-2 + AP-3)

**Why:** turn the new tokens into actual prompt directives. This is where bug #2 (non-sequential), #3 (lost personalisation), #4 (morning routine "optional") get their fix in user-facing behaviour.

**Files:**
- Touch: `services/onboarding/src/onboarding/prompts/onboarding_system.md`

**Implementation — three surgical edits:**

#### Edit 3a — Top-of-file greeting directive (AP-3)

**Insert AT THE VERY TOP** of the file, before the existing `# Sena — Onboarding Voice Agent System Instruction` line:

```markdown
## ADDRESS THE PARTICIPANT

The participant's display name for this session is: **__PARTICIPANT_NAME__**

If the value above is a real first name, open every screen with:
> "Hi {name}, ..." (use exactly the name shown above; never invent variations)

If the value is the literal string `__PARTICIPANT_NAME__` (renderer
left it untouched) or the string `unknown`, fall back to "Hi there, ...".

This is a directive, NOT optional context. The name is your single source
of truth for addressing the participant — never substitute, never fall
back to "User" or "Participant" when a real name is present.

---
```

#### Edit 3b — Rule 5 anchor (AP-2)

**Find:** the existing Rule 5 block. **Replace** it with:

```markdown
### Rule 5 — Proactive Optional Prompting

After every `required: true` field in the current section is filled,
**iterate the `required: false` fields in the order shown by**
`[LIVE_STATE_JSON].next_optional_field`. For each one ask:

> "Would you also like to add a [label]? It's optional but it helps us
> tailor support."

If the user declines, move on without recording a value. NEVER silently
skip an optional field — silence implies you forgot they exist. The
server-supplied `next_optional_field` is your authoritative pointer;
never iterate optionals in a different order.
```

#### Edit 3c — Rule 9 min-zero protocol (AP-2 — fixes "morning routine" bug)

**Find:** the bullet list inside Rule 9. **Append** at the end:

```markdown
- **Min-zero repeatable sections** (e.g. `morning_routine`, `evening_routine`,
  `medical_history` — schema declares `repeatable.min: 0`):
  Even when the schema permits zero rows, ALWAYS surface the section once.
  Announce it, then ask:
  > "Would you like to tell me about your {section.label}? You can skip
  >  it, but most participants find it helpful to capture at least one."

  Only call `add_repeatable_row` after the user explicitly opts in. NEVER
  silently skip a min-zero repeatable — silence is interpreted by the user
  as "the system forgot this exists" (Rule 5 generalised to whole sections).
```

**Acceptance:** open the file, confirm three edits visible. No test changes for prompt copy (we don't snapshot prompt strings).

**Estimated diff size:** ~30 lines net added.

---

### STEP 4 — Harden `_advance_step` (AP-4 — bug #6 + N-2 + N-7)

**Why:** three failure modes converge on this handler:
1. Bug #6: `confirmation_transcript` is declared in `FUNCTION_DECLS` but NOT in `required:[]`, AND the handler never validates non-empty. Model can call with zero args and the webhook fires.
2. N-2: cross-field invariants (`emergency-email-unique`, `plan-end-after-start`, `medical-history-all-or-none`) only run inside `validate_step_complete`, which is **never called** at the advance gate. Cross-field violations slip past.
3. N-7: `confirmation_transcript` is included in webhook payload but receivers can't rely on it being present.

**Files:**
- Touch: `services/onboarding/src/onboarding/services/tools.py`

**Implementation — two edits:**

#### Edit 4a — Tighten `FUNCTION_DECLS.advance_step`

**Find:** the `advance_step` entry in `FUNCTION_DECLS`. **Replace** the whole entry with:

```python
{
    "name": "advance_step",
    "description": (
        "Call ONLY after every required field is filled, validate_step_complete "
        "has zero rejections, and the user has spoken an explicit confirmation "
        "(e.g. 'yes I'm done', 'submit it'). Pass the user's exact confirmation "
        "words in confirmation_transcript — server rejects empty strings."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "confirmation_transcript": {
                "type": "string",
                "minLength": 3,
                "description": (
                    "EXACT verbatim words the user spoke to confirm completion. "
                    "Required and non-empty. Do not paraphrase. Do not synthesise."
                ),
            },
        },
        "required": ["confirmation_transcript"],
    },
},
```

#### Edit 4b — Harden `_advance_step` handler body

**Find:** `async def _advance_step(self, args: dict[str, Any])`. **Insert immediately after the existing `state = await self._repo.get_state(...)` + None-guard block, BEFORE the existing `if state.completed:` idempotency guard:**

```python
        # AP-4 fix: validate confirmation_transcript is genuinely user-spoken.
        # Without this the schema constraint is the only barrier; Gemini has
        # been observed sending zero-arg tool calls when the user's prior
        # utterance happened to end with "okay" — that is not consent.
        confirmation = (args.get("confirmation_transcript") or "").strip()
        if len(confirmation) < 3:
            return {
                "ok": False,
                "rejection": {
                    "code": "missing_confirmation",
                    "reason_human": (
                        "I need a clear yes from you before I save and move on — "
                        "could you confirm you're happy with everything you've shared?"
                    ),
                },
            }
```

**Find:** the existing `state.recompute_completion(...)` + `field_skipped_warning` emit + `pending_validation_errors` block. **Insert AFTER all of those guards pass, BEFORE `state.completed = True`:**

```python
        # N-2 fix: cross-field invariant gate.
        # Why: pending_validation_errors only catches per-field rejections.
        # Cross-field rules (emergency-email-unique, plan-end-after-start,
        # medical-history-all-or-none) only run inside validate_step_complete,
        # which previously was never invoked at advance time. A user could
        # hit advance with two emergency contacts sharing one email and the
        # webhook would fire with corrupt data.
        from onboarding.services.validators import validate_step_complete

        cross_rejections = validate_step_complete(self._schema, state)
        if cross_rejections:
            for rej in cross_rejections:
                await self._emit({
                    "type": "validation_rejection",
                    "section_id": "_aggregate",
                    "field_id": "_aggregate",
                    "rejection": rej.model_dump(),
                })
            return {
                "ok": False,
                "rejection": {
                    "code": "cross_field_invariants_failed",
                    "reason_human": cross_rejections[0].reason_human,
                    "all_rejections": [r.model_dump() for r in cross_rejections],
                },
            }
```

**Tests to add (in `tests/test_tools.py`):**

1. `test_advance_step_rejects_empty_confirmation_transcript`
2. `test_advance_step_rejects_short_confirmation_transcript` (e.g. "ok" — under 3 chars)
3. `test_advance_step_runs_cross_field_validators_and_blocks_on_rejection`
4. `test_advance_step_emits_validation_rejection_for_each_cross_field_violation`

**Acceptance:** 4 new tests pass; existing tests stay green.

**Estimated diff size:** ~50 lines added in `tools.py`, ~80 lines tests.

---

### STEP 5 — Race fix in `_handle_validation_failed` (N-3)

**Why:** when the Flutter client sends `validation_failed`, the handler immediately calls `session.send_realtime_input(text=...)`. If the user is still speaking when this fires, the injection text can land inside Gemini's input-transcription buffer and be misread as user speech, polluting the conversation.

**Files:**
- Touch: `services/onboarding/src/onboarding/services/gemini_live.py`

**Implementation:**

**Find:** in `_handle_validation_failed`, the line `await session.send_realtime_input(text=injection)`. **Replace** with:

```python
        # N-3 race fix: flush any in-flight audio buffer before injecting
        # text so the [SCREEN VALIDATION] hint cannot be concatenated into
        # the user's current utterance and misread as their speech.
        # send_realtime_input(audio_stream_end=True) is safe to call even
        # when no audio is currently buffered.
        await session.send_realtime_input(audio_stream_end=True)
        await session.send_realtime_input(text=injection)
```

**Tests:** difficult to unit-test the Gemini wire — verify in integration by manual voice test (speak while frontend rejects a value; agent should not echo your speech). Add a comment in the test file:

```python
# NOTE: N-3 (audio_stream_end before text injection) is verified via manual
# integration test only — Gemini Live SDK has no in-process race harness.
```

**Acceptance:** code change visible; manual integration test confirms no echo.

**Estimated diff size:** ~5 lines.

---

### STEP 6 — Mirror v2 `field_errors` into `pending_validation_errors` (N-4)

**Why:** `_handle_screen_state` (v2 path) currently only injects a prompt hint when `field_errors` is non-empty. It does NOT upsert into `state.pending_validation_errors`. Result: if the Flutter client renders v2 errors but forgets to additionally emit a `validation_failed` control frame, the `advance_step` gate (`if state.pending_validation_errors`) silently passes despite visible UI errors.

**Files:**
- Touch: `services/onboarding/src/onboarding/services/gemini_live.py` (in `_handle_screen_state`, the `version=2` branch)

**Implementation:**

**Find:** the `_handle_screen_state` method body, the v2 branch where `field_errors` is read for prompt rendering. **Insert** (after the prompt injection, before the early `return`):

```python
        # N-4 fix: mirror v2 field_errors into state.pending_validation_errors.
        # Why: previously the v2 handler only injected a prompt hint. Pending
        # validation tracking depended on a separate validation_failed control
        # frame, which Flutter could forget. The advance_step gate checks
        # pending_validation_errors, so the gate would silently pass.
        # Mirror here so a single source of truth always exists.
        state = await self._repo.get_state(self._session_id)
        if state is not None:
            for fe in (data.get("field_errors") or []):
                sec, fld = fe.get("section_id"), fe.get("field_id")
                if not (sec and fld):
                    continue
                idx = fe.get("repeatable_index")
                key = (sec, fld, idx)
                # Idempotent upsert — drop existing then append
                state.pending_validation_errors = [
                    e for e in state.pending_validation_errors
                    if (e.get("section_id"), e.get("field_id"), e.get("repeatable_index")) != key
                ]
                state.pending_validation_errors.append({
                    "section_id": sec,
                    "field_id": fld,
                    "repeatable_index": idx,
                    "code": fe.get("code") or "client_validation",
                    "reason_human": fe.get("reason_human") or fe.get("hint") or "Invalid value",
                })
            await self._repo.save_state(state, ttl_sec=settings.session_max_sec)
```

**Tests to add (in `tests/test_gemini_live.py` or a new `tests/test_screen_state_handler.py`):**

1. `test_v2_screen_state_with_field_errors_upserts_pending_validation_errors`
2. `test_v2_screen_state_idempotent_on_repeated_same_field_error`
3. `test_v2_screen_state_with_no_field_errors_does_not_touch_pending_list`

**Acceptance:** 3 new tests pass; advance_step gate now blocks even if Flutter forgets `validation_failed` frame.

**Estimated diff size:** ~25 lines in handler, ~60 lines tests.

---

### STEP 7 — Auto-pin focus on `add_repeatable_row` (N-5)

**Why:** `_add_repeatable_row` currently emits `row_added` only. The agent must remember to call `enter_repeatable_section(intent="next")` next, per Rule 9. If it forgets, the focus pin stays on the previous row, and subsequent `update_field` calls land on the wrong row.

**Files:**
- Touch: `services/onboarding/src/onboarding/services/tools.py` (in `_add_repeatable_row`)

**Implementation:**

**Find:** in `_add_repeatable_row`, the existing `await self._emit({"type": "row_added", ...})`. **Insert AFTER it, BEFORE the `return`:**

```python
        # N-5 fix: auto-pin focus on the new row.
        # Why: the agent should always be able to write to the row it just
        # added without an explicit enter_repeatable_section step. The
        # previous handler relied on the model remembering to make that
        # call; missed calls caused subsequent update_field to land on the
        # stale prior row's focus pin.
        state.focused_section = section_id
        state.focused_repeatable_index = new_index
        state.touch()
        await self._repo.save_state(state, ttl_sec=settings.session_max_sec)

        await self._emit({
            "type": "repeatable_section_entered",
            "section_id": section_id,
            "row_index": new_index,
            "intent": "next",
        })
```

**Tests to add:**

1. `test_add_repeatable_row_pins_focus_on_new_index`
2. `test_add_repeatable_row_emits_repeatable_section_entered_with_intent_next`

**Acceptance:** 2 new tests pass; agent can write to a new row immediately after `add_repeatable_row` without an explicit `enter_repeatable_section` call.

**Estimated diff size:** ~15 lines in `tools.py`, ~30 lines tests.

---

## 2. Verification Gates

Run after each step:

```bash
cd C:\Users\Admin\Downloads\sena-mobile\sena-mobile\SENA_AI\sena-ai
python -m pytest services/onboarding/tests/ \
  --ignore=services/onboarding/tests/test_cross_screen_context.py \
  --ignore=services/onboarding/tests/test_validators.py \
  -x -q
```

**Expected counts:**

| After step | Pass count | Notes |
|------------|-----------|-------|
| 1 | 80 | +2 (next_optional_field) |
| 2 | 84 | +4 (prompt_builder tokens) |
| 3 | 84 | no test delta (prompt copy not snapshotted) |
| 4 | 88 | +4 (advance_step hardening) |
| 5 | 88 | no test delta (manual integration only) |
| 6 | 91 | +3 (v2 field_errors mirror) |
| 7 | 93 | +2 (auto-pin focus) |

**Final:** 93 passing, 0 failing.

---

## 3. Commit Plan

Each step commits atomically with a conventional message:

| Step | Commit message |
|------|---------------|
| 1 | `feat(onboarding): add next_optional_field helper for Rule 5 anchor` |
| 2 | `feat(onboarding): interpolate participant_name + next_optional tokens` |
| 3 | `feat(onboarding): prompt directives — top-level greeting + min-zero repeatable protocol` |
| 4 | `fix(onboarding): harden advance_step gate (confirmation + cross-field invariants)` |
| 5 | `fix(onboarding): flush audio before validation text injection` |
| 6 | `fix(onboarding): mirror v2 field_errors into pending_validation_errors` |
| 7 | `fix(onboarding): auto-pin focus on add_repeatable_row` |

---

## 4. Out of Scope (do NOT do here)

| Item | Why deferred |
|------|--------------|
| Flutter event-model wiring (Issues #18-#22) | Frontend work — handoff doc owns it |
| Schema fixture changes (e.g. force `required:true` on `morning_routine`) | Schema is correct; the prompt is the fix |
| LLM-based intent detection of "yes/no" confirmation | Out of audit scope; current keyword check is adequate |
| Removing the `validation_failed` control frame entirely | N-4 fix mirrors v2 path; the explicit frame remains a useful belt-and-braces |

---

## 5. After All 7 Steps Complete

1. Run full pytest sweep — confirm 93 passing.
2. Update `.claude/tasks/TASKS.md` task #14 → status `completed`.
3. Update `SENA_AI/FLUTTER_DEV_HANDOFF.md` — flip the Issue #18-#22 checkboxes when frontend work also lands (separate session).
4. Delete this plan file (it has served its purpose) OR mark `status: shipped` in frontmatter and keep for trail.

---

## 6. Anti-Recurrence Checklist

When adding a new server→client event in the future:

1. ✅ Add the typed entity in `voice_event.dart`
2. ✅ Add a `case` in `VoiceEventModel.parse`
3. ✅ Add a controller reaction
4. ✅ Add an integration test that asserts the event fires AND the UI consumes it
5. ✅ Add to `FLUTTER_DEV_HANDOFF.md` Backend Wire Contracts table

When adding a new tool to `FUNCTION_DECLS`:

1. ✅ Required arguments listed in `parameters.required:[]`
2. ✅ Handler validates non-empty / type / shape BEFORE side effects
3. ✅ Tests cover the negative path (empty / missing args)

When adding a new prompt rule:

1. ✅ Anchor it to a state-rendered token (e.g. `[LIVE_STATE_JSON].next_optional_field`)
2. ✅ Avoid asking the model to "remember" prior turns or "iterate" without an order key
3. ✅ Test by running a session and grep'ing the rendered prompt for the anchor token
