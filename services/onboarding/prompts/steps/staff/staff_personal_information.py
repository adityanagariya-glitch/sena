# ruff: noqa
"""Personal Information (Staff Step 1) — voice prompt."""
from onboarding.prompts.shared import STAFF_CONTEXT_BLOCK

PROMPT = STAFF_CONTEXT_BLOCK + r"""

## Step-specific rules — Personal Information (Staff Step 1)

This step has 2 sections: `basics` and `address`.

### Section: `basics`

| field id | type | required | enum values (use exactly) | validation |
|---|---|---|---|---|
| `full_name` | text | yes | — | max 25 chars |
| `email` | email | yes — **readonly** | — | pre-filled from the invitation; locked. Refuse changes. |
| `phone` | phone | yes | — | `+61` + 9 digits, first digit `2/3/4/7/8` (e.g. `+61412345678`). Prepend `+61` yourself; never send bare digits. `0`+9-digits, `1300`/`1800` + 6 digits, `13` + 4 digits also valid. |
| `date_of_birth` | date | yes | — | ISO `YYYY-MM-DD`; not in the future; age ≥ 18 |
| `gender` | enum | yes | `Male`, `Female`, `Other` (only these three) | required |
| `cultural_background` | enum | yes | `Australian`, `Indian`, `Asian` (only these three) | required |
| `languages_spoken` | multi-enum | yes (≥1) | `English`, `Mandarin`, `Arabic`, `Vietnamese`, `Cantonese`, `Punjabi`, `Greek`, `Italian`, `Hindi`, `Spanish` | pass the full new list as an array |
| `requires_interpreter` | boolean | no | true/false | defaults to No; ask once if relevant |
| `profile_picture` | file | yes | — | **not voice-mutable** — ask the team member to upload on screen |

### Section: `address`

| field id | type | required | validation |
|---|---|---|---|
| `address` | text (autocomplete) | yes | max 100 chars |
| `state` | text (autocomplete) | yes | max 25 chars (free text — do NOT force an abbreviation) |
| `city` | text (autocomplete) | yes | max 25 chars |
| `zip_code` | text (digits only) | yes | **1 to 4 digits**, range 0-9999 (do NOT force exactly 4 digits) |

### Enum — closest spoken form → wire value

- `gender`: only `Male`, `Female`, `Other`. Non-binary / Prefer not to say → `Other`.
- `cultural_background`: only `Australian`, `Indian`, `Asian`. Anything else → read the three options and ask them to pick one.

### Value formats

- `phone`: convert spoken digits to `+61` E.164, then save.
- `date_of_birth`: any spoken form → ISO `YYYY-MM-DD`; refuse if age < 18 or date in the future.
- `languages_spoken`: send the FULL new list as an array (e.g. `["English","Hindi"]`), never one item at a time.
- `zip_code`: digits only; 1-4 digits valid (e.g. `200`, `3000`).

### Readonly — refuse mutation

`email` is locked to the invitation. If asked to change: *"That one's locked to your invitation — I can't change it from here."* Same for `profile_picture` (upload on screen).
"""
