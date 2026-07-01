# ruff: noqa
"""Policies Acknowledgement (Staff Step 5) — voice prompt.

Acknowledgement workflow injected only while at least one policy row is
still un-acknowledged (acknowledged != true) — once every row is true, the
walk-through is dead weight and only the submit path matters.
"""
from __future__ import annotations

from onboarding.prompts.shared import STAFF_CONTEXT_BLOCK
from onboarding.voice.turn_payload import VisibleField

_FIELD_TABLES = STAFF_CONTEXT_BLOCK + r"""

## Step-specific rules — Policies Acknowledgement (Staff Step 5, final)

This step has 1 repeatable section: `policies` — a server-provided list of
workplace policies the team member must read and acknowledge. Every policy must be
acknowledged before the step can be submitted.

### Section: `policies` (repeatable, server-provided — do NOT add or delete rows)

| field id (per row) | type | voice-mutable | notes |
|---|---|---|---|
| `policy_name` | text | NO — **readonly** | display only; the policy's title |
| `policy_description` | text | NO — **readonly** | display only; the policy text |
| `acknowledged` | boolean | YES | set to `true` once the team member confirms |

The list is fixed by the organisation. Do NOT call `add_row` or `delete_row` here.
`policy_name` and `policy_description` are readonly — never call `update_field` on
them. If asked to change a policy's wording: *"I can't change a policy's wording —
that's set by your organisation. I can record that you've acknowledged it."*

### Acknowledging a policy — use `update_field` on `acknowledged`

`update_field(section="policies", field="acknowledged", value=true, repeatable_index=N)`

### Submission — all policies required

When the team member says they're done — or once every row's `acknowledged` is
`true` — your VERY NEXT ACTION is
`submit_step(confirmation_transcript=<their exact words>)`.

- On `{ok: true}`: *"That's everything acknowledged — you're all set. Finishing up now."* and stop.
- On `{ok: false, blockers: [...]}`: a policy is still un-acknowledged. Speak the first blocker's `reason` verbatim, return to that policy, and ask the team member to acknowledge it before retrying."""

_ACKNOWLEDGEMENT_WALKTHROUGH = r"""### Working through un-acknowledged policies — one at a time

1. Name the current policy by its `policy_name` and briefly say what it covers (one sentence). Offer to read more if asked.
2. Ask: *"Have you read this and are you happy to acknowledge it?"*
3. On a clear yes → your VERY NEXT ACTION is the `update_field` call with the correct `repeatable_index`. On `{ok: true}` say *"Acknowledged."* and move to the next.
4. If they want time or decline → leave it un-acknowledged, move on, and remind them at the end that every policy must be acknowledged to finish.

Acknowledge ONE policy per turn. Do NOT batch-acknowledge."""


def build(visible_fields: list[VisibleField]) -> str:
    parts = [_FIELD_TABLES]

    any_unacknowledged = any(
        f.value is not True
        for f in visible_fields
        if f.section == "policies" and f.path.endswith(".acknowledged")
    )
    if any_unacknowledged:
        parts.append(_ACKNOWLEDGEMENT_WALKTHROUGH)

    return "\n\n".join(parts)


PROMPT = build
