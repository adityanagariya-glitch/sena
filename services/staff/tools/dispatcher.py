"""Tool dispatcher — runs a tool by name with validated inputs.

Used by `agent.py` after Bedrock returns a `toolUse` block.
"""
import sys
from typing import Any, Dict

from config import VERBOSE
from tools.base import ToolResult
from tools.registry import TOOLS_BY_NAME


def run_tool(name: str, inputs: Dict[str, Any]) -> ToolResult:
    """Look up the tool by name and execute it. Never raises — returns
    ToolResult with `error` set if anything goes wrong."""
    tool = TOOLS_BY_NAME.get(name)
    if not tool:
        return ToolResult(
            error=f"Unknown tool '{name}'. The LLM should pick a different tool.",
            next_hint="Tool not found — try a different approach.",
        )

    if VERBOSE:
        print(f"[tool] running {name} with inputs={inputs}", file=sys.stderr)

    try:
        result = tool.run(inputs or {})
        if not isinstance(result, ToolResult):
            return ToolResult(
                error=f"Tool '{name}' returned non-ToolResult ({type(result).__name__})",
            )
        if VERBOSE:
            status = "ERROR" if result.error else "OK"
            print(f"[tool] {name} → {status}", file=sys.stderr)
        return result
    except Exception as e:
        if VERBOSE:
            print(f"[tool] {name} FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        return ToolResult(
            error=f"Tool '{name}' crashed: {type(e).__name__}: {e}",
            next_hint="Tool execution failed unexpectedly. Apologise to the user and suggest they try again.",
        )
