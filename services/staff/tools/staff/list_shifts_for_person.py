"""list_shifts_for_person — find shifts attached to a NAMED person.

Backend endpoint: /organization/shift/calendar
   GET with groupBy=staff      → items grouped by staff member, occurrences include each client
   GET with groupBy=participant → items grouped by client participant, occurrences include each staff

We call BOTH variants in parallel so a single person is found regardless of
the role they play on shifts (a coordinator might be staff on most shifts but
also a participant on a service-agreement meeting; a guardian might appear
under participant; etc.).

Recurring shifts are expanded by the backend. Cancelled occurrences come back
with isCancelled=true and we keep them so the agent can show "(cancelled)".

Smart input handling — designed for whatever the user throws at us:
  • Pass `name` exactly as the user said. Backend does case-insensitive
    substring match across first/last/preferred name.
  • Pass timeframe (today / tomorrow / arvo / sarvo / this_week / next_week /
    last_week / this_month / next_month / last_month / date_range) — date math
    happens in the user's local timezone via current_timezone(), UTC-Z is what
    the API gets.
  • date_range needs from_date + to_date as YYYY-MM-DD.
  • If neither timeframe nor from/to are usable, we default to this_week — the
    most common intent ("loki's shifts" almost always means "this week").
"""
import sys
from concurrent.futures import ThreadPoolExecutor

from config import VERBOSE
from state import user_context
from api_router import call_target_api, construct_api_url
from tools.base import ToolSpec, ToolResult

# Reuse the DST-aware date helpers from list_my_shifts. Single source of truth
# for "what UTC range matches this Aussie timeframe?".
from tools.staff.list_my_shifts import (
    _timeframe_to_range,
    _this_week_range_utc,
)


_CALENDAR_PATH = "/organization/shift/calendar"
_DEFAULT_LIMIT = 50


def _fetch_one(group_by: str, search: str, from_iso: str, to_iso: str):
    """Single calendar-view fetch for one groupBy value. Errors come back in
    the {"error": ...} envelope from call_target_api — never raises."""
    params = {
        "from": from_iso,
        "to": to_iso,
        "groupBy": group_by,
        "page": 1,
        "limit": _DEFAULT_LIMIT,
    }
    if search:
        params["search"] = search
    return call_target_api(
        method="GET",
        url=construct_api_url(_CALENDAR_PATH, {}),
        query_params=params,
    )


def _resolve_range(timeframe, from_date, to_date):
    """Map (timeframe, from_date, to_date) → (from_iso_utc, to_iso_utc).

    Falls back to current week when timeframe is missing/unrecognised — better
    than failing on a vague user query like "shifts for loki".
    """
    from_iso, to_iso = _timeframe_to_range(timeframe or "", from_date, to_date)
    if from_iso and to_iso:
        return from_iso, to_iso
    # No usable range derived (e.g. timeframe='this_week' returns (None, None)
    # because callers typically use a dedicated this-week endpoint). For the
    # calendar endpoint we ALWAYS need explicit from/to — compute the Mon→Sun
    # current-week window in the user's local tz.
    return _this_week_range_utc()


