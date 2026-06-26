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

Per-step / per-mode rules and the base template now live as importable .py
modules under `prompts/` (one constant per file), assembled by
`prompts/registry.py` into TEMPLATE / STEPS / MODES. Each prompt-set passes its
registry via the `registry` kwarg. A step_id / mode with no registered fragment
raises loudly — no silent empty section. The base template stays free of step-
or mode-specific logic.
"""

from __future__ import annotations

from typing import Protocol, cast

from sena_common.voice.turn_payload import TurnPayload, VisibleField


class PromptRegistry(Protocol):
    """Structural type for a prompt-set registry module (see prompts/registry.py)."""

    TEMPLATE: str
    STEPS: dict[str, str]
    MODES: dict[str, str]


def _default_registry() -> PromptRegistry:
    """Fallback prompt registry = onboarding's, imported lazily.

    Lazy import so loading this module does NOT require ``onboarding`` to be
    installed — case_review passes its own ``registry`` and never triggers this.
    """
    from onboarding.prompts import registry

    return cast("PromptRegistry", registry)


def _bootstrap_state_json(turn: TurnPayload, tool_state_channel: bool) -> str:
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
    if not tool_state_channel:
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


def _step_rules_section(step_id: str, reg: PromptRegistry) -> str:
    """Return the `{step_id}` step fragment from the registry, wrapped.

    step_id is globally unique across flows (e.g. `personal_information` vs
    `staff_personal_information`); the registry maps it to its prompt text. A
    non-empty step_id with no registered fragment is a misconfiguration (typo /
    unshipped prompt) and raises loudly — replacing the old silent rglob-miss
    that produced a half-built prompt. Empty step_id → empty section.
    """
    if not step_id:
        return ""
    try:
        body = reg.STEPS[step_id].strip()
    except KeyError:
        raise KeyError(
            f"no prompt fragment registered for step_id={step_id!r}; "
            f"known steps: {sorted(reg.STEPS)}"
        ) from None
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


def _mode_rules_section(mode: str, reg: PromptRegistry) -> str:
    """Return `modes[mode]` from the registry, wrapped.

    Mode is always `fresh`/`update` (see _detect_form_mode), so a missing key is
    a packaging bug and raises loudly.
    """
    try:
        body = reg.MODES[mode].strip()
    except KeyError:
        raise KeyError(
            f"no mode fragment registered for mode={mode!r}; "
            f"known modes: {sorted(reg.MODES)}"
        ) from None
    if not body:
        return ""
    return f"\n{body}\n"


def build_system_prompt(
    turn: TurnPayload,
    *,
    grounding_enabled: bool = False,
    voice_coverage: list[str] | None = None,
    registry: PromptRegistry | None = None,
    tool_state_channel: bool = True,
) -> str:
    reg = registry if registry is not None else _default_registry()
    template = reg.TEMPLATE
    mode = _detect_form_mode(turn.visible_fields)
    return (
        template.replace("__STEP_LABEL__", turn.step.label)
        .replace("__VOICE_COVERAGE_SECTION__", _voice_coverage_section(voice_coverage))
        .replace("__GROUNDING_SECTION__", _grounding_section(grounding_enabled))
        .replace("__MODE_RULES__", _mode_rules_section(mode, reg))
        .replace("__STEP_RULES__", _step_rules_section(turn.step.id, reg))
        .replace("__TURN_JSON__", _bootstrap_state_json(turn, tool_state_channel))
    )
