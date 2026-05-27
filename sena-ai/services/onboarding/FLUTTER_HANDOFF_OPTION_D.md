# Flutter Handoff — Option D State Channel

**Status:** server-side complete (2026-05-25) · awaiting Flutter implementation
**Audience:** sena-mobile Flutter team
**Scope:** addendum to `flutterhandoffdev.md` for ONE specific behaviour change. Do NOT replace existing contracts.

> **READ THIS FIRST:** This doc is the Option D handoff. Do not implement before reading
> `SENA_AI/.claude/plans/per-screen-session-model/ISSUE_AND_SOLUTION.md` §7.
> That spec carries the full problem statement, design space, and rejection reasoning. This
> file is the implementation contract only.

---

## 1. Why this exists

Gemini Live was hallucinating participant data mid-session (fabricating names, dates, NDIS numbers). Root cause: server baked a frozen JSON copy of FormState into Gemini's `system_instruction` at session start, AND Flutter shipped runtime field changes through the conversation. Two writers, one field → context-window compression collapsed them into ambiguous summaries → fabricated values.

Server-side fix landed: bootstrap JSON shrunk to header-only (no field values); prompt rewritten so "source of truth = most recent tool reply's `state` field." See `ISSUE_AND_SOLUTION.md` §3 + §7.

**Flutter's half:** ship the fresh full state in every `tool_response.result.state`. Without this, the server-side fix is incomplete and Gemini has NO authoritative view of FormState at all.

---

## 2. The contract — what changes for Flutter

Three changes. Order doesn't matter; ship as one PR.

### Change A — Every tool reply must carry `state`

Tool replies that previously returned `{"ok": true}` (or `{"ok": false, "reason": "..."}`) must now also include a `state` key carrying the fresh full TurnPayload snapshot.

Affected tools (5 mobile-bridged, see `services/tools.py:21-24`):

| Tool | Before | After |
|------|--------|-------|
| `update_field` | `{"ok": true, "saved": {...}}` | `{"ok": true, "saved": {...}, "state": {...full snapshot...}}` |
| `clear_field` | `{"ok": true}` | `{"ok": true, "state": {...}}` |
| `add_row` | `{"ok": true, "row_index": N}` | `{"ok": true, "row_index": N, "state": {...}}` |
| `delete_row` | `{"ok": true}` | `{"ok": true, "state": {...}}` |
| `submit_step` | `{"ok": true}` or `{"ok": false, "blockers": [...]}` | same + `"state": {...}` on BOTH paths |

`escalate_incident` is server-side only (`services/tools.py:149-153`) — no `state` needed.

The `state` payload SHAPE is the `TurnPayload` model — see §4 below.

### Change B — Handle the new `get_current_state` tool

Server has declared a new tool (`services/tools.py:115-132`). Gemini calls it when its view feels stale.

```jsonc
// tool_request from server
{ "type": "tool_request", "tool_id": "...", "name": "get_current_state", "args": {} }

// expected Flutter tool_response
{ "type": "tool_response", "tool_id": "...", "result": {
    "ok": true,
    "state": { /* full fresh TurnPayload snapshot */ }
}}
```

Empty parameters. Always succeed with the freshest state. Never include `saved` — this tool doesn't save anything.

### Change C — No change needed for `escalate_incident`

Server handles it entirely (audit log + alert). Flutter doesn't see this tool call. Don't add a handler.

---

## 3. The `state` payload shape

This is the exact shape the `TurnPayload` Pydantic model emits server-side. Documented at `services/onboarding/src/onboarding/models/turn_payload.py:62-78`. Use these EXACT keys (snake_case) — Gemini's prompt is wired to them.

### Top-level

