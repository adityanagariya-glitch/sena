# ruff: noqa
"""Lazy prompt fragments for the staff case-note voice flow.

Rules here are NOT baked into the always-on system prompt. Each loads into the
live session the moment its trigger field appears on screen (see
shared/.../voice/prompt_fragments.py), then the agent has the full rule exactly
when it's relevant. The system prompt carries only a one-line pointer meanwhile.

SAFETY: only genuinely-conditional, low-risk rules belong here. The
``anyIncident`` confirmation gate and the mandatory document-upload reminder stay
baked into staff_case_note.py — they are compliance/safety rules with a high
cost of misfiring, so they must be present every turn.
"""

from __future__ import annotations

from sena_common.voice.prompt_fragments import (
    FragmentRegistry,
    PromptFragment,
    field_present,
)

# Injury details — only reachable once the worker confirms an injury, at which
# point Flutter reveals the `injuryDetails` child field. Triggering on that
# field appearing is value-free and faithful (the child renders only when the
# parent `anyInjuries` toggle is true).
_INJURY_DETAILS = PromptFragment(
    key="case_review.injuryDetails",
    pointer="injuryDetails: how to record injury specifics — loads if an injury is reported.",
    text=(
        "INJURY DETAILS (`safetyAndHealth.injuryDetails`)\n"
        "The worker has confirmed an injury, so the `injuryDetails` field is now "
        "on screen (textarea, 5-500 chars). Ask for it straight away — e.g. "
        '"Can you walk me through what happened with the injury?" — then call '
        'update_field(section="safetyAndHealth", field="injuryDetails", '
        "value=<their account>). Keep it factual and concise."
    ),
    triggers_on=field_present("safetyAndHealth.injuryDetails"),
)

CASE_NOTE_FRAGMENTS = FragmentRegistry(fragments=[_INJURY_DETAILS])
