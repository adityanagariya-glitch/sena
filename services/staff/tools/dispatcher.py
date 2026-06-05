"""Tool dispatcher — runs a tool by name with validated inputs.

Used by `agent.py` after Bedrock returns a `toolUse` block.

Every tool dispatch is logged to the original terminal stderr (sys.__stderr__)
so the Streamlit-launching shell sees what the agent is doing in real time,
even when ui.py redirects stderr to capture model output.
"""
import json
import sys
import time
from typing import Any, Dict

from tools.base import ToolResult
from tools.registry import TOOLS_BY_NAME


# Terminal-direct — bypasses any redirect_stderr() context manager,
# AND tees to /tmp/sena_activity.log so Streamlit's uvicorn capture can't hide it.
from activity_log import _TERMINAL


def _short_inputs(inputs: dict[str, Any] | None) -> str:
    """One-line summary of tool inputs for the terminal log."""
    if not inputs:
        return "{}"
    try:
        s = json.dumps(inputs, ensure_ascii=False, default=str)
    except Exception:
        s = str(inputs)
    if len(s) > 200:
        s = s[:200]
    return s


def run_tool(
    name: str,
    inputs: dict[str, Any] | None,
    allowed: set[str] | None = None,
    scope: str | None = None,
) -> ToolResult:
    """Look up the tool by name and execute it. Never raises — returns
    ToolResult with `error` set if anything goes wrong.

    Args:
        name: tool name the model asked for.
        inputs: validated tool inputs.
        allowed: if given, the set of tool names permitted in the active section.
            Any tool outside it is refused — defense-in-depth so the staff and
            client sections stay independent even if the model is offered, or
            hallucinates, an out-of-section tool.
        scope: active section ('staff' | 'client'), used for messaging and to pin
            cross-channel tools (find_person) to the current section only.
    """
    inputs = dict(inputs or {})
    print(f"[TOOL] > {name}({_short_inputs(inputs)})", file=_TERMINAL, flush=True)

    # Scope enforcement — refuse tools outside the active section.
    if allowed is not None and name not in allowed:
        print(f"[TOOL] X {name}  blocked (outside '{scope}' section)", file=_TERMINAL, flush=True)
        return ToolResult(
            error=f"Tool '{name}' is not available in the {scope or 'current'} section.",
            next_hint="That tool belongs to a different section — use a tool from this section instead.",
        )

    # find_person searches BOTH the staff and client directories. Pin it to the
    # active section so a staff query can't surface clients and vice-versa.
    if name == "find_person" and scope in ("staff", "client"):
        inputs["type"] = scope

    tool = TOOLS_BY_NAME.get(name)
    if not tool:
        print(f"[TOOL] X {name}  unknown tool", file=_TERMINAL, flush=True)
        return ToolResult(
            error=f"Unknown tool '{name}'. The LLM should pick a different tool.",
            next_hint="Tool not found — try a different approach.",
        )

    t0 = time.time()
    try:
        result = tool.run(inputs)
        if not isinstance(result, ToolResult):
            print(
                f"[TOOL] X {name}  returned non-ToolResult ({type(result).__name__})",
                file=_TERMINAL, flush=True,
            )
            return ToolResult(
                error=f"Tool '{name}' returned non-ToolResult ({type(result).__name__})",
            )

        elapsed_ms = int((time.time() - t0) * 1000)
        status = "X ERR " if result.error else "✓ OK  "
        # Show a brief preview of meta info to make traces readable
        meta_preview = ""
        if result.meta:
            meta_short = {k: v for k, v in result.meta.items() if k in ("path", "timeframe", "search", "staff_type", "shift_filter", "client_id", "topic", "merged_shift_count", "per_source_occurrence_counts")}
            if meta_short:
                meta_preview = f"  meta={_short_inputs(meta_short)}"
        print(f"[TOOL] {status}{name}  ({elapsed_ms}ms){meta_preview}", file=_TERMINAL, flush=True)
        return result
    except Exception as e:
        print(f"[TOOL] X EXC {name}  {type(e).__name__}: {e}", file=_TERMINAL, flush=True)
        return ToolResult(
            error=f"Tool '{name}' crashed: {type(e).__name__}: {e}",
            next_hint="Tool execution failed unexpectedly. Apologise to the user and suggest they try again.",
        )