| Key | Required | Dart type | Source |
|-----|----------|-----------|--------|
| `participant` | yes | `Map<String, String>` | object below |
| `step` | yes | `Map<String, dynamic>` | object below |
| `bootstrap_mode` | yes | `String` enum | `"new_user"` / `"returning_same_page"` / `"page_handoff"` |
| `prior_steps` | yes | `Map<String, dynamic>` | nested dict, may be empty `{}` |
| `visible_fields` | yes | `List<Map<String, dynamic>>` | array of VisibleField; may be empty `[]` |
| `next_target` | nullable | `Map<String, dynamic>?` | object below, or `null` |
| `last_rejection` | nullable | `Map<String, dynamic>?` | object below, or `null` |
| `pending_confirmation` | nullable | `Map<String, dynamic>?` | object below, or `null` |

### `participant`

```jsonc
{ "first_name": "Jane", "display_name": "Jane D." }
```

Both required (default `""` if not yet captured). NO PII beyond these two (no DOB, email, phone, NDIS number, participant_id).

### `step`

```jsonc
{ "id": "personal_information", "label": "Personal Information", "number": 1 }
```

`id` must match the step_id Flutter is on. `number` is 1-indexed.

### `bootstrap_mode`

`"new_user"` for first session ever · `"returning_same_page"` for routine refreshes · `"page_handoff"` when participant just moved screens. Use the value Flutter already passes at session start.

### `visible_fields[]` (one object per field currently on screen)

```jsonc
{
  "path": "basics.date_of_birth",
  "label": "your date of birth",
  "type": "date",
  "required": true,
  "readonly": false,
  "value": "2001-05-05",
  "enum_values": null,
  "validations_hint": null
}
```

| Key | Type | Notes |
|-----|------|-------|
| `path` | string | Section + field joined by `.` (e.g. `"basics.email"`, `"emergency_contacts[0].relation"` for repeatables) |
| `label` | string | Human-friendly label (used in agent speech) |
| `type` | enum | One of: `text`, `email`, `phone`, `date`, `enum`, `multi_enum`, `boolean`, `number`, `textarea`, `file`, `time`, `year`, `currency` |
| `required` | bool | Whether field is required for `submit_step` |
| `readonly` | bool | If true, agent will NOT call `update_field` (account-bound values like email) |
| `value` | any \| null | Current value, or `null` if empty |
| `enum_values` | `List<String>?` | For `enum`/`multi_enum` types — null otherwise |
| `validations_hint` | `String?` | Optional human-readable validation hint |

### `next_target` (nullable)

What field the agent should ask next, if any.

```jsonc
{ "path": "basics.phone", "label": "your phone number", "reason": "next_required" }
```

`reason` is one of: `"next_required"` · `"user_requested"` · `"forced_unlock"`.

### `last_rejection` (nullable)

Most recent server-side validation failure. Agent re-asks the named field with this reason verbatim.

```jsonc
{ "path": "basics.email", "reason": "Email address looks invalid — please spell it out.", "code": "invalid_format" }
```

### `pending_confirmation` (nullable)

Set when last capture was low-confidence and needs explicit yes/no before saving.

```jsonc
{ "path": "basics.date_of_birth", "heard_value": "5 May 2001" }
```

### `prior_steps`

Carries earlier-step summaries (name/dob/etc.) so the agent can reference cross-step values without re-asking. Nested dict; keys are step IDs.

```jsonc
{
  "personal_information": { "name": "Jane Doe", "dob": "2001-05-05", "_step_label": "Personal Information" },
  "ndis_plan_details": { "ndis_number": "123456789", "_step_label": "NDIS Plan Details" }
}
```

If Flutter doesn't have prior-step data, return `{}`.

---

## 4. Worked example — 4-turn conversation

User: *"My name is Jane."* → Gemini calls `update_field`.

**Turn 1 — tool_request (server → Flutter):**
```jsonc
{
  "type": "tool_request",
  "tool_id": "t1",
  "name": "update_field",
  "args": { "section": "basics", "field": "full_name", "value": "Jane" }
}
```

