"""list_org_shifts — ADMIN-only: list ALL shifts across the organisation.

Wraps `/organization/shift/list-view/type`. The `type` query param is required
by the backend and is derived from the timeframe input (thisweek / scheduled /
completed) unless the caller passes an explicit shift_type. For "this_week" we
send type=thisweek and skip from/to unless the caller asked for a status that
requires a date window. Supports groupBy=participant/staff for grouped views.
"""
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from config import VERBOSE
from state import user_context, current_timezone
from api_router import call_target_api, construct_api_url
from response_strippers import strip_api_response
from tools.base import ToolSpec, ToolResult


def _user_tz():
    """User's local IANA tz (state-aware). Reads user_context['timezone'],
    falls back to Australia/Sydney. zoneinfo handles DST automatically."""
    return ZoneInfo(current_timezone())


def _aus_to_utc_iso(dt_aus):
    return (
        dt_aus.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    )


def _start_of_day(dt):
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _end_of_day(dt):
    return dt.replace(hour=23, minute=59, second=59, microsecond=999000)


def _timeframe_to_range(timeframe, from_date=None, to_date=None):
    now = datetime.now(_user_tz())
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
    if timeframe == "date_range":
        if not from_date or not to_date:
            return None, None
        try:
            f = datetime.fromisoformat(from_date).replace(tzinfo=_user_tz())
            t = datetime.fromisoformat(to_date).replace(tzinfo=_user_tz())
            return _aus_to_utc_iso(_start_of_day(f)), _aus_to_utc_iso(_end_of_day(t))
        except ValueError:
            return None, None
    return None, None


def _this_week_range_utc():
    now = datetime.now(_user_tz())
    today = _start_of_day(now)
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return _aus_to_utc_iso(monday), _aus_to_utc_iso(_end_of_day(sunday))


def _pick_type_for_timeframe(timeframe, shift_type=None):
    if shift_type in ("draft", "scheduled", "ongoing", "completed", "cancelled", "thisweek"):
        return shift_type
    if timeframe == "this_week":
        return "thisweek"
    if timeframe in ("yesterday", "last_week"):
        return "completed"
    return "scheduled"


def _run(inputs):
    if (user_context.get("user_type") or "").lower() != "admin":
        return ToolResult(
            error="This tool is admin-only.",
            next_hint="Tell the user they need admin permissions to view org-wide shifts.",
        )

    timeframe = (inputs or {}).get("timeframe")
    if not timeframe:
        return ToolResult(error="Missing required input: timeframe.")

    from_date = (inputs or {}).get("from_date")
    to_date = (inputs or {}).get("to_date")
    shift_type = ((inputs or {}).get("shift_type") or "").strip().lower()
    group_by = ((inputs or {}).get("group_by") or "").strip().lower()
    page = (inputs or {}).get("page") or 1
    limit = (inputs or {}).get("limit") or 10

    if timeframe == "date_range" and (not from_date or not to_date):
        return ToolResult(
            error="timeframe=date_range requires both from_date and to_date (YYYY-MM-DD)."
        )

    if VERBOSE:
        print(
            f"[list_org_shifts] timeframe={timeframe} type={shift_type!r} "
            f"group_by={group_by!r}",
            file=sys.stderr,
        )

    path = "/organization/shift/list-view/type"
    query_params = {
        "page": int(page),
        "type": _pick_type_for_timeframe(timeframe, shift_type),
        "limit": int(limit),
    }

    selected_type = query_params["type"]
    from_iso, to_iso = _timeframe_to_range(timeframe, from_date, to_date)
    if timeframe == "this_week" and selected_type != "thisweek":
        from_iso, to_iso = _this_week_range_utc()
    if from_iso and to_iso:
        query_params["from"] = from_iso
        query_params["to"] = to_iso
    if group_by in ("participant", "staff"):
        query_params["groupBy"] = group_by

    url = construct_api_url(path, {})
    raw = call_target_api(method="GET", url=url, query_params=query_params)

    if isinstance(raw, dict) and raw.get("error"):
        return ToolResult(
            error=f"API error from {path}: {raw.get('error')}",
            meta={"status_code": raw.get("status_code"), "path": path},
        )

    stripped = strip_api_response(path, raw, verbose=VERBOSE)
    return ToolResult(
        data=stripped,
        meta={"path": path, "query_params": query_params, "timeframe": timeframe},
    )


TOOL = ToolSpec(
    name="list_org_shifts",
    description=(
        "ADMIN ONLY. List ALL shifts across the organisation (not just the "
        "user's). Use for: 'all shifts in the org', 'org-wide shifts', "
        "'every shift this week', 'all shifts today', 'cancelled shifts grouped "
        "by participant', 'completed shifts grouped by staff'. Supports explicit "
        "shift_type and group_by=participant/staff."
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
                    "date_range",
                ],
                "description": (
                    "Aussie-friendly timeframe. 'arvo' = this afternoon, "
                    "'sarvo' = same as arvo, 'date_range' requires from_date "
                    "and to_date."
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
            "shift_type": {
                "type": "string",
                "enum": ["draft", "scheduled", "ongoing", "completed", "cancelled", "thisweek"],
                "description": (
                    "Optional explicit backend type. Use when the user asks for "
                    "draft, scheduled, ongoing, completed, cancelled, or this-week "
                    "shifts. If omitted, type is derived from timeframe."
                ),
            },
            "group_by": {
                "type": "string",
                "enum": ["participant", "staff"],
                "description": (
                    "Optional grouped view. Use 'participant' for groupBy=participant "
                    "and 'staff' for groupBy=staff."
                ),
            },
            "page": {
                "type": "integer",
                "description": "Page number. Default 1.",
                "minimum": 1,
            },
            "limit": {
                "type": "integer",
                "description": "Records per page. Default 10.",
                "minimum": 1,
                "maximum": 100,
            },
        },
        "required": ["timeframe"],
    },
    run=_run,
)
