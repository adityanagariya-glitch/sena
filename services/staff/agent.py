"""Agent loop — Bedrock Converse with Tool Use, multi-turn.

Replaces detect_route + find_best_api + handler dispatch with a single agentic
loop. The LLM picks tools, the dispatcher runs them, results flow back to the
LLM until it emits a final text response for the user.

Public entry: `process_query_agent(user_question)` — drop-in for router's
process_query handlers.
"""
import asyncio
import json
import sys
import time

from config import (
    VERBOSE,
    MODEL_ID,
    GUARDRAILS,
    bedrock_runtime,
)
from state import user_context, conversation_history
from memory import _persist_turn, _format_user_profile
from agent_prompts import _core_prompt, _skills_for_question
from tools.registry import bedrock_tool_config
from tools.dispatcher import run_tool
from agents_types import StopReasonResponse


# How many tool-call iterations to allow before giving up (prevents infinite loops).
_MAX_TOOL_ITERATIONS = 6

_IN_SCOPE_WORK_TERMS = (
    "shift",
    "shifts",
    "roster",
    "rosters",
    "client",
    "clients",
    "participant",
    "participants",
    "allowance",
    "allowances",
    "payroll",
    "ndis",
    "policy",
    "policies",
    "support worker",
    "support workers",
    "organisation",
    "organisations",
    "organization",
    "organizations",
    " org",
    "orgs",
    "business",
    "business name",
    "owner",
    "account",
)


def _looks_like_work_query(text: str | None) -> bool:
    q = (text or "").lower()
    return any(term in q for term in _IN_SCOPE_WORK_TERMS)


def _work_query_snag_message(text: str | None) -> str:
    q = (text or "").lower()
    if (
        "organisation" in q or "organization" in q or " org" in q
        or "business" in q or "owner" in q or "account" in q
    ):
        subject = "organisation details"
    elif "client" in q or "participant" in q or "medical" in q:
        subject = "client information"
    elif "shift" in q or "roster" in q:
        subject = "shift answer"
    elif "payroll" in q or "allowance" in q:
        subject = "payroll details"
    elif "policy" in q or "ndis" in q:
        subject = "NDIS answer"
    else:
        subject = "answer"
    return (
        f"I hit a snag putting that {subject} together just now. "
        "Please try again in a moment."
    )


def _build_user_profile_block() -> str | None:
    """Tier-2 system prompt — per-user, cached separately."""
    return _format_user_profile()


