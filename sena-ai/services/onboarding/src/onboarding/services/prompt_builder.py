"""Renders the v2 onboarding system prompt.

Mobile owns schema + validation + state. The builder substitutes 4 simple
placeholders into a fixed template:
  __STEP_LABEL__              — step.label for the persona line
  __VOICE_COVERAGE_SECTION__  — empty or a one-line whitelist
  __GROUNDING_SECTION__       — empty or Google Search blurb
  __TURN_JSON__               — the TurnPayload serialised to compact JSON

No business logic. No sequencing. No validation. No state inspection.
"""
from __future__ import annotations

from pathlib import Path

from onboarding.models.turn_payload import TurnPayload

_TEMPLATE_PATH = Path(__file__).parent.parent / "prompts" / "onboarding_system.md"


def _voice_coverage_section(voice_coverage: list[str] | None) -> str:
    if not voice_coverage:
        return ""
    paths = ", ".join(voice_coverage)
    return (
        "\n## VOICE COVERAGE\n"
        f"You may ONLY call propose_field for these fields: {paths}.\n"
    )


def _grounding_section(enabled: bool) -> str:
    if not enabled:
        return ""
    return (
        "\n## GROUNDING\n"
        "Google Search is available as a tool. When the participant asks an "
        "NDIS policy question you cannot answer from `visible_fields` or your "
        "training, use Google Search and cite the source briefly.\n"
    )


def build_system_prompt(
    turn: TurnPayload,
    *,
    grounding_enabled: bool = False,
    voice_coverage: list[str] | None = None,
) -> str:
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    return (
        template
        .replace("__STEP_LABEL__", turn.step.label)
        .replace("__VOICE_COVERAGE_SECTION__", _voice_coverage_section(voice_coverage))
        .replace("__GROUNDING_SECTION__", _grounding_section(grounding_enabled))
        .replace("__TURN_JSON__", turn.model_dump_json())
    )
