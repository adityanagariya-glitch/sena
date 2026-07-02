# ruff: noqa
"""NDIS Plan Details (Step 3) — voice prompt.

Plan-manager fields shown only while actually visible; goals/schedule
walk-throughs injected only while those repeatable sections are incomplete.
"""
from __future__ import annotations

from onboarding.prompts._section_utils import has_incomplete_rows
from onboarding.voice.turn_payload import VisibleField

_FIELD_TABLES = r"""## Step-specific rules — NDIS Plan Details (Step 3)

This step has 5 sections: `plan_info` (identification + dates + plan
management with conditional fields), `ndis_goals` (repeatable),
`support_coordinator` (READONLY), `fund_allocations` (optional money inputs),
`support_schedule` (repeatable with nested time slots). Use these exact
section ids and field ids for `update_field`.

### Section: `plan_info` — identification & dates

| field id | type | required | validation |
|---|---|---|---|
| `ndis_number` | text (digits) | yes | exactly 9 digits |
| `plan_start_date` | date | yes | ISO `YYYY-MM-DD` |
| `plan_end_date` | date | yes | ISO `YYYY-MM-DD`; **strictly after** `plan_start_date` |

### Section: `plan_info` — plan management (enum)

| field id | type | required | enum values (wire — use EXACTLY) | display label |
|---|---|---|---|---|
| `plan_management` | enum | yes | `SELF_MANAGED`, `PLAN_MANAGED`, `NDIA_MANAGED`, `PLAN_NOMINEE_MANAGED` | Self Managed, Plan Managed, NDIA Managed, Plan Nominee Managed |

Default: `PLAN_MANAGED`.

### Section: `ndis_goals` (repeatable, min 1, max 10)

| field id (per row) | type | required | validation |
|---|---|---|---|
| `goal_text` | textarea | yes | required |

### Section: `support_coordinator` (READONLY)

| field id | type | readonly |
|---|---|---|
| `name` | text | **yes** |
| `email` | email | **yes** |

Server-prefilled. If the participant asks to change either, say:
*"That one's locked to your account — I can't change it from here."*

### Section: `fund_allocations` (all 3 optional)

If provided, must parse as positive number, integer part ≤9 digits.

| field id | type | required | validation |
|---|---|---|---|
| `daily_living` | number | no | positive double, integer part ≤9 digits |
| `social_community` | number | no | positive double, integer part ≤9 digits |
| `support_coordination` | number | no | positive double, integer part ≤9 digits |

### Section: `support_schedule` (repeatable, min 1, max 5)

This row has 6 fields. **`support_purpose`, `support_category`, and
`support_item` are SCREEN-ONLY — explain them, never voice-fill them**
(confirmed 2026-07-01: mobile sends no state echo after these are selected,
so voice-fill would go stale). `description`, `frequency`, and
`preferred_schedule` remain voice-fillable.

| field id (per row) | type | required | voice-fillable? |
|---|---|---|---|
| `support_purpose` | text/enum | yes | **NO — screen only** |
| `support_category` | text/enum | yes | **NO — screen only** |
| `support_item` | text/enum | yes | **NO — screen only** |
| `description` | textarea | no | yes (if filled: min 5, max 255 chars) |
| `frequency` | enum | yes | yes — fixed list below |
| `preferred_schedule` | string | yes | yes — DSL, see block below |

#### HARD RULE — never call `update_field` for support_purpose / support_category / support_item

These three form a live cascading NDIS-catalog lookup (purpose → category →
item, each filtered by the one before it) that only the mobile app's own
picker can resolve — the catalog loads dynamically and voice-set values here
can go stale against what the participant sees on screen. Do NOT call
`update_field` on any of `support_purpose`, `support_category`, or
`support_item`, even if the participant tells you their answer.

Explain what each one is if asked (Purpose = why they need the support,
Category = the NDIS budget category it falls under, Item = the specific
support line item) and why Category/Item stay locked until the field above is
picked. If they ask what's on screen, read the live options from
`visible_fields[...].enum_values` — a **non-empty list** is real options to
read verbatim; **null** means the catalog hasn't loaded yet or the upstream
hasn't been chosen (say so honestly, do NOT list options from memory); an
**empty list `[]`** means the upstream cascade was just cleared. Then direct
them to pick each one on screen:

> "This bit's a live NDIS catalog lookup, so I'll need you to tap through it
> on screen — pick your Support Purpose first, then Category and Item unlock
> one at a time. I'm right here if anything's unclear."

#### `frequency` — the ONE fixed enum on this row (voice-fillable)

Wire values (use EXACTLY) → display labels:

- `AS_REQUIRED` → "As Required"
- `DAILY` → "Daily"
- `WEEKLY` → "Weekly"
- `FORTNIGHTLY` → "Fortnightly"
- `MONTHLY` → "Monthly"
- `ONCE_OFF` → "Once-off"

Default new row: `{frequency: AS_REQUIRED}`.

Match the participant's spoken value against these 6 fixed labels. Exact
match → call `update_field`. Close but not exact → repeat the closest 2-3
labels back and ask "did you mean X or Y?" — never auto-correct. No match →
say *"I'm not seeing that one — the options are [read them]. Which one would
you like?"*

#### `preferred_schedule` — VOICE-MUTABLE (set days + times by voice)

You CAN set the schedule by voice — do NOT tell the participant to use the
screen. Call `update_field` with `field="preferred_schedule"`,
`repeatable_index=<row>`, and `value` as a STRING in this exact format:

```
"<DAY>[, <DAY>...] <START>-<END>[; <DAY> <START>-<END>...]"
```

- Days sharing the SAME time range are comma-joined; different time ranges are
  separated by a semicolon `;`.
- Times are 24-hour `HH:mm`. `END` must be strictly after `START`.
- Days: `Mon Tue Wed Thu Fri Sat Sun` (or `MO TU WE TH FR SA SU`).

Examples (the value is a plain string, NOT JSON):
```
update_field(section="support_schedule", field="preferred_schedule",
  repeatable_index=0, value="Mon 09:00-18:00")

update_field(section="support_schedule", field="preferred_schedule",
  repeatable_index=0, value="Mon, Wed, Sat 18:25-22:25")

update_field(section="support_schedule", field="preferred_schedule",
  repeatable_index=0, value="Mon 22:00-22:30; Wed 09:00-12:00; Sat 06:00-09:00")
```

Rules:
- This call REPLACES the whole schedule for that row — always send the FULL
  desired set of days+times, not a delta. To change one day's time, resend
  every day with the new time included.
- At least one day with one time range is required per support item.

#### Overlap check — MANDATORY before emitting

Before calling `update_field` for `preferred_schedule`, parse your intended
final string into a `{day → [(start, end), ...]}` map and verify no two
ranges on the SAME day overlap. Two ranges overlap when
`max(start_a, start_b) < min(end_a, end_b)`.

If overlap is detected, DO NOT send `update_field`. Instead say:
*"That would overlap your existing slot on {DAY} from {EXISTING_START} to
{EXISTING_END}. The new slot has to start at {EXISTING_END} or later — what
works?"*

Examples of REJECTIONS (do not send these):
- Existing: `Mon 10:00-22:00`. User adds: `Mon 16:00-23:00`. → overlap
  16:00-22:00 → refuse.
- Existing: `Tue 09:00-12:00; Tue 14:00-17:00`. User adds: `Tue 11:00-15:00`.
  → overlaps BOTH existing ranges → refuse.

Touching ranges are OK: `Mon 10:00-13:00; Mon 13:00-16:00` is valid (no
overlap; end == start).

Capture flow: ask which days and the start+end time for each. Convert spoken
times to 24-hour `HH:mm` ("9am"→`09:00`, "half past 2 in the
afternoon"→`14:30`, "10:25 pm"→`22:25`). Build the single string, run the
overlap check above, then make ONE `update_field` call.

### Cross-field rules to enforce

- `plan_end_date > plan_start_date` (strict).
- Plan manager fields exist ONLY when `plan_management == PLAN_MANAGED`.
- Each `support_schedule` row must have ≥1 time slot in `preferred_schedule`.
- Same-day time slots for the same support item MUST NOT overlap."""

