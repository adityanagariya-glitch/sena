"""Tests for services/grounding.py — pure module, no mocks needed."""
from __future__ import annotations

from google.genai import types

from voice.grounding import build_live_tools

_DECLS = [{"name": "update_field", "description": "test", "parameters": {"type": "object", "properties": {}}}]


def test_grounding_off_returns_one_tool():
    tools = build_live_tools(_DECLS, grounding_enabled=False)
    assert len(tools) == 1
    assert tools[0].function_declarations is not None


def test_grounding_on_returns_two_tools():
    tools = build_live_tools(_DECLS, grounding_enabled=True)
    assert len(tools) == 2
    names = {type(t.google_search).__name__ for t in tools if t.google_search is not None}
    assert "GoogleSearch" in names


def test_empty_decls_grounding_off_returns_empty():
    tools = build_live_tools([], grounding_enabled=False)
    assert tools == []


def test_empty_decls_grounding_on_returns_search_only():
    tools = build_live_tools([], grounding_enabled=True)
    assert len(tools) == 1
    assert tools[0].google_search is not None


def test_function_decls_passed_through_unchanged():
    tools = build_live_tools(_DECLS, grounding_enabled=False)
    assert tools[0].function_declarations is not None
    assert tools[0].function_declarations[0].name == "update_field"