def _coerce_text(value) -> str:
    """Unwrap any Bedrock 'text' value into a plain string.

    Bedrock's Converse response normally returns text blocks as
    `{"text": "string"}`, but in guardrail-augmented / wrapped responses the
    value can come through as a nested dict — e.g. `{"text": {"text": "string"}}`
    — or as a list of fragments. Blindly passing those to `.join()` raises
    `TypeError: sequence item 0: expected str instance, dict found`.

    This helper accepts any shape and returns a plain string, or '' if it
    can't extract anything useful.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        # Nested {"text": ...} or guardrail-wrapped variants
        inner = value.get("text") or value.get("content") or value.get("output")
        return _coerce_text(inner)
    if isinstance(value, list):
        return "".join(_coerce_text(v) for v in value)
    return str(value)


def _bedrock_messages_from_history() -> list[dict]:
    """Convert the in-memory conversation_history into Bedrock messages format."""
    messages = []
    # Bedrock requires alternating user/assistant; the conversation_history is
    # already in role/content shape but may have multiple consecutive turns of
    # one role from streaming. Coalesce conservatively.
    for turn in conversation_history[-10:]:
        role = turn.get("role")
        if role not in ("user", "assistant"):
            continue
        content = turn.get("content") or []
        text_parts = []
        for part in content:
            if isinstance(part, dict) and part.get("text") is not None:
                t = _coerce_text(part["text"])
                if t and t.strip():                # Bedrock rejects whitespace-only text
                    text_parts.append(t.strip())
        joined = "\n".join(text_parts).strip()
        if not joined:                              # skip whitespace-only turns entirely
            continue
        messages.append({"role": role, "content": [{"text": joined}]})
    return messages


def _content_blocks_with_tool_use(message: dict) -> tuple[list[str], list[dict]]:
    """Extract { text_blocks: [...], tool_use_blocks: [...] } from a Bedrock assistant message.

    `text_blocks` is always a list of plain strings — nested/wrapped text values
    from Bedrock are flattened via _coerce_text so downstream `.join()` never
    sees a dict.
    """
    text_blocks = []
    tool_use_blocks = []
    for block in (message.get("content") or []):
        if not isinstance(block, dict):
            continue
        if "text" in block:
            t = _coerce_text(block["text"])
            if t:
                text_blocks.append(t)
        elif "toolUse" in block:
            tool_use_blocks.append(block["toolUse"])
    return text_blocks, tool_use_blocks


def process_query_agent(user_question: str) -> str:
    """Agentic processing of a user query.

    Returns the final string answer (already printed to the user via streaming
    or final reveal).
    """
    start = time.time()

    # Terminal-direct stream — bypasses Streamlit's redirect_stderr AND tees to
    # /tmp/sena_activity.log so the launching shell always sees per-turn activity.
    from activity_log import _TERMINAL
    print(f"\n[AGENT] ━━━ user: {user_question!r}", file=_TERMINAL, flush=True)

    # Tier 1 — small core prompt, cached (identity, voice, today, principles)
    system_blocks = [{"text": _core_prompt()}]
    system_blocks.append({"cachePoint": {"type": "default"}})

    # Tier 2 — per-user profile, cached per user
    profile_text = _build_user_profile_block()
    if profile_text:
        system_blocks.append({"text": profile_text})
        system_blocks.append({"cachePoint": {"type": "default"}})

    # Tier 3 — per-question skill blocks, NOT cached (varies per turn).
    # Only the relevant skills load — keeps the prompt lean per turn and
    # avoids feeding the LLM unrelated guidance that could trigger hallucination.
    skills_text = _skills_for_question(user_question)
    if skills_text:
        system_blocks.append({"text": skills_text})
        # Show which skill blocks were loaded for this turn
        skill_names = [line.split('(')[0].strip().replace('## ', '') for line in skills_text.split('\n') if line.startswith('## ')]
        print(f"[AGENT] skills loaded: {skill_names}", file=_TERMINAL, flush=True)
    else:
        print(f"[AGENT] skills loaded: [] (core prompt only)", file=_TERMINAL, flush=True)

    tool_config = bedrock_tool_config()

    # Seed messages: prior conversation + this new user turn.
    # Strip trailing/leading whitespace — Bedrock rejects whitespace-only text blocks.
    messages = _bedrock_messages_from_history()
    user_text = (user_question or "").strip()
    if not user_text:
        return "Sorry — that came through blank. Could you type your question again?"
    messages.append({
        "role": "user",
        "content": [{"text": user_text}],
    })

    final_text = ""
    iterations = 0

    while iterations < _MAX_TOOL_ITERATIONS:
        iterations += 1
        loop_start = time.time()

        payload = {
            "modelId": MODEL_ID,
            "messages": messages,
            "system": system_blocks,
            "toolConfig": tool_config,
            "inferenceConfig": {"maxTokens": 2048},
        }

        # Primary guardrail rides on converse() — covers in + out, no extra cost
        if GUARDRAILS:
            primary_id, primary_ver = GUARDRAILS[0]
            payload["guardrailConfig"] = {
                "guardrailIdentifier": primary_id,
                "guardrailVersion": primary_ver,
                "trace": "enabled",
            }

        print(f"[AGENT] iter {iterations} → calling Bedrock...", file=_TERMINAL, flush=True)
        try:
            response = bedrock_runtime.converse(**payload)
        except Exception as e:
            print(f"[AGENT] ✗ Bedrock converse failed: {type(e).__name__}: {e}", file=_TERMINAL, flush=True)
            final_text = (
                "Sorry, I hit a snag connecting to the assistant just then. "
                "Give it another go in a moment."
            )
            break

        elapsed = time.time() - loop_start
        stop_reason = response.get("stopReason")
        # Show token usage so we can see prompt-size impact at a glance
        usage = response.get("usage") or {}
        in_tok = usage.get("inputTokens", 0)
        out_tok = usage.get("outputTokens", 0)
        cache_read = usage.get("cacheReadInputTokens", 0)
        cache_write = usage.get("cacheWriteInputTokens", 0)
        print(
            f"[AGENT] iter {iterations} done in {elapsed:.2f}s  stop={stop_reason}  "
            f"in={in_tok} (cache_r={cache_read}, cache_w={cache_write})  out={out_tok}",
            file=_TERMINAL, flush=True,
        )

        # Pattern match on stop_reason — handle guardrail intervention early
        match stop_reason:
            case "guardrail_intervened":
                message = response.get("output", {}).get("message", {})
                text_blocks, _ = _content_blocks_with_tool_use(message)
                guardrail_text = " ".join(text_blocks).strip()
                if _looks_like_work_query(user_question):
                    final_text = _work_query_snag_message(user_question)
                else:
                    final_text = guardrail_text or (
                        "I can only help with SENA and NDIS-related questions. Please ask "
                        "about shifts, clients, payroll, policies, or other NDIS topics."
                    )
                break
            case _:
                pass

        assistant_message = response.get("output", {}).get("message", {})
        text_blocks, tool_use_blocks = _content_blocks_with_tool_use(assistant_message)

        # Handle end_turn or no tool calls
        if stop_reason == "end_turn" or not tool_use_blocks:
            final_text = "\n".join(t for t in text_blocks if t).strip()
            if not final_text:
                final_text = "Sorry, I couldn't put together an answer for that."
            break

        # Show the model's tool selection for this iteration — names + a short
        # preview of the inputs, so it's clear WHY each [TOOL] line that follows
        # was run (rather than just seeing the dispatch line in isolation).
        picks = ", ".join(tu.get("name", "?") for tu in tool_use_blocks)
        print(f"[AGENT] iter {iterations} picked tools: [{picks}]", file=_TERMINAL, flush=True)

        # tool_use stop reason — append the assistant message and run each tool
        messages.append({
            "role": "assistant",
            "content": assistant_message.get("content") or [],
        })

        tool_result_blocks = []
        for tu in tool_use_blocks:
            tool_name = tu.get("name", "")
            tool_use_id = tu.get("toolUseId", "")
            tool_input = tu.get("input") or {}

            result = run_tool(tool_name, tool_input)

            tool_result_blocks.append({
                "toolResult": {
                    "toolUseId": tool_use_id,
                    "content": [{"json": result.to_dict()}],
                    "status": "error" if result.error else "success",
                }
            })

        messages.append({
            "role": "user",
            "content": tool_result_blocks,
        })

    if iterations >= _MAX_TOOL_ITERATIONS and not final_text:
        final_text = (
            "I worked through a few steps but couldn't wrap that one up neatly. "
            "Try rephrasing what you're after — for example: "
            "'show my shifts this week' or 'tell me about <client name>'."
        )

    # Output sanitiser — last gate. Catches accidental leak of secrets, model
    # identity, system-prompt phrases, or tool-name enumeration. On match the
    # whole reply is replaced with a safe fallback.
    from style_guide import sanitize_output
    final_text, leak_kind = sanitize_output(final_text)
    if leak_kind:
        print(
            f"[AGENT] OUTPUT FILTER blocked leak (kind={leak_kind}) — "
            f"reply replaced with safe fallback",
            file=_TERMINAL, flush=True,
        )

    total = time.time() - start
    reply_preview = final_text.replace("\n", " ")[:160]
    print(
        f"[AGENT] ━━━ done  {iterations} iter(s), {total:.2f}s total  "
        f"reply≈{reply_preview!r}",
        file=_TERMINAL, flush=True,
    )

    print(f"\nSena: {final_text}")
    _persist_turn(user_question, final_text, mode="AGENT" if not leak_kind else f"OUTPUT_FILTERED_{leak_kind.upper()}")
    return final_text


# ---- Async Tool Dispatch (for parallelization) ----

async def _run_tool_async(name: str, inputs: dict) -> tuple[str, dict, object]:
    """Async variant of run_tool using asyncio.to_thread.

    Returns (tool_name, tool_use_id, result) for gathering.
    """
    return await asyncio.to_thread(run_tool, name, inputs)


async def _dispatch_tools_parallel(tool_use_blocks: list[dict]) -> list[dict]:
    """Parallelize tool dispatch using asyncio.gather when multiple tools are requested.

    When the LLM picks multiple tools (2+), run them concurrently instead of
    sequentially. Single tools run via to_thread for consistency.
    """
    if not tool_use_blocks:
        return []

    from activity_log import _TERMINAL

    # Create async tasks for each tool
    tasks = []
    tool_metadata = []  # Track (name, tool_use_id) for result assembly
    for tu in tool_use_blocks:
        tool_name = tu.get("name", "")
        tool_use_id = tu.get("toolUseId", "")
        tool_input = tu.get("input") or {}
        tasks.append(_run_tool_async(tool_name, tool_input))
        tool_metadata.append((tool_name, tool_use_id))

    # Run all tools in parallel
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Assemble tool result blocks
    tool_result_blocks = []
    for i, (result, (tool_name, tool_use_id)) in enumerate(zip(results, tool_metadata)):
        if isinstance(result, Exception):
            print(f"[TOOL] X ERR {tool_name}  {type(result).__name__}: {result}", file=_TERMINAL, flush=True)
            tool_result_blocks.append({
                "toolResult": {
                    "toolUseId": tool_use_id,
                    "content": [{"json": {"error": str(result)}}],
                    "status": "error",
                }
            })
        else:
            tool_result_blocks.append({
                "toolResult": {
                    "toolUseId": tool_use_id,
                    "content": [{"json": result.to_dict()}],
                    "status": "error" if result.error else "success",
                }
            })

    return tool_result_blocks
