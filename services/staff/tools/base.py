"""Shared types for the SENA tool registry.

Every tool exposes:
- A `name` (matches the Bedrock toolSpec name)
- A `description` (what the LLM sees to decide when to use it)
- An `input_schema` (JSON Schema — Bedrock validates inputs against this)
- A `run` callable that takes the validated input dict and returns a ToolResult
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional


@dataclass
class ToolResult:
    """Standard envelope every tool returns.

    `data` is the structured payload the LLM will see next turn.
    `error` flags that the tool couldn't complete (LLM should explain it gracefully).
    `next_hint` is an optional instruction to nudge the LLM (e.g. "user must clarify").
    """
    data: Any = None
    error: Optional[str] = None
    next_hint: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        out = {"data": self.data}
        if self.error:
            out["error"] = self.error
        if self.next_hint:
            out["next_hint"] = self.next_hint
        if self.meta:
            out["meta"] = self.meta
        return out


@dataclass
class ToolSpec:
    """Bedrock tool specification + the Python callable that runs it."""
    name: str
    description: str
    input_schema: Dict[str, Any]
    run: Callable[[Dict[str, Any]], ToolResult]

    def to_bedrock_spec(self) -> Dict[str, Any]:
        """Convert to the shape Bedrock Converse `toolConfig.tools` expects."""
        return {
            "toolSpec": {
                "name": self.name,
                "description": self.description,
                "inputSchema": {"json": self.input_schema},
            }
        }
