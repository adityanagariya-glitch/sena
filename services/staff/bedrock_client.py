"""Bedrock model invocation — buffered (`call_bedrock`) and streaming variants.

Use `call_bedrock_stream` for user-facing replies (prints tokens live).
Use `call_bedrock` for JSON-parsing utility calls (intent detection, API routing).
Async variants: `call_bedrock_async` and `call_bedrock_stream_async` for parallelization.
"""
import asyncio
import sys

try:
    from dotenv import find_dotenv, load_dotenv
    _env = find_dotenv(usecwd=True)
    if _env:
        load_dotenv(_env, override=False)
except ImportError:
    pass

from langfuse import observe, get_client

from config import bedrock_runtime, MODEL_ID, GUARDRAILS, VERBOSE
from guardrails import _last_user_text, _apply_guardrail
from agents_types import StopReasonResponse

langfuse = get_client()
_SERVICE = "staff-client"

_lf_prompt = None
try:
    _lf_prompt = langfuse.get_prompt(f"{_SERVICE}/system-prompt")
except Exception:
    pass

# Anthropic prompt caching on Bedrock — Claude Sonnet 4.x supports it. Marking
# the end of a stable prefix with a cachePoint block lets subsequent calls reuse
# the KV cache for ~10% of normal input cost (5-min ephemeral TTL). The minimum
# cached prefix is 1024 tokens (~3-4k chars of English); below that Bedrock
# silently ignores the cachePoint, so the threshold below is just a small
# optimisation to avoid pointless API noise on short system prompts.
_CACHE_MIN_CHARS = 2500


def _build_system_blocks(system_prompt: str | None, user_profile: str | None = None) -> list[dict] | None:
    """Build the `system` payload with up to two cachePoints (global + per-user).

    Layout::

        [Tier 1 — stable across all users]
        [cachePoint]            ← global cache (high hit rate)
        [Tier 2 — per-user profile + preferences]
        [cachePoint]            ← per-user cache (5-min Bedrock TTL)

    The 2nd cachePoint is a no-op on Bedrock when the prefix below the
    1024-token minimum, so we always emit it when `user_profile` is non-empty —
    Bedrock silently ignores it if too short.
    """
    if not system_prompt:
        return None
    blocks = [{"text": system_prompt}]
    if len(system_prompt) >= _CACHE_MIN_CHARS:
        blocks.append({"cachePoint": {"type": "default"}})
    if user_profile:
        blocks.append({"text": user_profile})
        blocks.append({"cachePoint": {"type": "default"}})
    return blocks


def _log_cache_usage(response: dict, label: str) -> None:
    """Emit cache read/write token counts to stderr when VERBOSE is on."""
    if not VERBOSE:
        return
    usage = response.get("usage") or {}
    read = usage.get("cacheReadInputTokens") or usage.get("cache_read_input_tokens") or 0
    write = usage.get("cacheWriteInputTokens") or usage.get("cache_write_input_tokens") or 0
    if read or write:
        print(f"[bedrock-cache] {label} read={read} write={write}", file=sys.stderr)


