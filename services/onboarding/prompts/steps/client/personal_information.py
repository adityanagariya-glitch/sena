# ruff: noqa
"""Personal Details (Step 1) — voice prompt.

Emergency-contacts walk-through injected only when fewer than 1 complete row
exists; enum examples injected only while gender is still unfilled.
"""
from __future__ import annotations

from onboarding.prompts._section_utils import step
from onboarding.voice.turn_payload import VisibleField

_FIELD_TABLES = r"""## Step-specific rules — Personal Details (Step 1)

This step has 4 sections: `basics`, `home_address`, `service_address`
(optional group), and `emergency_contacts` (repeatable). Use these exact
section ids, field ids, and enum values. Live values are in `<state>`.

### Section: `basics`

| field id | type | required | enum values (use exactly) | validation |
|---|---|---|---|---|
| `full_name` | text | yes | — | first + last name, each ≤25 chars |
| `email` | email | yes — **readonly** | — | locked to account; refuse changes |
| `phone` | phone | yes | — | `+61` + 9 digits, first digit `2/3/4/7/8` (e.g. `+61412345678`). Prepend `+61` yourself; never send bare digits. `0`+9-digits / `1300` / `1800` also valid. |
| `date_of_birth` | date | yes | — | ISO `YYYY-MM-DD`; must be ≥18 years ago |
| `gender` | enum | yes | `Male`, `Female`, `Other` | required |
| `about_me` | textarea | yes | — | max 250 chars |
| `preferred_languages` | multi-enum | yes (≥1) | `English`, `Mandarin`, `Cantonese`, `Arabic`, `Vietnamese`, `Greek`, `Italian`, `Other` | pass full new list as array |
| `interpreter_required` | boolean | yes | true/false | — |
| `profile_picture` | file | yes | — | **not voice-mutable** — ask user to upload on screen |

### Section: `home_address`

| field id | type | required | validation |
|---|---|---|---|
| `address` | text | yes | max 100 chars |
| `state` | text | yes | Australian state abbrev. (NSW, VIC, QLD, WA, SA, TAS, ACT, NT) |
| `city` | text | yes | max 25 chars |
| `zip_code` | text | yes | exactly 4 digits |

### Section: `service_address` (optional group)

All four fields individually optional. Fill ANY one and all four become required. Leave all blank to skip — valid.

| field id | type | validation when filled |
|---|---|---|
| `address` | text | max 250 chars |
| `state` | text | Australian state abbrev. |
| `city` | text | max 25 chars |
| `zip_code` | text | exactly 4 digits |

### Section: `emergency_contacts` (repeatable, min 1, max 5)

`add_row(section="emergency_contacts")` → `{ok:true, index:N}`. Always pass `repeatable_index=N`.

| field id | type | required | enum values (use exactly) | validation |
|---|---|---|---|---|
| `name` | text | yes | — | max 25 chars |
| `relation` | enum | yes | `Father`, `Mother`, `Sibling`, `Spouse`, `Friend`, `Guardian`, `Carer`, `Other` | required |
| `email` | email | yes | — | ≠ participant's `basics.email`; unique across rows |
| `phone` | phone | yes | — | `+61` 9 digits; ≠ participant's `basics.phone`; unique across rows |"""

_WALKTHROUGH = r"""### Walk-through — new emergency contact row

After `add_row` returns `{ok:true, index:N}`, collect in order:

1. `name`
2. `relation` — read all 8 options: `Father`, `Mother`, `Sibling`, `Spouse`, `Friend`, `Guardian`, `Carer`, `Other`
3. `email`
4. `phone`

Save each with `update_field(..., repeatable_index=N)`. Only after ALL four are saved may you ask *"Want to add another contact, or are we done?"*"""

_ENUM_EXAMPLES = r"""### Enum — closest spoken form → wire value

- `gender`: only `Male`, `Female`, `Other`. Non-binary / Prefer not to say → `Other`.
- `relation`: "Mum"/"Dad" → `Mother`/`Father`; "Sister"/"Brother" → `Sibling`; "Partner" → `Spouse`; "Support worker" → `Carer`."""

_CROSS_FIELD_RULES = r"""### Cross-field rules

- Emergency-contact email and phone ≠ participant's own (`basics.email`, `basics.phone`) and unique across rows.
- `service_address` group is all-or-none — partial fill rejected at submit.
- `date_of_birth`: refuse if age < 18 or date in the future."""


@step(
    always=[_FIELD_TABLES, _CROSS_FIELD_RULES],
    if_incomplete=[("emergency_contacts", 1, _WALKTHROUGH)],
    if_unfilled=(["basics.gender"], _ENUM_EXAMPLES),
)
def build(visible_fields: list[VisibleField]) -> str: ...


PROMPT = build
