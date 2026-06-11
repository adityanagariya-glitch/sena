"""sena_common.voice — shared voice-onboarding layer.

Re-exports the public surface consumed by onboarding and future services
(case_review, staff). Import directly from sub-modules for tree-shaking;
use these re-exports for convenience in tests and service wiring.
"""

from __future__ import annotations

from config import VoiceEngineConfig
from coverage import coverage_paths, is_eligible, is_repeatable_eligible
from field_apply import build_envelope
from form_state import FieldValue, FormState
from gemini_live import GeminiLiveSession
from grounding import build_live_tools
from mobile_bridge import MobileBridge
from prompt_builder import build_system_prompt
from resumption import build_replay_context, issue_handle, redeem_handle
from schema_spec import FieldSpec, SectionSpec, StepSchema
from session_bootstrap import SessionBootstrap
from state_repo import FormStateRepo
from tools import FUNCTION_DECLS, ToolDispatcher
from turn_payload import TurnPayload
from webhook import fire_webhook

__all__ = [
    # Engine config (injected — replaces onboarding.core.settings coupling)
    "VoiceEngineConfig",
    # Gemini bridge
    "GeminiLiveSession",
    # Tool dispatcher
    "ToolDispatcher",
    "FUNCTION_DECLS",
    # State repository
    "FormStateRepo",
    # Prompt builder
    "build_system_prompt",
    # Mobile bridge
    "MobileBridge",
    # Resumption
    "build_replay_context",
    "issue_handle",
    "redeem_handle",
    # Webhook
    "fire_webhook",
    # Grounding
    "build_live_tools",
    # Field apply
    "build_envelope",
    # Coverage
    "is_eligible",
    "is_repeatable_eligible",
    "coverage_paths",
    # Models
    "StepSchema",
    "SectionSpec",
    "FieldSpec",
    "FormState",
    "FieldValue",
    "SessionBootstrap",
    "TurnPayload",
]
