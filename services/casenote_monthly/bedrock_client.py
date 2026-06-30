"""Bedrock model invocation — buffered `call_bedrock` (+ async variant).

Trimmed copy of services/staff/bedrock_client.py: only the buffered calls are
kept because this service returns a single JSON summary (no token streaming).
"""
import asyncio
import sys
import time

from langfuse import observe, get_client

from config import bedrock_runtime, MODEL_ID, GUARDRAILS, VERBOSE
from guardrails import _last_user_text, _apply_guardrail

langfuse = get_client()
_SERVICE = "casenote_monthly"

_lf_prompt = None
try:
    _lf_prompt = langfuse.get_prompt(f"{_SERVICE}/monthly-summary-system")
except Exception:
    pass  # prompt will be unlinked; hardcoded system prompt in callers is used

# Anthropic prompt caching on Bedrock — marking the end of a stable prefix with a
# cachePoint lets subsequent calls reuse the KV cache for ~10% of input cost.
# Minimum cached prefix is 1024 tokens; below that Bedrock ignores the cachePoint.
_CACHE_MIN_CHARS = 2500


def _build_system_blocks(system_prompt: str | None) -> list[dict] | None:
    """Build the `system` payload with a cachePoint after a long stable prefix."""
    if not system_prompt:
        return None
    blocks = [{"text": system_prompt}]
    if len(system_prompt) >= _CACHE_MIN_CHARS:
        blocks.append({"cachePoint": {"type": "default"}})
    return blocks


def _log_cache_usage(response: dict, label: str) -> None:
    if not VERBOSE:
        return
    usage = response.get("usage") or {}
    read = usage.get("cacheReadInputTokens") or usage.get("cache_read_input_tokens") or 0
    write = usage.get("cacheWriteInputTokens") or usage.get("cache_write_input_tokens") or 0
    if read or write:
        print(f"[bedrock-cache] {label} read={read} write={write}", file=sys.stderr)


@observe(as_type="generation", name="casenote-generate", capture_input=False, capture_output=False)
def call_bedrock(
    messages: list[dict],
    system_prompt: str | None = None,
    use_guardrail: bool = True,
    max_tokens: int = 2048,
) -> str | None:
    """Call Claude via Bedrock `converse`, wrapped with stacked Bedrock Guardrails.

    `use_guardrail=False` skips guardrails for internal utility calls where the
    input is already-validated API data, not free-form user text.
    """
    start = time.time()

    # Pre-check: run EXTRA guardrails on input (primary one rides on converse below)
    if use_guardrail and len(GUARDRAILS) > 1:
        user_text = _last_user_text(messages)
        for gid, ver in GUARDRAILS[1:]:
            blocked = _apply_guardrail(gid, ver, user_text, "INPUT")
            if blocked:
                print(f"[bedrock-guardrails] INPUT blocked by {gid}", file=sys.stderr)
                return blocked

    try:
        payload = {
            "modelId": MODEL_ID,
            "messages": messages,
            "inferenceConfig": {"maxTokens": max_tokens},
        }
        system_blocks = _build_system_blocks(system_prompt)
        if system_blocks:
            payload["system"] = system_blocks

        # Primary guardrail rides on converse() — covers both directions
        if use_guardrail and GUARDRAILS:
            primary_id, primary_ver = GUARDRAILS[0]
            payload["guardrailConfig"] = {
                "guardrailIdentifier": primary_id,
                "guardrailVersion": primary_ver,
                "trace": "enabled",
            }

        response = bedrock_runtime.converse(**payload)
        if VERBOSE:
            print(f"[bedrock-timing] converse took {time.time() - start:.2f}s "
                  f"(guardrail={use_guardrail})", file=sys.stderr)
        _log_cache_usage(response, "converse")

        if response.get("stopReason") == "guardrail_intervened" and GUARDRAILS:
            print(f"[bedrock-guardrails] primary {GUARDRAILS[0][0]} intervened", file=sys.stderr)

        text = None
        if response.get("output") and response["output"].get("message"):
            content = response["output"]["message"].get("content", [])
            if content and isinstance(content, list):
                text = content[0].get("text", "")

        # Record to Langfuse regardless of guardrail outcome
        usage = response.get("usage", {})
        user_text = _last_user_text(messages)
        input_total = usage.get("inputTokens", 0) + usage.get("cacheReadInputTokens", 0) + usage.get("cacheWriteInputTokens", 0)
        output_total = usage.get("outputTokens", 0)
        langfuse.update_current_generation(
            model=MODEL_ID,
            input=user_text[:2000] if user_text else None,
            output=text[:2000] if text else None,
            usage_details={
                "input": input_total,
                "output": output_total,
                "total": input_total + output_total,
            },
            prompt=_lf_prompt,
            metadata={"service": _SERVICE},
        )

        if not text:
            return None

        # Post-check: run EXTRA guardrails on the response
        if use_guardrail and len(GUARDRAILS) > 1:
            for gid, ver in GUARDRAILS[1:]:
                blocked = _apply_guardrail(gid, ver, text, "OUTPUT")
                if blocked:
                    print(f"[bedrock-guardrails] OUTPUT blocked by {gid}", file=sys.stderr)
                    return blocked

        return text

    except Exception as e:
        print(f"Bedrock error: {e}", file=sys.stderr)
        return None


async def call_bedrock_async(
    messages: list[dict],
    system_prompt: str | None = None,
    use_guardrail: bool = True,
    max_tokens: int = 2048,
) -> str | None:
    """Async variant of call_bedrock (wraps the sync boto3 call in a thread)."""
    return await asyncio.to_thread(
        call_bedrock, messages, system_prompt, use_guardrail, max_tokens
    )
