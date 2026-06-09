"""sena_common.voice — shared voice-onboarding layer.

Re-exports the public surface consumed by onboarding and future services
(case_review, staff). Import directly from sub-modules for tree-shaking;
use these re-exports for convenience in tests and service wiring.
"""

from __future__ import annotations

from sena_common.voice.coverage import coverage_paths, is_eligible, is_repeatable_eligible
from sena_common.voice.field_apply import build_envelope
from sena_common.voice.form_state import FieldValue, FormState
from sena_common.voice.gemini_live import GeminiLiveSession
from sena_common.voice.grounding import build_live_tools
from sena_common.voice.mobile_bridge import MobileBridge
from sena_common.voice.prompt_builder import build_system_prompt
from sena_common.voice.resumption import build_replay_context, issue_handle, redeem_handle
from sena_common.voice.schema_spec import FieldSpec, SectionSpec, StepSchema
from sena_common.voice.session_bootstrap import SessionBootstrap
from sena_common.voice.state_repo import FormStateRepo
from sena_common.voice.tools import FUNCTION_DECLS, ToolDispatcher
from sena_common.voice.turn_payload import TurnPayload
from sena_common.voice.webhook import fire_webhook

__all__ = [
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