@observe(as_type="generation", name="staff-client-query", capture_input=False, capture_output=False)
def call_bedrock_stream(messages: list[dict], system_prompt: str | None = None, use_guardrail: bool = True, user_profile: str | None = None) -> str | None:
    """Streaming variant of call_bedrock. Prints tokens live and returns full text.

    Use this for user-facing replies (chat answers, API summaries). For JSON-parsing
    utility calls (intent detection, API routing) keep using call_bedrock — streaming
    JSON gives no benefit since you have to wait for the whole thing to parse it.

    `use_guardrail=False` skips Bedrock Guardrails for this call — only safe when the
    input is fully under our control (e.g. the META path replaying the user's own
    prior turns, which already passed guardrails on the way in, or API response translation
    where the response is already validated data from a legitimate API call).
    """
    import time
    start = time.time()

    # Pre-check: extra guardrails on input (primary rides on converse_stream below)
    # Skip this check if use_guardrail=False (e.g. API response translation, META recall)
    if use_guardrail and len(GUARDRAILS) > 1:
        user_text = _last_user_text(messages)
        for gid, ver in GUARDRAILS[1:]:
            blocked = _apply_guardrail(gid, ver, user_text, "INPUT")
            if blocked:
                print(f"[bedrock-guardrails] INPUT blocked by {gid}", file=sys.stderr)
                print(blocked)
                return blocked

    try:
        payload = {
            "modelId": MODEL_ID,
            "messages": messages,
            "inferenceConfig": {"maxTokens": 2048},
        }
        system_blocks = _build_system_blocks(system_prompt, user_profile=user_profile)
        if system_blocks:
            payload["system"] = system_blocks

        # Only attach guardrail config if use_guardrail=True AND guardrails are configured
        # For API response translation and META recall, skip guardrail to avoid false positives
        if use_guardrail and GUARDRAILS:
            primary_id, primary_ver = GUARDRAILS[0]
            payload["guardrailConfig"] = {
                "guardrailIdentifier": primary_id,
                "guardrailVersion": primary_ver,
                "trace": "enabled",
            }

        response = bedrock_runtime.converse_stream(**payload)

        chunks = []
        intervened = False
        cache_usage = {}
        stream_start = time.time()
        for event in response.get("stream", []):
            if "contentBlockDelta" in event:
                token = event["contentBlockDelta"]["delta"].get("text", "")
                if token:
                    print(token, end="", flush=True)
                    chunks.append(token)
            elif "messageStop" in event:
                if event["messageStop"].get("stopReason") == "guardrail_intervened":
                    intervened = True
                    print()
                    if GUARDRAILS:
                        print(f"[bedrock-guardrails] primary {GUARDRAILS[0][0]} intervened mid-stream", file=sys.stderr)
                    else:
                        print(f"[bedrock-guardrails] intervention occurred", file=sys.stderr)
            elif "metadata" in event:
                cache_usage = event["metadata"].get("usage") or {}
        _log_cache_usage({"usage": cache_usage}, "stream")

        print()  # newline after stream completes
        text = "".join(chunks)
        stream_elapsed = time.time() - stream_start
        print(f"[bedrock-timing] converse_stream took {stream_elapsed:.2f}s", file=sys.stderr)

        if not text:
            return None

        langfuse.update_current_generation(
            model=MODEL_ID,
            input=_last_user_text(messages),
            output=text[:2000],
            usage_details={
                "input": cache_usage.get("inputTokens", 0) + cache_usage.get("cacheReadInputTokens", 0) + cache_usage.get("cacheWriteInputTokens", 0),
                "output": cache_usage.get("outputTokens", 0),
                "total": cache_usage.get("inputTokens", 0) + cache_usage.get("cacheReadInputTokens", 0) + cache_usage.get("cacheWriteInputTokens", 0) + cache_usage.get("outputTokens", 0),
            },
            prompt=_lf_prompt,
            metadata={"service": _SERVICE},
        )

        # Post-check: run extra guardrails on the full assembled output
        # Skip post-check if use_guardrail=False (same as pre-check)
        if use_guardrail and len(GUARDRAILS) > 1 and not intervened:
            for gid, ver in GUARDRAILS[1:]:
                blocked = _apply_guardrail(gid, ver, text, "OUTPUT")
                if blocked:
                    print(f"[bedrock-guardrails] OUTPUT blocked by {gid}", file=sys.stderr)
                    print(blocked)
                    return blocked

        return text

    except Exception as e:
        print(f"Bedrock stream error: {e}", file=sys.stderr)
        return None


