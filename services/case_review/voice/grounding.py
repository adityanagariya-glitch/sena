"""Grounding tool builder — pure module (no IO)."""
from __future__ import annotations

from typing import Any

from google.genai import types


def build_live_tools(
    function_decls: list[dict[str, Any]],
    *,
    grounding_enabled: bool,
) -> list[types.Tool]:
    tools: list[types.Tool] = []
    if function_decls:
        tools.append(types.Tool(function_declarations=function_decls))
    if grounding_enabled:
        tools.append(types.Tool(google_search=types.GoogleSearch()))
    return tools
