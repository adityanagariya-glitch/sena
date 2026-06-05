"""TypedDict schemas referenced by bedrock_client / guardrails.

Minimal subset copied from services/staff/agents_types.py — only the types the
case-note summary service actually imports.
"""
from typing import TypedDict


class StopReasonResponse(TypedDict, total=False):
    """Bedrock Converse API response stop_reason."""
    stop_reason: str  # "guardrail_intervened" | "end_turn" | "tool_use" | "max_tokens"
    content: list[dict]
    tool_use_blocks: list[dict] | None


class GuardRailResponse(TypedDict, total=False):
    """Policy check result."""
    allowed: bool
    reason: str | None
