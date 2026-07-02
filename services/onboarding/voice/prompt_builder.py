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

from collections.abc import Callable
from typing import Protocol, cast

from .turn_payload import TurnPayload, VisibleField


class PromptRegistry(Protocol):
    """Structural type for a prompt-set registry module (see prompts/registry.py)."""

    TEMPLATE: str
    STEPS: dict[str, str | Callable[[list[VisibleField]], str]]
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


def _step_rules_section(
    step_id: str, visible_fields: list[VisibleField], reg: PromptRegistry
) -> str:
    """Return the `{step_id}` step fragment from the registry, wrapped.

    step_id is globally unique across flows (e.g. `personal_information` vs
    `staff_personal_information`); the registry maps it to its prompt text. A
    non-empty step_id with no registered fragment is a misconfiguration (typo /
    unshipped prompt) and raises loudly — replacing the old silent rglob-miss
    that produced a half-built prompt. Empty step_id → empty section.

    Registry entries may be a plain str (static) or a callable that accepts
    visible_fields and returns the optimised fragment (state-aware injection).
    """
    if not step_id:
        return ""
    try:
        entry = reg.STEPS[step_id]
    except KeyError:
        raise KeyError(
            f"no prompt fragment registered for step_id={step_id!r}; "
            f"known steps: {sorted(reg.STEPS)}"
        ) from None
    body = (entry(visible_fields) if callable(entry) else entry).strip()
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
    """Full inline system prompt (static sections + bootstrap JSON baked in).

    Kept for backward compatibility / tests. The live WS path
    (api/ws_routes.py) uses build_static_system_prompt() + build_bootstrap_message()
    instead, so the (cacheable) static portion never embeds session-specific
    data — see prompt_cache.py for why that split exists.
    """
    reg = registry if registry is not None else _default_registry()
    template = reg.TEMPLATE
    mode = _detect_form_mode(turn.visible_fields)
    return (
        template.replace("__STEP_LABEL__", turn.step.label)
        .replace("__VOICE_COVERAGE_SECTION__", _voice_coverage_section(voice_coverage))
        .replace("__GROUNDING_SECTION__", _grounding_section(grounding_enabled))
        .replace("__MODE_RULES__", _mode_rules_section(mode, reg))
        .replace("__STEP_RULES__", _step_rules_section(turn.step.id, turn.visible_fields, reg))
        .replace("__TURN_JSON__", _bootstrap_state_json(turn, tool_state_channel))
    )


# Placeholder for the bootstrap block in the CACHEABLE static prompt — points
# the model at the message that follows, instead of embedding session-specific
# data (participant name, prior_steps) where every session would otherwise
# produce a distinct, uncacheable system-prompt string.
_BOOTSTRAP_POINTER = (
    "[Bootstrap state follows as a separate message immediately after this "
    "system prompt — treat it exactly as instructed above.]"
)


def build_static_system_prompt(
    turn: TurnPayload,
    *,
    grounding_enabled: bool = False,
    voice_coverage: list[str] | None = None,
    registry: PromptRegistry | None = None,
) -> str:
    """Build the step/mode-dependent but session-INDEPENDENT portion of the
    system prompt — every section except the bootstrap state block (§8).

    This string is safe to hand to Gemini's explicit cache
    (client.aio.caches.create) and reuse across every session that produces
    the identical (step_id, mode, voice_coverage, grounding) combination —
    explicit caching IS supported for Live sessions, proven by
    voice/services/gemini_live_service.py in this same codebase; see
    prompt_cache.py. Pair with build_bootstrap_message() for the
    session-specific part, injected as a realtime text turn after connecting
    instead of being embedded here.
    """
    reg = registry if registry is not None else _default_registry()
    template = reg.TEMPLATE
    mode = _detect_form_mode(turn.visible_fields)
    return (
        template.replace("__STEP_LABEL__", turn.step.label)
        .replace("__VOICE_COVERAGE_SECTION__", _voice_coverage_section(voice_coverage))
        .replace("__GROUNDING_SECTION__", _grounding_section(grounding_enabled))
        .replace("__MODE_RULES__", _mode_rules_section(mode, reg))
        .replace("__STEP_RULES__", _step_rules_section(turn.step.id, turn.visible_fields, reg))
        .replace("__TURN_JSON__", _BOOTSTRAP_POINTER)
    )


def build_bootstrap_message(turn: TurnPayload, tool_state_channel: bool = True) -> str:
    """The session-specific bootstrap state (§8's JSON) as a standalone
    message, sent via session.send_realtime_input(text=...) immediately after
    connecting — kept OUT of the system instruction so
    build_static_system_prompt()'s output stays identical, and therefore
    cacheable, across every session of the same step/mode.
    """
    return f"[BOOTSTRAP]\n{_bootstrap_state_json(turn, tool_state_channel)}"