def _run(inputs: dict | None) -> ToolResult:
    inputs = inputs or {}
    name = (inputs.get("name") or "").strip()
    timeframe = (inputs.get("timeframe") or "this_week").strip().lower()
    from_date = inputs.get("from_date")
    to_date = inputs.get("to_date")
    show_cancelled = inputs.get("include_cancelled")
    if show_cancelled is None:
        show_cancelled = True  # default: include with isCancelled flag

    if not name:
        return ToolResult(error="Missing required input: name (the person to look up).")

    if timeframe == "date_range" and not (from_date and to_date):
        return ToolResult(
            error="timeframe=date_range needs both from_date and to_date (YYYY-MM-DD).",
        )

    from_iso, to_iso = _resolve_range(timeframe, from_date, to_date)

    if VERBOSE:
        print(
            f"[list_shifts_for_person] name={name!r} timeframe={timeframe} "
            f"from={from_iso} to={to_iso}",
            file=sys.stderr,
        )

    # PARALLEL: groupBy=staff + groupBy=participant. Two calls, ~max-of-2 latency.
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_staff = ex.submit(_fetch_one, "staff", name, from_iso, to_iso)
        f_part = ex.submit(_fetch_one, "participant", name, from_iso, to_iso)
        raw_staff = f_staff.result()
        raw_part = f_part.result()

    # Soft-fail: if BOTH errored, return error. If only one errored, we still
    # have the other half — better partial answer than no answer.
    staff_failed = isinstance(raw_staff, dict) and raw_staff.get("error")
    part_failed = isinstance(raw_part, dict) and raw_part.get("error")
    if staff_failed and part_failed:
        return ToolResult(
            error=f"Both calendar lookups failed: {raw_staff.get('error')}",
            meta={
                "path": _CALENDAR_PATH,
                "name": name,
                "from": from_iso,
                "to": to_iso,
            },
        )

    # Pull cancellation flags up to the meta so the LLM doesn't have to scan
    # for them — quick visibility.
    cancelled_count, total_occurrences, items_found = _count_occurrences(raw_staff, raw_part)

    return ToolResult(
        data={
            "as_staff": raw_staff if not staff_failed else {"items": [], "_note": "groupBy=staff call failed"},
            "as_participant": raw_part if not part_failed else {"items": [], "_note": "groupBy=participant call failed"},
            "name_searched": name,
            "_note": (
                "Two parallel sources from /organization/shift/calendar. "
                "'as_staff' lists shifts where the named person plays the staff "
                "role (each item has the person + their occurrences, each "
                "occurrence has its client). 'as_participant' lists shifts "
                "where the named person is a client participant (each "
                "occurrence has the staff). DEDUPE by shiftId — the same shift "
                "rarely appears in both, but if it does (person is both staff "
                "and a participant on different shifts), show each shift once. "
                "Recurring shifts are already expanded — don't try to re-derive "
                "them. Cancelled occurrences have isCancelled=true; keep them "
                "in the reply but label them clearly (e.g. 'Tue 26 May — "
                "Cancelled'). NEVER mention the two-source design or any "
                "endpoint name to the user."
            ),
        },
        meta={
            "path": _CALENDAR_PATH,
            "groupBy_calls": ["staff", "participant"],
            "name": name,
            "timeframe": timeframe,
            "from": from_iso,
            "to": to_iso,
            "items_found": items_found,
            "total_occurrences": total_occurrences,
            "cancelled_occurrences": cancelled_count,
        },
    )


def _count_occurrences(raw_staff, raw_part):
    """Best-effort count of (cancelled, total, items) across both responses.

    Helps the meta log quickly tell whether we hit data or empty.
    """
    cancelled = 0
    total = 0
    items_found = 0
    for raw in (raw_staff, raw_part):
        if not isinstance(raw, dict):
            continue
        data = raw.get("data")
        if not isinstance(data, dict):
            continue
        items = data.get("items") or []
        items_found += len(items) if isinstance(items, list) else 0
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            for occ in (item.get("occurrences") or []):
                if not isinstance(occ, dict):
                    continue
                total += 1
                if occ.get("isCancelled"):
                    cancelled += 1
    return cancelled, total, items_found


TOOL = ToolSpec(
    name="list_shifts_for_person",
    description=(
        "Find shifts attached to a SPECIFIC named person — staff member, "
        "support worker, ISW, client, participant, or guardian. PREFER THIS "
        "TOOL over `list_my_shifts` whenever the user names a specific person "
        "and asks about their shifts. Uses /organization/shift/calendar with "
        "BOTH groupBy=staff and groupBy=participant in parallel so the person "
        "is found regardless of which role they play. Backend does case-"
        "insensitive name matching. Use for: 'loki's shifts this week', "
        "'shifts for Tanishq next month', 'who are John's clients', 'any "
        "shifts for Sarah tomorrow', 'is Anna rostered today', 'when's "
        "Kareena next on'."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": (
                    "The person's name (or any partial of their name) to "
                    "search for. Pass it exactly as the user said — the "
                    "backend does case-insensitive matching across first / "
                    "last / preferred name."
                ),
            },
            "timeframe": {
                "type": "string",
                "enum": [
                    "today", "tomorrow", "yesterday", "arvo", "sarvo",
                    "this_week", "next_week", "last_week",
                    "this_month", "next_month", "last_month",
                    "date_range",
                ],
                "description": (
                    "Aussie-friendly timeframe, computed in the user's local "
                    "timezone (DST-aware). Defaults to this_week if omitted. "
                    "date_range REQUIRES from_date and to_date."
                ),
            },
            "from_date": {
                "type": "string",
                "description": "ISO date YYYY-MM-DD. Required ONLY if timeframe=date_range.",
            },
            "to_date": {
                "type": "string",
                "description": "ISO date YYYY-MM-DD. Required ONLY if timeframe=date_range.",
            },
            "include_cancelled": {
                "type": "boolean",
                "description": (
                    "Default true. Keep cancelled occurrences in the result "
                    "and label them in the reply. Set false only if the user "
                    "explicitly says 'ignore cancelled' / 'only active shifts'."
                ),
            },
        },
        "required": ["name"],
    },
    run=_run,
)