**Turn 1 — tool_response (Flutter → server, NEW SHAPE):**
```jsonc
{
  "type": "tool_response",
  "tool_id": "t1",
  "result": {
    "ok": true,
    "saved": { "section": "basics", "field": "full_name", "value": "Jane" },
    "state": {
      "participant": { "first_name": "Jane", "display_name": "Jane" },
      "step": { "id": "personal_information", "label": "Personal Information", "number": 1 },
      "bootstrap_mode": "returning_same_page",
      "prior_steps": {},
      "visible_fields": [
        { "path": "basics.full_name", "label": "your full name", "type": "text", "required": true, "readonly": false, "value": "Jane", "enum_values": null, "validations_hint": null },
        { "path": "basics.date_of_birth", "label": "your date of birth", "type": "date", "required": true, "readonly": false, "value": null, "enum_values": null, "validations_hint": null },
        { "path": "basics.phone", "label": "your phone number", "type": "phone", "required": true, "readonly": false, "value": null, "enum_values": null, "validations_hint": null }
      ],
      "next_target": { "path": "basics.date_of_birth", "label": "your date of birth", "reason": "next_required" },
      "last_rejection": null,
      "pending_confirmation": null
    }
  }
}
```

**Turn 2:** user says *"5 May 2001"* → `update_field` for `date_of_birth` → Flutter saves → returns tool_response with `state.visible_fields` reflecting BOTH `full_name="Jane"` AND `date_of_birth="2001-05-05"`. `next_target` advances to `basics.phone`.

**Turn 3:** participant types phone via UI (no voice). See §5 for handling.

**Turn 4:** user asks *"What's my name on file?"* → Gemini reads the most recent `function_response.state.visible_fields`, finds `basics.full_name.value == "Jane"`, answers *"Jane."* No hallucination — the answer comes from the tool reply, not from frozen bootstrap.

---

## 5. UI-driven update path

When the participant edits a field via the Flutter UI directly (not by voice), Gemini doesn't know unless Flutter tells it. Two paths:

### Path A (RECOMMENDED) — Synthetic `get_current_state` response

When Flutter detects a UI-driven field change and the voice session is active, send a synthetic `tool_response` for `get_current_state` over the WS:

```jsonc
{
  "type": "tool_response",
  "tool_id": "synthetic-ui-<timestamp>",
  "result": { "ok": true, "state": { /* fresh full snapshot */ } }
}
```

