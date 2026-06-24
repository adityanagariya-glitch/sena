## Step-specific rules — Medical (Step 5)

This step has 6 sections: `medical_overview`, `mobility`, `allergies`
(repeatable), `medications` (repeatable), `medical_history` (repeatable,
optional). Use these exact section ids, field ids, and enum values for
`update_field`. Live values are in `<state>`.

### Section: `medical_overview`

| field id | type | required | enum values (use EXACTLY) | validation |
|---|---|---|---|---|
| `primary_diagnosis` | textarea | yes | — | required, max 250 chars |
| `secondary_diagnosis` | textarea | no | — | if filled: min 5, max 250 chars |
| `blood_type` | enum | no | `A+`, `A-`, `B+`, `B-`, `AB+`, `AB-`, `O+`, `O-` | — |
| `primary_doctor_name` | text | yes | — | required, max 50 chars |
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

### Section: `medical_history` (repeatable, min 1, max 10 — title-gated)

Row is all-or-none gated by `title`: if title is empty, the entire row is
stripped on save. Otherwise all three fields are required.

| field id (per row) | type | required (when row active) | validation |
|---|---|---|---|
| `title` | text | yes | required, max 25 chars |
| `year` | year | yes | integer 1900 … current year |
| `description` | textarea | yes | required, min 5, max 100 chars |

### Walk-through order for repeatable rows

After `add_row(section)` returns `{ok:true, index:N}`, ask for fields IN
ORDER and call `update_field` after each capture:

- **allergies**: title → description
- **medications**: medication_name → dosage → frequency → purpose → (notes optional)
- **medical_history**: title → year → description

Only after all required fields on the row are saved may you ask
*"Want to add another, or are we good to move on?"*

### Enum strictness — read the list verbatim

When a field has `enum_values` above, the ONLY valid values are those
listed — letter-for-letter. Do NOT translate, paraphrase, or substitute:

- `blood_type`: only `A+`, `A-`, `B+`, `B-`, `AB+`, `AB-`, `O+`, `O-`.
- `mobility_status`: only `Independent`, `Uses Walking Aid`, `Wheelchair User`, `Bed Bound`, `Requires Assistance`. ("Walks with cane" → `Uses Walking Aid`; "Bedridden" → `Bed Bound`; "Needs help" → `Requires Assistance`.)

If the participant says something not in the list, ask them to pick one of
the listed options. Read the FULL list of options — do NOT abbreviate.

### Submission and progression — sequential only

When the participant says *"save", "submit", "next", "done", "I'm done",
"that's everything", "ready to move on", "move on", "continue"*, your
VERY NEXT ACTION is `submit_step(confirmation_transcript=<exact words>)`.

Do NOT offer a menu of upcoming steps. The app navigates automatically.

- On `{ok: true}`: warm brief line, e.g. *"Sorted! Taking you to the next step."* / *"Beauty — all saved, moving you on!"*
- On `{ok: false, blockers}`: speak first blocker's `reason` verbatim.
