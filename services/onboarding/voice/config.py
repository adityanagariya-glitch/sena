"""Per-service configuration for the shared voice engine.

Replaces the old ``from onboarding.core.settings import settings`` coupling:
each consuming service (onboarding, case_review) builds a ``VoiceEngineConfig``
from its own ``core/settings.py`` and injects it into ``GeminiLiveSession`` and
``build_system_prompt``. The engine reads only this object — never a service's
settings module — so the shared package has no reverse dependency on any service.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VoiceEngineConfig:
    """Immutable config injected into the voice engine at session construction.

    ``prompts_dir`` is the base directory holding the system-prompt template plus
    the ``steps/`` and ``modes/`` subtrees; each service supplies its own so the
    engine never hard-codes onboarding's prompt layout.
    """

    gemini_api_key: str
    gemini_live_model_id: str
    prompts_dir: Path
    grounding_enabled: bool = False
    screen_state_max_bytes: int = 8192
    session_max_sec: int = 3600
    silence_timeout_sec: int = 8
    tool_state_channel: bool = True
    # Strip static per-field metadata (enum_values on filled fields, section,
    # repeatable_index, validations_hint) from the state echoed back to Gemini
    # in every function_response. Self-contained (all path+value kept every
    # turn — no field omitted), so it's safe under sliding-window compression.
    compress_tool_state: bool = True
    debug: bool = False