@observe(as_type="generation", name="staff-client-query", capture_input=False, capture_output=False)
def call_bedrock(messages: list[dict], system_prompt: str | None = None, user_profile: str | None = None, use_guardrail: bool = True) -> str | None:
    """Call Claude via Bedrock, wrapped with stacked AWS Bedrock Guardrails.

    `use_guardrail=False` skips guardrails for internal utility calls (intent
    detection, API routing, client resolution) — saves rate limit budget and
    reduces latency. Only safe when the output isn't shown directly to the user.
    """
    import time
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
            "inferenceConfig": {"maxTokens": 2048},
        }
        system_blocks = _build_system_blocks(system_prompt, user_profile=user_profile)
        if system_blocks:
            payload["system"] = system_blocks

        # Primary guardrail rides on converse() — free, covers both directions
        if use_guardrail and GUARDRAILS:
            primary_id, primary_ver = GUARDRAILS[0]
            payload["guardrailConfig"] = {
                "guardrailIdentifier": primary_id,
                "guardrailVersion": primary_ver,
                "trace": "enabled",
            }

        response = bedrock_runtime.converse(**payload)
        elapsed = time.time() - start
        print(f"[bedrock-timing] converse took {elapsed:.2f}s (guardrail={use_guardrail})", file=sys.stderr)
        _log_cache_usage(response, "converse")

        if response.get("stopReason") == "guardrail_intervened":
            print(f"[bedrock-guardrails] primary {GUARDRAILS[0][0]} intervened", file=sys.stderr)

        text = None
        if response.get("output") and response["output"].get("message"):
            content = response["output"]["message"].get("content", [])
            if content and isinstance(content, list):
                text = content[0].get("text", "")

        if not text:
            return None

        usage = response.get("usage", {})
        langfuse.update_current_generation(
            model=MODEL_ID,
            input=_last_user_text(messages),
            output=text[:2000],
            usage_details={
                "input": usage.get("inputTokens", 0) + usage.get("cacheReadInputTokens", 0) + usage.get("cacheWriteInputTokens", 0),
                "output": usage.get("outputTokens", 0),
                "total": usage.get("inputTokens", 0) + usage.get("cacheReadInputTokens", 0) + usage.get("cacheWriteInputTokens", 0) + usage.get("outputTokens", 0),
            },
            prompt=_lf_prompt,
            metadata={"service": _SERVICE},
        )

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


# ---- Async Variants (for parallelization) ----

@observe(as_type="generation", name="staff-client-query", capture_input=False, capture_output=False)
async def call_bedrock_async(messages: list[dict], system_prompt: str | None = None, user_profile: str | None = None, use_guardrail: bool = True) -> str | None:
    """Async variant of call_bedrock using asyncio.to_thread to wrap sync boto3 calls."""
    import time
    start = time.time()

    # Pre-check: run EXTRA guardrails on input
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
            "inferenceConfig": {"maxTokens": 2048},
        }
        system_blocks = _build_system_blocks(system_prompt, user_profile=user_profile)
        if system_blocks:
            payload["system"] = system_blocks

        if use_guardrail and GUARDRAILS:
            primary_id, primary_ver = GUARDRAILS[0]
            payload["guardrailConfig"] = {
                "guardrailIdentifier": primary_id,
                "guardrailVersion": primary_ver,
                "trace": "enabled",
            }

        # Run sync boto3 call in thread pool
        response = await asyncio.to_thread(bedrock_runtime.converse, **payload)
        elapsed = time.time() - start
        print(f"[bedrock-timing] converse_async took {elapsed:.2f}s (guardrail={use_guardrail})", file=sys.stderr)
        _log_cache_usage(response, "converse_async")

        if response.get("stopReason") == "guardrail_intervened":
            print(f"[bedrock-guardrails] primary {GUARDRAILS[0][0]} intervened", file=sys.stderr)

        text = None
        if response.get("output") and response["output"].get("message"):
            content = response["output"]["message"].get("content", [])
            if content and isinstance(content, list):
                text = content[0].get("text", "")

        if not text:
            return None

        usage = response.get("usage", {})
        langfuse.update_current_generation(
            model=MODEL_ID,
            input=_last_user_text(messages),
            output=text[:2000],
            usage_details={
                "input": usage.get("inputTokens", 0) + usage.get("cacheReadInputTokens", 0) + usage.get("cacheWriteInputTokens", 0),
                "output": usage.get("outputTokens", 0),
                "total": usage.get("inputTokens", 0) + usage.get("cacheReadInputTokens", 0) + usage.get("cacheWriteInputTokens", 0) + usage.get("outputTokens", 0),
            },
            prompt=_lf_prompt,
            metadata={"service": _SERVICE},
        )

        # Post-check: run EXTRA guardrails on the response
        if use_guardrail and len(GUARDRAILS) > 1:
            for gid, ver in GUARDRAILS[1:]:
                blocked = _apply_guardrail(gid, ver, text, "OUTPUT")
                if blocked:
                    print(f"[bedrock-guardrails] OUTPUT blocked by {gid}", file=sys.stderr)
                    return blocked

        return text

    except Exception as e:
        print(f"Bedrock async error: {e}", file=sys.stderr)
        return None