The server forwards this to Gemini; Gemini treats it as a fresh state delivery (it doesn't need to have asked first — the function_response arrives in conversation context regardless).

> **VERIFY** with server team: this requires `services/api/ws_routes.py` to accept an unprompted `tool_response`. If it currently only accepts replies to a prior `tool_request`, server-side will need a small additive change. Flag back if blocked.

### Path B (fallback) — Let Gemini self-trigger

If Path A isn't viable, Gemini's prompt §1b instructs it to call `get_current_state()` when its function_response is more than 3 turns old AND it's about to assert any field value. Flutter just needs to implement the Change B handler (§2). Latency: up to 3 turns of stale state before Gemini auto-refreshes.

Use Path A. Path B is the safety net.

---

## 6. What server is doing on its half

Already shipped (2026-05-25):

- Bootstrap JSON in `system_instruction` shrunk to header-only (`participant` + `step` + `next_target` + `bootstrap_mode`). No `visible_fields[].value` in bootstrap. See `services/prompt_builder.py:28-47`.
- Prompt §1 rewritten: *"Your source of truth is the `state` field in the most recent `function_response`."*
- Prompt §1a: FORBIDDEN PHRASES list for name, DOB, phone, NDIS number, plan dates, plan management — agent cannot assert these without a matching `function_response.state`.
- Prompt §1b: staleness self-check → call `get_current_state()` when last tool reply >3 turns old.
- Prompt §6: tool count bumped to "Seven tools" with `get_current_state` row.
- Prompt §8 demoted from "authoritative" to "bootstrap state — first turn only".
- `services/tools.py`: `get_current_state` added to `_KNOWN_TOOLS` (line 21) + `FUNCTION_DECLS` entry between `submit_step` and `escalate_incident` (line 115).
- `services/gemini_live.py:141`: `SlidingWindow(target_tokens=4000)` for Layer 3 context compression — old conversational drift gets summarised away faster.

---

## 7. Feature flag

Server flag: `SENA_AI_ONBOARDING_TOOL_STATE_CHANNEL` (boolean, default `true`).

- `true` (default): server expects Flutter to ship `state` in tool replies; bootstrap is shrunk.
- `false` (rollback): server reverts to full TurnPayload in bootstrap; passes Flutter's tool replies through unchanged (so adding `state` is harmless in this mode).

Implication for Flutter: shipping `state` is SAFE in both modes. Not shipping `state` is the legacy hallucination-prone path — only used if rollback fires.

See `services/core/settings.py:71-75`.

---

## 8. Acceptance checks for Flutter

| # | Check | How to verify |
|---|-------|---------------|
| 1 | `update_field` round-trip includes `state` with all `visible_fields` reflecting the saved value | Capture WS frames during a voice session; saved field shows up in next tool_response's `state.visible_fields[N].value` |
| 2 | `get_current_state` handler returns fresh state with zero parameters | Simulate server-side `tool_request` with empty args; confirm Flutter returns `{ok: true, state: {...}}` with current FormState |
| 3 | Mid-session UI edit triggers a state refresh via Path A or Path B | Edit a field via the UI mid-session; observe Gemini's next utterance references the new value within 0–3 turns |
| 4 | `submit_step` failure path also carries state | Trigger a validation failure (e.g. plan_end < plan_start); confirm tool_response has BOTH `blockers: [...]` AND `state: {...}` |
| 5 | `escalate_incident` handler NOT added | Confirm `escalate_incident` is silently dropped client-side (server handles it) |

---

## 9. Out of scope (do NOT implement)

- The per-screen session reconnect work (PLAN #1) — that ships separately as Phase 2 once Option D stabilises.
- Server-side state validation. Mobile remains authoritative — server just declares and forwards.
- Tool result auditing (Layer 5 in spec §7.12) — server-side observability, not Flutter.

---

## 10. References

### Internal
- Spec: `SENA_AI/.claude/plans/per-screen-session-model/ISSUE_AND_SOLUTION.md` §7 (the fix), §7.12 (5-layer enforcement strategy), §10 (acceptance criteria)
- Visual storyboard: `SENA_AI/.claude/plans/per-screen-session-model/OPTION_D_EXPLAINED.html`
- Comparison matrix of all 6 options considered: `SENA_AI/.claude/plans/per-screen-session-model/STATE_REFRESH_OPTIONS.html`
- PLAN #1 (per-screen reconnect, Phase 2 follow-up): `SENA_AI/.claude/plans/per-screen-session-model/PLAN.md`

### Code (server-side, file:line)
- `services/onboarding/src/onboarding/services/tools.py:21-24` — `_KNOWN_TOOLS` frozenset (6 mobile-bridged tools incl. `get_current_state`)
- `services/onboarding/src/onboarding/services/tools.py:26-148` — `FUNCTION_DECLS` list (7 declarations incl. `get_current_state` at lines 115-132)
- `services/onboarding/src/onboarding/services/tools.py:149-161` — `ToolDispatcher.dispatch` (thin proxy to MobileBridge)
- `services/onboarding/src/onboarding/services/prompt_builder.py:28-47` — `_bootstrap_state_json` (header-only when flag on)
- `services/onboarding/src/onboarding/services/gemini_live.py:141` — `SlidingWindow(target_tokens=4000)` Layer 3 compression
- `services/onboarding/src/onboarding/models/turn_payload.py:1-78` — canonical `TurnPayload` shape
- `services/onboarding/src/onboarding/prompts/onboarding_system.md` §1, §1a, §1b, §6, §8 — agent prompt rules

### Hard rules to honour
- `SENA_AI/.claude/rules/gemini.md` — Gemini Live API rules (deprecated patterns, model id, VAD)
- `SENA_AI/.claude/rules/service-onboarding.md` — service architecture, WS event list, env vars
