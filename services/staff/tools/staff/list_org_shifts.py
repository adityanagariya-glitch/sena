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
from tools._common import parallel_fetch, flat_list


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
    if timeframe == "next_month":
        first_of_this_month = today.replace(day=1)
        if first_of_this_month.month == 12:
            first_of_next = first_of_this_month.replace(year=first_of_this_month.year + 1, month=1)
        else:
            first_of_next = first_of_this_month.replace(month=first_of_this_month.month + 1)
        if first_of_next.month == 12:
            first_of_after = first_of_next.replace(year=first_of_next.year + 1, month=1)
        else:
            first_of_after = first_of_next.replace(month=first_of_next.month + 1)
        last_of_next = first_of_after - timedelta(days=1)
        return _aus_to_utc_iso(first_of_next), _aus_to_utc_iso(_end_of_day(last_of_next))
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
    # today/arvo/sarvo fall inside the current week — backend's "scheduled" is
    # future-only and would drop shifts already started today. Same mapping as
    # list_my_shifts; the from/to day-range params narrow the week server-side.
    if timeframe in ("this_week", "today", "arvo", "sarvo"):
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

    # ---- AUTO-ENRICH: Fetch full details for sparse shifts (PARALLEL) ----
    # If shifts have empty staff/client arrays and there are few (<= 5),
    # fetch get_shift_details for each in PARALLEL to give the LLM complete data upfront.
    # This way, when user asks "with whom", we already have the answer.
    enriched_data = stripped
    try:
        shifts_list = flat_list(stripped, keys=("data", "shifts", "items"))

        # Only auto-enrich if we have a reasonable number of shifts to enrich
        if isinstance(shifts_list, list) and 1 <= len(shifts_list) <= 5:
            # Check if shifts look sparse (empty staff/client/title)
            has_sparse = any(
                not s.get("title") or not s.get("staff") or not s.get("client")
                for s in shifts_list
                if isinstance(s, dict)
            )

            if has_sparse:
                if VERBOSE:
                    print(f"[list_org_shifts] Auto-enriching {len(shifts_list)} sparse shifts (parallel)...", file=sys.stderr)

                # Build parallel fetch list for all sparse shifts
                fetchers = []
                shift_ids_to_indices: dict[str, int] = {}
                for idx, shift in enumerate(shifts_list):
                    if isinstance(shift, dict) and shift.get("id"):
                        shift_id = shift["id"]
                        detail_path = "/organization/shift/details/{id}"
                        detail_url = construct_api_url(detail_path, {"id": shift_id})
                        fetchers.append({
                            "label": f"shift_{shift_id}",
                            "url": detail_url,
                            "method": "GET",
                        })
                        shift_ids_to_indices[f"shift_{shift_id}"] = idx

                # Fetch all shift details in parallel
                if fetchers:
                    detail_responses = parallel_fetch(fetchers, tool_name="list_org_shifts")

                    # Merge detail data into shifts
                    enriched_shifts = list(shifts_list)  # Start with copies
                    for label, detail_response in detail_responses.items():
                        idx = shift_ids_to_indices.get(label)
                        if idx is not None and isinstance(detail_response, dict):
                            if not detail_response.get("error"):
                                detail_data = detail_response.get("data", detail_response)
                                merged = {**enriched_shifts[idx], **detail_data}
                                enriched_shifts[idx] = merged

                    # Replace data with enriched version
                    if isinstance(enriched_data, dict) and "data" in enriched_data:
                        enriched_data["data"] = enriched_shifts
    except Exception as e:
        if VERBOSE:
            print(f"[list_org_shifts] Auto-enrich failed (non-fatal): {e}", file=sys.stderr)
        # Silently fall back to original data

    return ToolResult(
        data=enriched_data,
        meta={
            "path": path,
            "query_params": query_params,
            "timeframe": timeframe,
            "auto_enriched": True if enriched_data != stripped else False,
        },
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
                    "next_month",
                    "date_range",
                ],
                "description": (
                    "Aussie-friendly timeframe. 'arvo' = this afternoon, "
                    "'sarvo' = same as arvo, 'next_month' = next calendar month, "
                    "'date_range' requires from_date and to_date."
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
