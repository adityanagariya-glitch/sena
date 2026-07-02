"""Shared utilities for all tools — parallelization, caching, dedup.

This module provides reusable helpers for tools that make multiple API calls.
Centralizing these reduces code duplication and ensures consistent logging.
"""
import asyncio
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from config import VERBOSE
from api_router import call_target_api

# Terminal-direct stream (matches dispatcher.py pattern)
_TERMINAL = sys.__stderr__


# ---- HTTP error framing ----
# The agent kept telling users "temporary glitch, try again in a few minutes"
# for failures that are PERMANENT (a 403 never clears by waiting). The fix is to
# hand the model the right framing per status class instead of letting it guess:
#   4xx (except 429) → permanent, do NOT promise a retry will work
#   429 / 5xx        → genuinely transient, a retry IS reasonable
ACCESS_DENIED_CODES = (401, 403)

ACCESS_DENIED_HINT = (
    "This is a PERMISSION denial (the signed-in user isn't authorised for this "
    "data), NOT a temporary outage. Tell the user plainly that they don't have "
    "access and may need an admin to grant it. Do NOT call it a glitch, do NOT "
    "say it's temporary, and do NOT suggest trying again in a few minutes — "
    "retrying will not help."
)


def access_denied_code(*responses: Any) -> int | None:
    """Return 401/403 if any raw API envelope carries an auth-denial status code.

    Accepts the dicts returned by `call_target_api` (or anything else, which is
    ignored). Returns the first matching code, or None when no envelope denied.
    """
    for r in responses:
        if isinstance(r, dict) and r.get("status_code") in ACCESS_DENIED_CODES:
            return r["status_code"]
    return None


def error_hint_for_status(code: int | None) -> str | None:
    """Map a backend HTTP error code → instruction for HOW the agent explains it.

    Returns None for success/unknown codes (agent uses its default handling).
    Only error codes get a hint; the framing is the whole point of this helper.
    """
    if code is None or code < 400:
        return None
    if code == 401:
        return (
            "The user's session is no longer valid — this is NOT a glitch. Tell "
            "them they may need to sign in again. Do NOT say it's temporary or "
            "that retrying in a few minutes will fix it."
        )
    if code == 403:
        return ACCESS_DENIED_HINT
    if code == 404:
        return (
            "The requested record doesn't exist. Tell the user it couldn't be "
            "found. Do NOT call it an outage and do NOT suggest retrying — the "
            "record isn't there. If an id/name/date might be wrong, ask them to confirm it."
        )
    if code in (400, 422):
        return (
            "The request was rejected as invalid (a problem with how the lookup "
            "was built, not a temporary outage). Tell the user you couldn't "
            "complete that request. Do NOT tell them to try again in a few "
            "minutes — the same request will fail again. If a detail (name, "
            "date, id) might be off, ask them to confirm it."
        )
    if code == 429:
        return (
            "Rate limited — this one IS temporary. It's fine to tell the user the "
            "system is busy and to try again shortly."
        )
    if 500 <= code <= 599:
        return (
            "Genuine server-side error. This is temporary — it's fine to tell the "
            "user there was a hiccup and to try again in a little while."
        )
    # Other 4xx: treat as permanent client errors, don't promise a retry.
    return (
        "The request failed and won't succeed if simply repeated. Tell the user "
        "you couldn't complete it; do NOT say it's a temporary glitch."
    )


def unknown_user_type_result() -> "ToolResult":
    """Standard ToolResult for when /auth/user-type returned non-200 and the
    user's role is unknown. JWT is valid — account just isn't configured yet.

    Import and return this in any tool that needs role-specific routing but
    can't resolve the user's type. Roles are optional; a valid JWT always gets
    through — this is only used where routing genuinely can't proceed without
    knowing the role.
    """
    from tools.base import ToolResult  # local import avoids circular deps
    return ToolResult(
        error="User account type could not be determined from the backend.",
        next_hint=(
            "The user's JWT is valid but /auth/user-type returned no role. "
            "Tell them: 'Your account doesn't seem to have a role set up in "
            "SENA yet — please contact your organisation admin to confirm your "
            "account is fully configured.' Do NOT say their session expired."
        ),
        meta={"user_type": "unknown", "status_code": 401},
    )