_PLAN_MANAGER_FIELDS = r"""#### Conditional fields — visible ONLY when `plan_management == PLAN_MANAGED`

If `plan_management` is anything else, these fields DO NOT exist for this
turn — do NOT ask for them.

| field id | type | required (when visible) | validation |
|---|---|---|---|
| `plan_manager_name` | text | yes | letters and spaces only; min 3, max 25 chars |
| `plan_manager_contact_email` | email | yes | valid email; max 50 chars |
| `plan_manager_billing_email` | email | yes | valid email; max 50 chars |"""

_GOALS_WALKTHROUGH = r"""### Walk-through — new ndis_goals row

After `add_row` returns `{ok:true, index:N}`, ask for `goal_text` and call
`update_field` with `repeatable_index=N`. The first row (index 0) is
pre-populated in the form — you will NOT call `add_row` for it."""

_SCHEDULE_CASCADE_GUIDANCE = r"""### Walk-through order for a new support_schedule row

After `add_row(section="support_schedule")`, in this order:

1. Direct the participant to pick `support_purpose` on screen (see the HARD
   RULE above — do not voice-fill it).
2. Direct them to pick `support_category` on screen once it unlocks.
3. Direct them to pick `support_item` on screen once it unlocks.
4. `frequency` — read all 6 fixed options verbatim and voice-fill it.
5. At least one day + time slot for `preferred_schedule` — voice-fill it.
6. Optional `description` — voice-fill it."""


def build(visible_fields: list[VisibleField]) -> str:
    parts = [_FIELD_TABLES]

    if any(f.path.startswith("plan_info.plan_manager") for f in visible_fields):
        parts.append(_PLAN_MANAGER_FIELDS)

    if has_incomplete_rows("ndis_goals", 1, visible_fields):
        parts.append(_GOALS_WALKTHROUGH)

    if has_incomplete_rows("support_schedule", 1, visible_fields):
        parts.append(_SCHEDULE_CASCADE_GUIDANCE)

    return "\n\n".join(parts)


PROMPT = build
