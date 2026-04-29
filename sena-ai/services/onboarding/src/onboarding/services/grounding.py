"""
Grounding tool builder — Phase E.

Pure module (no IO). Assembles the Gemini Live tools list from function
declarations plus an optional Google Search tool, gated by a single flag.

Usage:
    tools = build_live_tools(FUNCTION_DECLS, grounding_enabled=settings.onboarding_grounding_enabled)
    # tools is [] if both args are empty/False
    # tools is [Tool(function_declarations=[...])] when grounding is off
    # tools is [Tool(function_declarations=[...]), Tool(google_search=GoogleSearch())] when on
"""
from __future__ import annotations

from typing import Any

from google.genai import types


def build_live_tools(
    function_decls: list[dict[str, Any]],
    *,
    grounding_enabled: bool,
) -> list[types.Tool]:
    """
    Returns the tools list to attach to LiveConnectConfig.

    Always includes Tool(function_declarations=...) when function_decls is non-empty.
    Appends Tool(google_search=GoogleSearch()) when grounding_enabled is True.
    Default off — enabling requires compliance sign-off (SENA_AI_ONBOARDING_GROUNDING_ENABLED).
    """
    tools: list[types.Tool] = []
    if function_decls:
        tools.append(types.Tool(function_declarations=function_decls))
    if grounding_enabled:
        tools.append(types.Tool(google_search=types.GoogleSearch()))
    return tools
