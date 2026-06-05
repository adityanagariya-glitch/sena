"""Renders the v2 onboarding system prompt.

Mobile owns schema + validation + state. The builder substitutes 6 simple
placeholders into a fixed template:
  __STEP_LABEL__              — step.label for the persona line
  __VOICE_COVERAGE_SECTION__  — empty or a one-line whitelist
  __GROUNDING_SECTION__       — empty or Google Search blurb
  __MODE_RULES__              — fresh-form vs update-form behaviour fragment
                                 (see prompts/modes/)
  __STEP_RULES__              — per-step behavior fragment (see prompts/steps/)
  __TURN_JSON__               — bootstrap state (header-only when tool state
                                 channel enabled; full TurnPayload when flag off)

Per-step rules live in `prompts/steps/<flow>/{step_id}.md` (grouped by flow —
e.g. steps/client/, steps/staff/). Mode rules live in
`prompts/modes/{fresh,update}.md`. Edit one file per step/mode. Missing file =
empty section. The base template stays free of step- or mode-specific logic.
"""

from __future__ import annotations

from pathlib import Path

from onboarding.core.settings import settings
from onboarding.models.turn_payload import TurnPayload, VisibleField

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_TEMPLATE_PATH = _PROMPTS_DIR / "onboarding_system.md"
_STEPS_DIR = _PROMPTS_DIR / "steps"
_MODES_DIR = _PROMPTS_DIR / "modes"


def _bootstrap_state_json(turn: TurnPayload) -> str:
    """Render the bootstrap state block for the system prompt.

    At session-open we embed the FULL TurnPayload — participant + step +
    bootstrap_mode + visible_fields (with values from mobile's bootstrap
    payload) + next_target. The values are fresh at t=0 by definition
    (mobile sent them milliseconds ago in POST /v1/onboarding/session) so
    staleness does not apply yet.

    Mid-session refresh stays on the tool-reply channel (Option D): every
    function_response carries a fresh `state` payload, which overrides this
    block per system prompt Section 1. This block is the agent's view of
    the form ONLY until the first tool call returns.

    The legacy header-only mode is retained behind the off flag for
    rollback, but is no longer the default behaviour.
    """
    if not settings.onboarding_tool_state_channel:
        return turn.model_dump_json()

    return turn.model_dump_json()


def _voice_coverage_section(voice_coverage: list[str] | None) -> str:
    if not voice_coverage:
        return ""
    paths = ", ".join(voice_coverage)
    return "\n## VOICE COVERAGE\n" f"You may ONLY call update_field for these fields: {paths}.\n"


def _grounding_section(enabled: bool) -> str:
    if not enabled:
        return ""
    return (
        "\n## GROUNDING\n"
        "Google Search is available as a tool. When the participant asks an "
        "NDIS policy question you cannot answer from `visible_fields` or your "
        "training, use Google Search and cite the source briefly.\n"
    )


def _step_rules_section(step_id: str) -> str:
    """Load the `{step_id}.md` step fragment from anywhere under prompts/steps/.

    Step files are grouped into per-flow subfolders (steps/client/, steps/staff/,
    …). step_id is globally unique (e.g. `personal_information` vs
    `staff_personal_information`), so a recursive search resolves to exactly one
    file regardless of which subfolder holds it. New flows add a subfolder; this
    loader needs no change. Missing file → empty section.
    """
    if not step_id:
        return ""
    matches = sorted(_STEPS_DIR.rglob(f"{step_id}.md"))
    if not matches:
        return ""
    body = matches[0].read_text(encoding="utf-8").strip()
    if not body:
        return ""
    return f"\n{body}\n"


def _detect_form_mode(visible_fields: list[VisibleField]) -> str:
    """Classify bootstrap as `fresh` or `update`.

    `update` — any required non-readonly field already has a non-null value
              (mobile sent pre-filled data; agent is editing, not collecting).
    `fresh`  — every required non-readonly field is empty (first-time capture).

    Repeatable rows that exist with values count as updates too — a single
    populated emergency_contacts[0].name flips the whole step to update mode.
    Keeps the model focused on the genuinely-empty fields and removes the long
    "ask first empty field" preamble that derails when the form is already
    largely filled (which is the case for every screen handoff in practice).
    """
    for vf in visible_fields:
        if not vf.required or vf.readonly:
            continue
        if vf.value not in (None, "", [], {}):
            return "update"
    return "fresh"


def _mode_rules_section(mode: str) -> str:
    """Load `prompts/modes/{mode}.md` if present, else empty."""
    fragment_path = _MODES_DIR / f"{mode}.md"
    if not fragment_path.is_file():
        return ""
    body = fragment_path.read_text(encoding="utf-8").strip()
    if not body:
        return ""
    return f"\n{body}\n"


def build_system_prompt(
    turn: TurnPayload,
    *,
    grounding_enabled: bool = False,
    voice_coverage: list[str] | None = None,
) -> str:
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    mode = _detect_form_mode(turn.visible_fields)
    return (
        template.replace("__STEP_LABEL__", turn.step.label)
        .replace("__VOICE_COVERAGE_SECTION__", _voice_coverage_section(voice_coverage))
        .replace("__GROUNDING_SECTION__", _grounding_section(grounding_enabled))
        .replace("__MODE_RULES__", _mode_rules_section(mode))
        .replace("__STEP_RULES__", _step_rules_section(turn.step.id))
        .replace("__TURN_JSON__", _bootstrap_state_json(turn))
    )
