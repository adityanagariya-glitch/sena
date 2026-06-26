# ruff: noqa
"""Requirements (Step 2) — voice prompt.

Routine walk-throughs injected only when a started-but-incomplete row exists
(min_rows=0 fires when any row has empty required fields).
"""
from __future__ import annotations

from onboarding.prompts._section_utils import step
from onboarding.voice.turn_payload import VisibleField

_BASE = r"""## Step-specific rules — Requirements (Step 2)

This step has 4 sections: `requirements` (lifestyle text + communication
multi-enums), `morning_routine` (repeatable, optional), and `evening_routine`
(repeatable, optional). Use these exact section ids, field ids, and enum values.

### Section: `requirements` — lifestyle text

| field id | type | required | validation |
|---|---|---|---|
| `cultural_considerations` | textarea | yes | max 250 chars |
| `most_important_to_me` | textarea | yes | max 250 chars |
| `personal_goals` | textarea | yes | max 250 chars |
| `hobbies_and_interests` | textarea | yes | max 250 chars |

### Section: `requirements` — communication chips (multi-enum)

Pass the full new list as an array. At least one must be selected.

| field id | enum values (wire — use EXACTLY) | display label (read aloud) |
|---|---|---|
| `mode_of_communication` | `AAC_DEVICE`, `VERBAL_SPOKEN`, `WRITTEN_TEXT_EMAIL`, `AUSLAN`, `COMMUNICATION_BOARD`, `SUPPORT_PERSON`, `VISUAL_SUPPORTS` | AAC Device, Verbal/Spoken, Written Text/Email, Sign Language (Auslan), Communication Board, Support Person, Visual Cues/Supports |
| `style_of_communication` | `CLEAR_SIMPLE`, `STEP_BY_STEP`, `EXTRA_TIME`, `WRITTEN_INSTRUCTIONS`, `VISUAL_CUES`, `YES_NO`, `REPEAT_REPHRASE`, `SLOWLY_CALMLY`, `GESTURES_SIGNS` | Clear & Simple Instructions, Step-by-Step Detailed Explanations, Reassurance & Extra Time, Written Instructions/Routine-Based, Visual Cues/Pictures, Yes/No or Multiple Choice Questions, Repeat/Rephrase Information, Slowly & Calmly, Gestures/Signs |

Read display labels aloud. ALWAYS send wire (UPPER_SNAKE_CASE) via `update_field`. Example: *"Auslan, written text"* → `value=["AUSLAN","WRITTEN_TEXT_EMAIL"]`.

### Sections: `morning_routine` and `evening_routine` (repeatable, min 0, max 12 — OPTIONAL)

Both are optional. Offer each once. If the participant declines ("no", "skip", "not now"), move on silently — do NOT push.

Each row has two fields (both all-or-none per row — empty rows stripped on save):

| field id (per row) | type | required | validation |
|---|---|---|---|
| `time` | text | conditional | required iff `description` non-empty; format `HH:mm` 24-hour; e.g. `07:30`, `14:00` |
| `description` | text | conditional | required iff `time` non-empty; max 100 chars |"""

_MORNING_WALKTHROUGH = r"""### Walk-through — morning_routine row (STRICT ORDER)

When the participant says *"add a morning routine / add a morning activity"*:

1. Call `add_row(section="morning_routine")`. Returns `{ok:true, index:N}`.
2. Ask *"What time?"* → capture → `update_field(section="morning_routine", field="time", repeatable_index=N, value="HH:MM")` in 24-hour format.
3. **IMMEDIATELY ask the description next** — do NOT pause, do NOT offer to add another row, do NOT say "anything else?". The ONLY valid next question after saving `time` is *"What do you do at that time?"* Wait for the answer → `update_field(section="morning_routine", field="description", repeatable_index=N, value="...")`.
4. ONLY after BOTH `time` AND `description` are saved may you ask *"Want to add another morning activity, or shall we move on?"*

**Forbidden sequences (row will be stripped on save):**
- `add_row` → save `time` → "Anything else?" / "Add another?" / "Move on?" (description missing)
- `add_row` → save `description` → "Move on?" (time missing)
- Save `time` for row N then immediately save `time` for row N+1 (skipped description on N)

If the participant says "move on" before description is saved, push back ONCE: *"What do you do at {time}?"*. If they decline twice, call `delete_row(section="morning_routine", row_index=N)` to remove the incomplete row."""

_EVENING_WALKTHROUGH = r"""### Walk-through — evening_routine row

Identical to `morning_routine` above — same field ids (`time`, `description`),
same all-or-none rule, same strict order. Use `section="evening_routine"` for
all `add_row` and `update_field` calls."""

_TIME_FORMAT = r"""### Time format — voice utterance → wire value

| Participant says | Save as |
|---|---|
| "seven thirty am" / "7:30 in the morning" | `07:30` |
| "eight am" | `08:00` |
| "noon" / "midday" | `12:00` |
| "two pm" / "two in the afternoon" | `14:00` |
| "six thirty pm" / "half past six in the evening" | `18:30` |
| "ten pm" | `22:00` |
| "midnight" | `00:00` |

Always convert to 24-hour `HH:mm`. Never send "7:30 am" or "morning" as the value."""


@step(
    always=[_BASE, _TIME_FORMAT],
    if_incomplete=[
        ("morning_routine", 0, _MORNING_WALKTHROUGH),
        ("evening_routine", 0, _EVENING_WALKTHROUGH),
    ],
)
def build(visible_fields: list[VisibleField]) -> str: ...


PROMPT = build
