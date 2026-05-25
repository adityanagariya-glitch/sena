"""list_my_shifts — list the logged-in user's own shifts (persona-routed).

Routing rules:
- user_type == "isw"                       → /mobile/isw-shift/all-shifts (new mobile)
- user_type == "client"                    → /mobile/client-shift/this-week-shifts | all-shifts
- staff_type == "support_worker" or
  user_type == "staff"                     → /mobile/staff-shift/this-week-shifts | all-shifts
- user_type == "admin"                     → /organization-member/shift/list-view

Mobile `all-shifts` endpoints accept:
- `type` (required): allshift | available | accepted | completed
- `startDate` / `endDate` (UTC ISO with Z)
- `search` (string): shift title / staff name / client name (case-insensitive)
- `page`, `limit`: pagination
- `userLat`, `userLng`: optional, computes distance to shift

DST: dates are computed in Australia/Sydney via zoneinfo (correctly handles
AEDT/AEST transition each Oct/Apr) then converted to UTC with the literal "Z"
suffix that the backend expects.
"""
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from config import VERBOSE
from state import user_context
from api_router import call_target_api, construct_api_url
from response_strippers import strip_api_response
from tools.base import ToolSpec, ToolResult


# Australia/Sydney is the canonical NDIS timezone. zoneinfo handles DST
# transitions automatically — AEDT (UTC+11) Oct–Apr, AEST (UTC+10) Apr–Oct.
_AUS_TZ = ZoneInfo("Australia/Sydney")


def _aus_to_utc_iso(dt_aus):
    """Convert an aware Australia/Sydney datetime to UTC ISO with Z suffix.

    The `astimezone(timezone.utc)` call respects the DST state encoded in the
    Sydney tzinfo, so 2026-01-15 noon Sydney → 01:00Z (AEDT/+11) while
    2026-07-15 noon Sydney → 02:00Z (AEST/+10).
    """
    return (
        dt_aus.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    )


def _start_of_day(dt):
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _end_of_day(dt):
    return dt.replace(hour=23, minute=59, second=59, microsecond=999000)


def _parse_aus_date(date_str):
    """Parse an ISO date string and attach Australia/Sydney tz (DST-aware).

    Using `.replace(tzinfo=_AUS_TZ)` with a zoneinfo zone is correct — zoneinfo
    computes the right UTC offset based on the date itself (no manual DST math).
    """
    return datetime.fromisoformat(date_str).replace(tzinfo=_AUS_TZ)


def _timeframe_to_range(timeframe, from_date=None, to_date=None):
    """Return (from_iso_utc, to_iso_utc) for a timeframe.

    Returns (None, None) for "this_week" — callers using `this-week-shifts`
    endpoints don't need date params; callers using `all-shifts` should still
    compute the explicit range from the current Monday→Sunday window.
    """
    now = datetime.now(_AUS_TZ)
    today = _start_of_day(now)

    if timeframe == "this_week":
        return None, None

    if timeframe == "today":
        return _aus_to_utc_iso(today), _aus_to_utc_iso(_end_of_day(today))

    if timeframe == "tomorrow":
        d = today + timedelta(days=1)
        return _aus_to_utc_iso(d), _aus_to_utc_iso(_end_of_day(d))

    if timeframe == "yesterday":
        d = today - timedelta(days=1)
        return _aus_to_utc_iso(d), _aus_to_utc_iso(_end_of_day(d))

    if timeframe in ("arvo", "sarvo"):
        start = today.replace(hour=12, minute=0, second=0, microsecond=0)
        return _aus_to_utc_iso(start), _aus_to_utc_iso(_end_of_day(today))

    if timeframe == "next_week":
        days_until_monday = (7 - today.weekday()) % 7 or 7
        monday = today + timedelta(days=days_until_monday)
        sunday = monday + timedelta(days=6)
        return _aus_to_utc_iso(monday), _aus_to_utc_iso(_end_of_day(sunday))

    if timeframe == "last_week":
        monday_this_week = today - timedelta(days=today.weekday())
        last_monday = monday_this_week - timedelta(days=7)
        last_sunday = last_monday + timedelta(days=6)
        return _aus_to_utc_iso(last_monday), _aus_to_utc_iso(_end_of_day(last_sunday))

    if timeframe == "this_month":
        first_of_month = today.replace(day=1)
        if first_of_month.month == 12:
            next_month_first = first_of_month.replace(year=first_of_month.year + 1, month=1)
        else:
            next_month_first = first_of_month.replace(month=first_of_month.month + 1)
        last_of_month = next_month_first - timedelta(days=1)
        return _aus_to_utc_iso(first_of_month), _aus_to_utc_iso(_end_of_day(last_of_month))

    if timeframe == "next_month":
        first_of_this_month = today.replace(day=1)
        if first_of_this_month.month == 12:
            first_of_next = first_of_this_month.replace(year=first_of_this_month.year + 1, month=1)
        else:
            first_of_next = first_of_this_month.replace(month=first_of_this_month.month + 1)
        # End of next month
        if first_of_next.month == 12:
            first_after_next = first_of_next.replace(year=first_of_next.year + 1, month=1)
        else:
            first_after_next = first_of_next.replace(month=first_of_next.month + 1)
        last_of_next = first_after_next - timedelta(days=1)
        return _aus_to_utc_iso(first_of_next), _aus_to_utc_iso(_end_of_day(last_of_next))

    if timeframe == "last_month":
        first_of_this_month = today.replace(day=1)
        if first_of_this_month.month == 1:
            first_of_last = first_of_this_month.replace(year=first_of_this_month.year - 1, month=12)
        else:
            first_of_last = first_of_this_month.replace(month=first_of_this_month.month - 1)
        last_of_last = first_of_this_month - timedelta(days=1)
        return _aus_to_utc_iso(first_of_last), _aus_to_utc_iso(_end_of_day(last_of_last))

    if timeframe == "date_range":
        if not from_date or not to_date:
            return None, None
        try:
            f = _parse_aus_date(from_date)
            t = _parse_aus_date(to_date)
            return _aus_to_utc_iso(_start_of_day(f)), _aus_to_utc_iso(_end_of_day(t))
        except ValueError:
            return None, None

    return None, None


