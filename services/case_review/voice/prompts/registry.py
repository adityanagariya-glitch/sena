# ruff: noqa
"""Auto-generated prompt registry. Loud lookups replace silent file misses.

TEMPLATE: the base system prompt.  STEPS: step_id -> rules text.
MODES: mode -> rules text.  Missing key -> KeyError at call site (by design).
"""
from __future__ import annotations

from .case_note_system import TEMPLATE as TEMPLATE
from .steps.staff_case_note import PROMPT as _step_staff_case_note
from .modes.fresh import PROMPT as _mode_fresh
from .modes.update import PROMPT as _mode_update

STEPS: dict[str, str] = {
    'staff_case_note': _step_staff_case_note,
}

MODES: dict[str, str] = {
    'fresh': _mode_fresh,
    'update': _mode_update,
}