def parallel_fetch(
    fetchers: list[dict[str, Any]],
    max_workers: int | None = None,
    tool_name: str = "tool",
) -> dict[str, Any]:
    """Run multiple API calls in parallel. Thread-safe + logs to terminal.

    Args:
        fetchers: List of dicts, each with:
            - "label": str (identifier, e.g., "shifts_staff")
            - "url": str (full URL)
            - "params": dict (query params, optional)
            - "method": str (GET/POST/PUT/DELETE, default GET)

        max_workers: Max concurrent threads (default: len(fetchers), capped at 20)
        tool_name: Tool name for logging context (e.g., "list_my_shifts")

    Returns:
        Dict mapping label → API response. On error, response includes {"error": ...}.
    """
    if not fetchers:
        return {}

    max_workers = max_workers or min(len(fetchers), 20)
    t0 = time.time()

    # Log the parallel batch start
    labels = [f["label"] for f in fetchers]
    print(
        f"[{tool_name}] ▶ parallel batch  fetchers={len(fetchers)}  labels={labels}",
        file=_TERMINAL,
        flush=True,
    )

    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {}
        for fetcher in fetchers:
            label = fetcher["label"]
            url = fetcher["url"]
            params = fetcher.get("params") or {}
            method = fetcher.get("method", "GET").upper()

            fut = ex.submit(
                call_target_api,
                method=method,
                url=url,
                query_params=params if method == "GET" else None,
                body_params=params if method in ("POST", "PUT") else None,
            )
            futures[fut] = label

        # Collect results as they complete (not in submission order)
        for fut in as_completed(futures):
            label = futures[fut]
            try:
                results[label] = fut.result()
            except Exception as e:
                results[label] = {"error": str(e), "status_code": 0}

    elapsed_ms = int((time.time() - t0) * 1000)
    success_count = sum(1 for r in results.values() if not isinstance(r, dict) or not r.get("error"))
    error_count = len(results) - success_count

    status_emoji = "✓" if error_count == 0 else "⚠" if success_count > 0 else "✗"
    print(
        f"[{tool_name}] {status_emoji} parallel batch done  ({elapsed_ms}ms)  "
        f"ok={success_count}  err={error_count}",
        file=_TERMINAL,
        flush=True,
    )

    return results


def dedup_by_id(records: list[dict[str, Any]], id_keys: tuple = ("id", "_id", "ID")) -> list[dict[str, Any]]:
    """Remove duplicate records by ID. Keeps first occurrence.

    Args:
        records: List of dicts
        id_keys: Keys to check for IDs, in priority order

    Returns:
        Deduplicated list
    """
    seen = set()
    deduped = []
    for record in records:
        if not isinstance(record, dict):
            deduped.append(record)
            continue

        rid = None
        for key in id_keys:
            if key in record:
                rid = record[key]
                break

        if rid is None:
            deduped.append(record)
        elif rid not in seen:
            seen.add(rid)
            deduped.append(record)

    return deduped


def flat_list(d: dict[str, Any] | list | None, keys: tuple = ("data", "items", "records", "results", "shifts", "clients", "staff")) -> list[Any]:
    """Extract the first non-empty list from a response dict.

    Handles common SENA envelope patterns. Returns empty list if no list found.
    """
    if d is None:
        return []
    if isinstance(d, list):
        return d
    if not isinstance(d, dict):
        return []

    for key in keys:
        val = d.get(key)
        if isinstance(val, list):
            return val

    return []