def _this_week_range_utc():
    """Explicit current-week range in UTC (Mon 00:00 → Sun 23:59 AUS)."""
    now = datetime.now(_AUS_TZ)
    today = _start_of_day(now)
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return _aus_to_utc_iso(monday), _aus_to_utc_iso(_end_of_day(sunday))


def _pick_mobile_type(timeframe, shift_filter):
    """Map (timeframe, shift_filter) → mobile `type` query value.

    Mobile endpoints accept: allshift, available, accepted, completed.
    Explicit filter wins; otherwise default to allshift, with `completed` for
    past timeframes if user clearly wants past shifts.
    """
    if shift_filter and shift_filter in ("allshift", "available", "accepted", "completed"):
        return shift_filter
    if timeframe in ("yesterday", "last_week", "last_month"):
        return "completed"
    return "allshift"


def _run(inputs):
    inputs = inputs or {}
    timeframe = inputs.get("timeframe")
    if not timeframe:
        return ToolResult(error="Missing required input: timeframe.")

    from_date = inputs.get("from_date")
    to_date = inputs.get("to_date")
    search = (inputs.get("search") or "").strip()
    shift_filter = (inputs.get("shift_filter") or "").strip().lower()

    if timeframe == "date_range" and (not from_date or not to_date):
        return ToolResult(
            error="timeframe=date_range requires both from_date and to_date (YYYY-MM-DD)."
        )

    user_type = (user_context.get("user_type") or "").lower()
    staff_type = (user_context.get("staff_type") or "").lower()

    if VERBOSE:
        print(
            f"[list_my_shifts] timeframe={timeframe} user_type={user_type} "
            f"staff_type={staff_type} search={search!r} filter={shift_filter!r}",
            file=sys.stderr,
        )

    from_iso, to_iso = _timeframe_to_range(timeframe, from_date, to_date)
    mobile_type = _pick_mobile_type(timeframe, shift_filter)

    # ---- Persona routing ----
    if user_type == "isw":
        # Use the new mobile all-shifts endpoint (replaces /isw/shift/list-view)
        path = "/mobile/isw-shift/all-shifts"
        query_params = {"type": mobile_type}
        if from_iso and to_iso:
            query_params["startDate"] = from_iso
            query_params["endDate"] = to_iso
        elif timeframe == "this_week":
            sd, ed = _this_week_range_utc()
            query_params["startDate"] = sd
            query_params["endDate"] = ed

    elif user_type == "client":
        if timeframe == "this_week" and not (search or shift_filter):
            # Fast path: dedicated this-week endpoint
            path = "/mobile/client-shift/this-week-shifts"
            query_params = {}
        else:
            path = "/mobile/client-shift/all-shifts"
            query_params = {"type": mobile_type}
            if from_iso and to_iso:
                query_params["startDate"] = from_iso
                query_params["endDate"] = to_iso
            elif timeframe == "this_week":
                sd, ed = _this_week_range_utc()
                query_params["startDate"] = sd
                query_params["endDate"] = ed

    elif staff_type == "support_worker" or user_type == "staff":
        if timeframe == "this_week" and not (search or shift_filter):
            path = "/mobile/staff-shift/this-week-shifts"
            query_params = {}
        else:
            path = "/mobile/staff-shift/all-shifts"
            query_params = {"type": mobile_type}
            if from_iso and to_iso:
                query_params["startDate"] = from_iso
                query_params["endDate"] = to_iso
            elif timeframe == "this_week":
                sd, ed = _this_week_range_utc()
                query_params["startDate"] = sd
                query_params["endDate"] = ed

    elif user_type == "admin":
        path = "/organization-member/shift/list-view"
        # admin endpoint uses `from`/`to` not startDate/endDate
        query_params = {}
        if from_iso and to_iso:
            query_params["from"] = from_iso
            query_params["to"] = to_iso
        elif timeframe == "this_week":
            sd, ed = _this_week_range_utc()
            query_params["from"] = sd
            query_params["to"] = ed

    else:
        return ToolResult(
            error=(
                f"Unsupported persona for list_my_shifts: user_type={user_type!r}, "
                f"staff_type={staff_type!r}."
            )
        )

    # Append search if provided and endpoint supports it (mobile all-shifts variants)
    if search and "all-shifts" in path:
        query_params["search"] = search

    url = construct_api_url(path, {})
    raw = call_target_api(method="GET", url=url, query_params=query_params)

    if isinstance(raw, dict) and raw.get("error"):
        return ToolResult(
            error=f"API error from {path}: {raw.get('error')}",
            meta={"status_code": raw.get("status_code"), "path": path},
        )

    # Bypass stripper — backend field names vary across personas/endpoints and
    # the stripper was returning mostly nulls. LLM handles raw JSON fine.
    return ToolResult(
        data=raw,
        meta={"path": path, "query_params": query_params, "timeframe": timeframe},
    )


