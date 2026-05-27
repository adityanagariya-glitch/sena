"""Bedrock model invocation — buffered (`call_bedrock`) and streaming variants.

Use `call_bedrock_stream` for user-facing replies (prints tokens live).
Use `call_bedrock` for JSON-parsing utility calls (intent detection, API routing).
"""
import sys

from config import bedrock_runtime, MODEL_ID, GUARDRAILS, VERBOSE
from guardrails import _last_user_text, _apply_guardrail

# Anthropic prompt caching on Bedrock — Claude Sonnet 4.x supports it. Marking
# the end of a stable prefix with a cachePoint block lets subsequent calls reuse
# the KV cache for ~10% of normal input cost (5-min ephemeral TTL). The minimum
# cached prefix is 1024 tokens (~3-4k chars of English); below that Bedrock
# silently ignores the cachePoint, so the threshold below is just a small
# optimisation to avoid pointless API noise on short system prompts.
_CACHE_MIN_CHARS = 2500


def _build_system_blocks(system_prompt, user_profile=None):
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


def _log_cache_usage(response, label):
    """Emit cache read/write token counts to stderr when VERBOSE is on."""
    if not VERBOSE:
        return
    usage = response.get("usage") or {}
    read = usage.get("cacheReadInputTokens") or usage.get("cache_read_input_tokens") or 0
    write = usage.get("cacheWriteInputTokens") or usage.get("cache_write_input_tokens") or 0
    if read or write:
        print(f"[bedrock-cache] {label} read={read} write={write}", file=sys.stderr)


def call_bedrock_stream(messages, system_prompt=None, use_guardrail=True, user_profile=None):
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


def call_bedrock(messages, system_prompt=None, user_profile=None, use_guardrail=True):
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
