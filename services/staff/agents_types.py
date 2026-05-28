"""TypedDict schemas for agent responses and routing decisions.

Structured types for pattern matching, routing, and API response handling.
All TypedDict definitions use total=False for optional fields.
"""
from typing import TypedDict


class StopReasonResponse(TypedDict, total=False):
    """Bedrock Converse API response stop_reason."""
    stop_reason: str  # "guardrail_intervened" | "end_turn" | "tool_use" | "max_tokens"
    content: list[dict]
    tool_use_blocks: list[dict] | None


class APIRouteResponse(TypedDict, total=False):
    """Intent-based API routing decision."""
    intent: str  # "KB" | "API" | "GREETING"
    endpoint: str | None
    method: str  # "GET" | "POST" | "PUT"
    payload: dict | None


class APIErrorResponse(TypedDict, total=False):
    """API error response structure."""
    error: str
    status_code: int | None
    path: str | None


class ResponseTypeResponse(TypedDict, total=False):
    """Post-process response type detection."""
    response_type: str  # "KB" | "API" | "GREETING"
    content: str
    metadata: dict | None


class AuthResponse(TypedDict, total=False):
    """Combined auth flow response."""
    user_id: str
    authenticated: bool
    token: str | None
    error: str | None


class GuardRailResponse(TypedDict, total=False):
    """Policy check result."""
    allowed: bool
    reason: str | None


class DeploymentStatusResponse(TypedDict, total=False):
    """CloudFormation/infrastructure deployment status."""
    status: str  # "ACTIVE" | "CREATING" | "UPDATING" | "FAILED" | "DELETING"
    ready: bool
    error: str | None
