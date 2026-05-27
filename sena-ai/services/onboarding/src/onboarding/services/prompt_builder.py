"""Renders the v2 onboarding system prompt.

Mobile owns schema + validation + state. The builder substitutes 5 simple
placeholders into a fixed template:
  __STEP_LABEL__              — step.label for the persona line
  __VOICE_COVERAGE_SECTION__  — empty or a one-line whitelist
  __GROUNDING_SECTION__       — empty or Google Search blurb
  __STEP_RULES__              — per-step behavior fragment (see prompts/steps/)
  __TURN_JSON__               — bootstrap state (header-only when tool state
                                 channel enabled; full TurnPayload when flag off)

Per-step rules live in `prompts/steps/{step_id}.md`. Edit one file per step.
Missing file = empty section (no step-specific rules). The base template stays
free of step-specific logic.
"""

from __future__ import annotations

import json
from pathlib import Path

from onboarding.core.settings import settings
from onboarding.models.turn_payload import TurnPayload

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_TEMPLATE_PATH = _PROMPTS_DIR / "onboarding_system.md"
_STEPS_DIR = _PROMPTS_DIR / "steps"


def _bootstrap_state_json(turn: TurnPayload) -> str:
    """Render the bootstrap state block for the system prompt.

    When the tool state channel is enabled (Option D — default), the
    bootstrap is HEADER-ONLY: participant + step + next_target +
    bootstrap_mode. No visible_fields data, since those go stale immediately
    and cause hallucinations (see ISSUE_AND_SOLUTION.md §3). The model's
    source of truth becomes the most recent function_response.state field,
    populated by Flutter.

    When the feature flag is off, falls back to the full TurnPayload JSON
    for rollback safety (legacy hallucination-prone behaviour).
    """
    if not settings.onboarding_tool_state_channel:
        return turn.model_dump_json()

    bootstrap = turn.model_dump(
        mode="json",
        include={"participant", "step", "next_target", "bootstrap_mode"},
    )
    return json.dumps(bootstrap)


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
    """Load `prompts/steps/{step_id}.md` if present, else empty."""
    if not step_id:
        return ""
    fragment_path = _STEPS_DIR / f"{step_id}.md"
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
    return (
        template.replace("__STEP_LABEL__", turn.step.label)
        .replace("__VOICE_COVERAGE_SECTION__", _voice_coverage_section(voice_coverage))
        .replace("__GROUNDING_SECTION__", _grounding_section(grounding_enabled))
        .replace("__STEP_RULES__", _step_rules_section(turn.step.id))
        .replace("__TURN_JSON__", _bootstrap_state_json(turn))
    )
