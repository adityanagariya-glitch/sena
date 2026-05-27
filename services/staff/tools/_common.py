"""Shared utilities for all tools — parallelization, caching, dedup.

This module provides reusable helpers for tools that make multiple API calls.
Centralizing these reduces code duplication and ensures consistent logging.
"""
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional

from config import VERBOSE
from api_router import call_target_api

# Terminal-direct stream (matches dispatcher.py pattern)
_TERMINAL = sys.__stderr__


def parallel_fetch(
    fetchers: List[Dict[str, Any]],
    max_workers: Optional[int] = None,
    tool_name: str = "tool",
) -> Dict[str, Any]:
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


def dedup_by_id(records: List[Dict[str, Any]], id_keys: tuple = ("id", "_id", "ID")) -> List[Dict[str, Any]]:
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


def flat_list(d: Dict[str, Any], keys: tuple = ("data", "items", "records", "results", "shifts", "clients", "staff")) -> List[Any]:
    """Extract the first non-empty list from a response dict.

    Handles common SENA envelope patterns. Returns empty list if no list found.
    """
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
    items: List[Any],
    func: Callable[[Any], Any],
    max_workers: Optional[int] = None,
    tool_name: str = "tool",
    item_label: str = "item",
) -> List[Any]:
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