TOOL = ToolSpec(
    name="list_my_shifts",
    description=(
        "List the user's own shifts. Handles persona-specific routing "
        "automatically (ISW → /mobile/isw-shift/*, support worker → "
        "/mobile/staff-shift/*, client → /mobile/client-shift/*, admin → "
        "/organization-member/shift/list-view). Use for: 'my shifts', 'shifts "
        "today', 'shifts tomorrow', 'shifts tomoz', 'arvo shift', 'sarvo', "
        "'next shift', 'next gig', 'what's on tomorrow', 'where do i go', "
        "'who am i with', 'am i free thursday', 'this week', 'last week', "
        "'shifts with Sarah' (pass search='Sarah'), 'available shifts' "
        "(pass shift_filter='available')."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "timeframe": {
                "type": "string",
                "enum": [
                    "today",
                    "tomorrow",
                    "yesterday",
                    "arvo",
                    "sarvo",
                    "this_week",
                    "next_week",
                    "last_week",
                    "this_month",
                    "next_month",
                    "last_month",
                    "date_range",
                ],
                "description": (
                    "Aussie-friendly timeframe. 'arvo' = this afternoon, "
                    "'sarvo' = same as arvo, 'date_range' requires from_date "
                    "and to_date. Computed in Australia/Sydney (DST-aware)."
                ),
            },
            "from_date": {
                "type": "string",
                "description": (
                    "ISO date YYYY-MM-DD (Australian timezone). Required "
                    "only if timeframe=date_range."
                ),
            },
            "to_date": {
                "type": "string",
                "description": (
                    "ISO date YYYY-MM-DD. Required only if timeframe=date_range."
                ),
            },
            "search": {
                "type": "string",
                "description": (
                    "Optional: filter shifts by title / staff name / client "
                    "name (case-insensitive, backend matches). Use when the "
                    "user mentions a name with their shift query, e.g. "
                    "'shifts with Sarah next week'."
                ),
            },
            "shift_filter": {
                "type": "string",
                "enum": ["allshift", "available", "accepted", "completed"],
                "description": (
                    "Optional acknowledgement/status filter. 'allshift' "
                    "(default for current/future), 'available' (unacknowledged), "
                    "'accepted' (acknowledged), 'completed' (past completed). "
                    "Past timeframes default to 'completed' automatically."
                ),
            },
        },
        "required": ["timeframe"],
    },
    run=_run,
)
