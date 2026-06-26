# ruff: noqa
"""Medical (Step 5) — voice prompt.

Repeatable-section walk-throughs injected only while rows are incomplete;
enum voice-to-wire mappings injected while mobility_status is unfilled.
"""
from __future__ import annotations

from onboarding.prompts._section_utils import step
from onboarding.voice.turn_payload import VisibleField

_FIELD_TABLES = r"""## Step-specific rules — Medical (Step 5)

This step has 6 sections: `medical_overview`, `mobility`, `allergies`
(repeatable), `medications` (repeatable), `medical_history` (repeatable,
optional). Use these exact section ids, field ids, and enum values for
`update_field`. Live values are in `<state>`.

### Section: `medical_overview`

| field id | type | required | enum values (use EXACTLY) | validation |
|---|---|---|---|---|
| `primary_diagnosis` | textarea | yes | — | max 250 chars |
| `secondary_diagnosis` | textarea | no | — | if filled: min 5, max 250 chars |
| `blood_type` | enum | no | `A+`, `A-`, `B+`, `B-`, `AB+`, `AB-`, `O+`, `O-` | — |
| `primary_doctor_name` | text | yes | — | max 50 chars |
| `doctor_phone` | phone | no | — | Australian mobile if filled |
| `last_medical_checkup` | date | no | — | ISO `YYYY-MM-DD`; today − 10 years … today |

Blood type display: read aloud as "A positive", "A negative", "AB positive"
etc. ALWAYS send the medical notation (`A+`, `A-`, `AB+`, etc) via
`update_field`.

### Section: `mobility`

| field id | type | required | enum values (use EXACTLY) | validation |
|---|---|---|---|---|
| `mobility_status` | enum | yes | `Independent`, `Uses Walking Aid`, `Wheelchair User`, `Bed Bound`, `Requires Assistance` | required |
| `support_requirements` | textarea | yes | — | required, max 250 chars |

### Section: `allergies` (repeatable, min 1, max 10)

Each row is all-or-none. Empty rows stripped before save.

| field id (per row) | type | required | validation |
|---|---|---|---|
| `title` | text | yes | required, max 25 chars |
| `description` | textarea | yes | required, min 5, max 250 chars |

### Section: `medications` (repeatable, min 1, max 10)

ALL fields required per row (no all-or-none).

| field id (per row) | type | required | validation |
|---|---|---|---|
| `medication_name` | text | yes | required, max 50 chars |
| `dosage` | text | yes | required, max 50 chars |
| `frequency` | text | yes | required, max 50 chars |
| `purpose` | textarea | yes | required, min 5, max 100 chars |
| `notes` | text | no | if filled: min 5, max 100 chars |

### Section: `medical_history` (repeatable, min 0, max 10 — title-gated optional)

Row active when `title` is non-empty; blank title → whole row stripped on save.

| field id (per row) | type | required (when active) | validation |
|---|---|---|---|
| `title` | text | yes | max 25 chars |
| `year` | year | yes | integer 1900 … current year |
| `description` | textarea | yes | min 5, max 100 chars |"""

_ALLERGY_WALKTHROUGH = r"""### Walk-through — allergies row

After `add_row(section="allergies")` → `{ok:true, index:N}`:
1. `title` → `update_field(section="allergies", field="title", repeatable_index=N, value=...)`
2. `description` → `update_field(section="allergies", field="description", repeatable_index=N, value=...)`

Only after BOTH saved may you ask *"Want to add another allergy, or shall we move on?"*"""

_MEDICATION_WALKTHROUGH = r"""### Walk-through — medications row

After `add_row(section="medications")` → `{ok:true, index:N}`, collect in order:
1. `medication_name`
2. `dosage`
3. `frequency`
4. `purpose`
5. `notes` (optional — offer once; if declined, move on)

Save each with `update_field(..., repeatable_index=N)`. Only after all required fields saved may you ask *"Want to add another medication, or shall we move on?"*"""

_HISTORY_WALKTHROUGH = r"""### Walk-through — medical_history row (title-gated)

After `add_row(section="medical_history")` → `{ok:true, index:N}`:
1. `title` — if left blank, the whole row is stripped on save
2. `year` — integer 1900 … current year
3. `description`

Save each with `update_field(..., repeatable_index=N)`. Only after all three saved may you ask *"Want to add another history entry, or shall we move on?"*"""

_ENUM_EXAMPLES = r"""### Enum — voice-to-wire mappings

- `blood_type`: read aloud as "A positive", "B negative", "AB positive" etc. Send medical notation: `A+`, `A-`, `B+`, `B-`, `AB+`, `AB-`, `O+`, `O-`.
- `mobility_status`: "Walks with cane" → `Uses Walking Aid`; "Bedridden" → `Bed Bound`; "Needs help" → `Requires Assistance`."""


@step(
    always=[_FIELD_TABLES],
    if_incomplete=[
        ("allergies", 1, _ALLERGY_WALKTHROUGH),
        ("medications", 1, _MEDICATION_WALKTHROUGH),
        ("medical_history", 0, _HISTORY_WALKTHROUGH),
    ],
    if_unfilled=(["mobility.mobility_status"], _ENUM_EXAMPLES),
)
def build(visible_fields: list[VisibleField]) -> str: ...


PROMPT = build
