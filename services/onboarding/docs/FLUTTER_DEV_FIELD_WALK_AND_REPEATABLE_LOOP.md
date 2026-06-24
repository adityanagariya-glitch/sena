# Flutter handoff — voice flow: walk every field in order + repeatable "add another" loop

**Date:** 2026-06-24
**Status:** Backend prompt fix SHIPPED (`onboarding_system.md`); this doc covers the
**Flutter `next_target` change** that makes the fix robust at the authority layer.
**Audience:** sena-mobile onboarding voice team.

---

## The two bugs (reported on every screen / flow)

1. **Optional fields are skipped.** The voice assistant almost never asks optional
   fields. When the user explicitly asks to fill optionals, it fills **one**, then
   immediately asks *"are we ready to submit?"* again — it does not continue
   through the remaining fields.
2. **Repeatable sections don't loop.** On NDIS Goals (and any repeatable), after
   capturing the **first** row the assistant does not ask *"add another?"* — even
   though the per-step prompt says it must.

## Root cause — the phone is the sequencing authority

This service runs the **Option-D mobile-authoritative** model. The agent's next
question is driven by `state.next_target`, which **the Flutter client computes**
and returns in every `tool_response`. The backend just relays it
(`services/onboarding/voice/mobile_bridge.py:105`).

The phone currently computes `next_target` from **required fields only**:
- Once every `required` field has a value, the phone sends **`next_target: null`**.
- The agent reads `null` → goes straight to *"shall we submit?"*. Optionals
  (which never flip required-completion) are never surfaced → **bug 1**.
- After a repeatable row satisfies the section `min`, the phone points
  `next_target` at the next **required** field *outside* the section → the agent
  obeys it and leaves the section → **bug 2**.

`recompute_completion` confirms completion ignores optionals
(`form_state.py:54`: `required_filled >= required_total`).

## What the BACKEND already changed (shipped)

`services/onboarding/prompts/onboarding_system.md` now makes the agent **self-drive**
from `visible_fields` (which already carries the full field set + values every turn
— `mobile_bridge.py:97,120-124`):

- Walks **every** empty field in `visible_fields` schema order — **required AND
  optional** — offering each optional once (skippable), never jumping to submit
  just because required is done.
- After saving a **repeatable** row, **always** asks "add another?" before moving
  on — including after the first row — until the user declines or `max` is hit.
- `next_target` is now treated as a **hint** (forced/unlock + user-requested
  jumps), not a licence to skip earlier empty fields or to submit.
- Offers submit only once every field has been offered, or the user explicitly
  says submit / skip the rest.

This means the agent will drive correct behaviour **even if `next_target` stays
null**. But the phone's UI focus can then diverge from what the agent is asking
(the agent asks an optional the phone hasn't "focused"). The Flutter change below
realigns them.

## What FLUTTER should change (to align `next_target` with the new walk)

> These are **not** strictly required for the agent to ask optionals (the prompt
> now drives that), but they keep the on-screen focus in sync with the agent and
> make the contract correct rather than relying on the prompt to compensate.

### 1. `next_target` must be optional-aware
Compute `next_target` as **the first empty field in schema order — required OR
optional** — not just required. Emit `next_target: null` **only** when *every*
field (required and optional) has a value.

```
// before: next_target = first empty REQUIRED field, else null
// after:  next_target = first empty field (required OR optional) in schema order,
//         else null (only when ALL fields, incl. optionals, are filled)
```

### 2. `next_target` must be repeatable-sticky
After a row is added to a repeatable section and its `min` is satisfied, do **not**
immediately move `next_target` out of the section. Either:
- keep `next_target` `null`/within the section until the user declines another row
  (let the agent's "add another?" prompt drive the loop), **or**
- point `next_target` at the new row's first empty field if the user added one.

Do not jump `next_target` to the next required field outside the section while the
user might still add rows — that is exactly what suppresses the "add another?"
prompt today.

### 3. `visible_fields` must stay complete (already true — please keep)
Every turn, `state.visible_fields[]` must list **all** currently-visible fields
(required + optional, with `value`, `required`, `readonly`, and `path`), in schema
order. The agent's walk depends on this. (Conditional `visible_if` fields that are
hidden should remain absent — that is correct.)

### 4. Keep ACKing the tool bridge
Unchanged: every `tool_request` (update_field / add_row / submit_step / …) must be
answered with a `tool_response` carrying the updated `state` (the `{ok, ...}` +
fresh `visible_fields` + `next_target`).

## Contract reference (unchanged ids/shape)

- `state.visible_fields[].path` — `"<section>.<field>"` or `"<section>[<n>].<field>"`
- `state.visible_fields[].required` / `.value` / `.readonly`
- `state.next_target.path` — the field the agent should ask next (now optional-aware)
- Tools the agent uses: `update_field(section, field, value, repeatable_index?)`,
  `add_row(section)`, `delete_row(section, row_index?)`, `submit_step(...)`.

## Acceptance (how to confirm the fix end-to-end)

1. Fill all **required** fields, leave an optional empty → the assistant should ask
   the optional (not "shall we submit?").
2. Decline the optional → the assistant moves to the **next** empty field in order,
   not to submit.
3. On NDIS Goals, after the first goal the assistant asks *"add another goal?"*;
   it keeps looping until you decline or hit `max` (10).
4. Ask for a specific field mid-flow → it jumps there, fills it, then **resumes**
   the in-order walk.
5. Submit is only offered after every field has been offered (or you say submit).