@observe(as_type="generation", name="staff-client-query", capture_input=False, capture_output=False)
async def call_bedrock_stream_async(messages: list[dict], system_prompt: str | None = None, use_guardrail: bool = True, user_profile: str | None = None) -> str | None:
    """Async variant of call_bedrock_stream using asyncio.to_thread for streaming."""
    import time
    start = time.time()

    # Pre-check: extra guardrails on input
    if use_guardrail and len(GUARDRAILS) > 1:
        user_text = _last_user_text(messages)
        for gid, ver in GUARDRAILS[1:]:
            blocked = _apply_guardrail(gid, ver, user_text, "INPUT")
            if blocked:
                print(f"[bedrock-guardrails] INPUT blocked by {gid}", file=sys.stderr)
                print(blocked)
                return blocked

    try:
        payload = {
            "modelId": MODEL_ID,
            "messages": messages,
            "inferenceConfig": {"maxTokens": 2048},
        }
        system_blocks = _build_system_blocks(system_prompt, user_profile=user_profile)
        if system_blocks:
            payload["system"] = system_blocks

        if use_guardrail and GUARDRAILS:
            primary_id, primary_ver = GUARDRAILS[0]
            payload["guardrailConfig"] = {
                "guardrailIdentifier": primary_id,
                "guardrailVersion": primary_ver,
                "trace": "enabled",
            }

        # Run sync boto3 stream call in thread pool
        response = await asyncio.to_thread(bedrock_runtime.converse_stream, **payload)

        chunks = []
        intervened = False
        cache_usage = {}
        stream_start = time.time()
        for event in response.get("stream", []):
            if "contentBlockDelta" in event:
                token = event["contentBlockDelta"]["delta"].get("text", "")
                if token:
                    print(token, end="", flush=True)
                    chunks.append(token)
            elif "messageStop" in event:
                if event["messageStop"].get("stopReason") == "guardrail_intervened":
                    intervened = True
                    print()
                    if GUARDRAILS:
                        print(f"[bedrock-guardrails] primary {GUARDRAILS[0][0]} intervened mid-stream", file=sys.stderr)
                    else:
                        print(f"[bedrock-guardrails] intervention occurred", file=sys.stderr)
            elif "metadata" in event:
                cache_usage = event["metadata"].get("usage") or {}
        _log_cache_usage({"usage": cache_usage}, "stream_async")

        print()  # newline after stream completes
        text = "".join(chunks)
        stream_elapsed = time.time() - stream_start
        print(f"[bedrock-timing] converse_stream_async took {stream_elapsed:.2f}s", file=sys.stderr)

        if not text:
            return None

        langfuse.update_current_generation(
            model=MODEL_ID,
            input=_last_user_text(messages),
            output=text[:2000],
            usage_details={
                "input": cache_usage.get("inputTokens", 0) + cache_usage.get("cacheReadInputTokens", 0) + cache_usage.get("cacheWriteInputTokens", 0),
                "output": cache_usage.get("outputTokens", 0),
                "total": cache_usage.get("inputTokens", 0) + cache_usage.get("cacheReadInputTokens", 0) + cache_usage.get("cacheWriteInputTokens", 0) + cache_usage.get("outputTokens", 0),
            },
            prompt=_lf_prompt,
            metadata={"service": _SERVICE},
        )

        # Post-check: run extra guardrails on the full assembled output
        if use_guardrail and len(GUARDRAILS) > 1 and not intervened:
            for gid, ver in GUARDRAILS[1:]:
                blocked = _apply_guardrail(gid, ver, text, "OUTPUT")
                if blocked:
                    print(f"[bedrock-guardrails] OUTPUT blocked by {gid}", file=sys.stderr)
                    print(blocked)
                    return blocked

        return text

    except Exception as e:
        print(f"Bedrock stream async error: {e}", file=sys.stderr)
        return None