def parallel_map(
    items: list[Any],
    func: Callable[[Any], Any],
    max_workers: int | None = None,
    tool_name: str = "tool",
    item_label: str = "item",
) -> list[Any]:
    """Apply a function to items in parallel (e.g., fetch each ID from a list).

    Args:
        items: List of items to process
        func: Callable that takes one item and returns a result (or None on error)
        max_workers: Max concurrent threads (default: min(len(items), 20))
        tool_name: Tool name for logging (e.g., "filter_clients")
        item_label: Label for logging (e.g., "client_ids")

    Returns:
        List of non-None results (filtered)
    """
    if not items:
        return []

    max_workers = max_workers or min(len(items), 20)
    t0 = time.time()

    print(
        f"[{tool_name}] ▶ parallel map  {item_label}={len(items)}",
        file=_TERMINAL,
        flush=True,
    )

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(func, item) for item in items]

        success_count = 0
        for fut in as_completed(futures):
            result = fut.result()
            if result is not None:
                results.append(result)
                success_count += 1

    elapsed_ms = int((time.time() - t0) * 1000)
    print(
        f"[{tool_name}] ✓ parallel map done  ({elapsed_ms}ms)  collected={success_count}/{len(items)}",
        file=_TERMINAL,
        flush=True,
    )

    return results


# ---- Async Variants (for Phase 3A parallelization) ----

async def parallel_fetch_async(
    fetchers: list[dict[str, Any]],
    max_workers: int | None = None,
    tool_name: str = "tool",
) -> dict[str, Any]:
    """Async variant of parallel_fetch using asyncio.gather for concurrent API calls."""
    if not fetchers:
        return {}

    max_workers = max_workers or min(len(fetchers), 20)
    t0 = time.time()

    # Log the parallel batch start
    labels = [f["label"] for f in fetchers]
    print(
        f"[{tool_name}] ▶ async parallel batch  fetchers={len(fetchers)}  labels={labels}",
        file=_TERMINAL,
        flush=True,
    )

    # Create async tasks for each fetcher
    async def fetch_one(fetcher: dict[str, Any]) -> tuple[str, Any]:
        label = fetcher["label"]
        url = fetcher["url"]
        params = fetcher.get("params") or {}
        method = fetcher.get("method", "GET").upper()

        result = await asyncio.to_thread(
            call_target_api,
            method=method,
            url=url,
            query_params=params if method == "GET" else None,
            body_params=params if method in ("POST", "PUT") else None,
        )
        return label, result

    # Run all fetches in parallel
    tasks = [fetch_one(f) for f in fetchers]
    results_list = await asyncio.gather(*tasks, return_exceptions=True)

    # Assemble results dict
    results = {}
    success_count = 0
    for item in results_list:
        if isinstance(item, Exception):
            # Handle exception from gather
            continue
        label, result = item
        if isinstance(result, dict) and not result.get("error"):
            success_count += 1
        results[label] = result

    elapsed_ms = int((time.time() - t0) * 1000)
    error_count = len(results) - success_count

    status_emoji = "✓" if error_count == 0 else "⚠" if success_count > 0 else "✗"
    print(
        f"[{tool_name}] {status_emoji} async parallel batch done  ({elapsed_ms}ms)  "
        f"ok={success_count}  err={error_count}",
        file=_TERMINAL,
        flush=True,
    )

    return results


async def parallel_map_async(
    items: list[Any],
    func: Callable[[Any], Any],
    max_workers: int | None = None,
    tool_name: str = "tool",
    item_label: str = "item",
) -> list[Any]:
    """Async variant of parallel_map using asyncio.gather."""
    if not items:
        return []

    t0 = time.time()

    print(
        f"[{tool_name}] ▶ async parallel map  {item_label}={len(items)}",
        file=_TERMINAL,
        flush=True,
    )

    # Create async tasks for each item
    async def map_one(item: Any) -> Any | None:
        return await asyncio.to_thread(func, item)

    tasks = [map_one(item) for item in items]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Filter out None results and exceptions
    filtered = [r for r in results if r is not None and not isinstance(r, Exception)]
    success_count = len(filtered)

    elapsed_ms = int((time.time() - t0) * 1000)
    print(
        f"[{tool_name}] ✓ async parallel map done  ({elapsed_ms}ms)  collected={success_count}/{len(items)}",
        file=_TERMINAL,
        flush=True,
    )

    return filtered
