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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from config import VERBOSE
from state import user_context, current_timezone
from api_router import call_target_api, construct_api_url
from response_strippers import strip_api_response
from tools.base import ToolSpec, ToolResult


# Persona → clients-reference endpoint. We pair each shift fetch with the
# clients endpoint the user has access to, so the LLM can cross-reference
# client_id mentions in shift records when the shift response is sparse.
# Cached at the api_router layer (10 min), so repeat shift queries get
# the clients data nearly free.
def _clients_ref_path_for_user():
    """Return the clients-reference path appropriate for the current user,
    or None if cross-referencing doesn't apply (e.g. client persona — they
    don't have a list of OTHER clients).
    """
    user_type = (user_context.get("user_type") or "").lower()
    staff_type = (user_context.get("staff_type") or "").lower()
    roles = [r.lower() for r in (user_context.get("roles") or [])]

    if user_type == "client":
        # Participant viewing their own shifts — no "other clients" reference.
        return None
    if user_type == "admin":
        return "/organization/client/list/all-clients"
    if "guardian" in roles or user_type == "guardian":
        return "/mobile/visitor/clients"
    if user_type == "isw" or staff_type == "support_worker" or user_type == "staff":
        return "/mobile/visitor/clients"
    return None  # unknown persona — skip enrichment


def _calendar_view_path_for_user():
    """Return the persona-appropriate calendar-view endpoint, or None.

    Each persona has a `calendar-view` endpoint that returns shift occurrences
    in a given UTC range (defaults to current week). This is a parallel/fallback
    source — if the primary shift endpoint returns empty, the calendar-view may
    still have data. Same bug pattern as the admin case, applied to every persona.
    """
    user_type = (user_context.get("user_type") or "").lower()
    staff_type = (user_context.get("staff_type") or "").lower()
    roles = [r.lower() for r in (user_context.get("roles") or [])]

    if user_type == "client" or "guardian" in roles or user_type == "guardian":
        return "/mobile/client-shift/calendar-view"
    if user_type == "isw":
        return "/mobile/isw-shift/calendar-view"
    if staff_type == "support_worker" or user_type == "staff":
        return "/mobile/staff-shift/calendar-view"
    # Admin uses /organization-member/shift/calendar-view — already wired
    # in the admin branch above.
    return None


def _extract_occurrences(raw):
    """Pull shift occurrences out of ANY of the shapes the shift endpoints
    return. Returns a flat list of shift dicts.

    Handles:
      • Flat list at data.data          → /organization/shift/list-view/type
      • Flat list at top-level data     → calendar-view (data=[...])
      • Person-grouped with nested
        occurrences/shifts arrays       → /organization/shift/staff/* + /clients
                                          and /organization/shift/calendar
    """
    if not isinstance(raw, dict) or raw.get("error"):
        return []

    data = raw.get("data")

    # Shape A: data is already a flat list of shift records
    if isinstance(data, list):
        records = data
    # Shape B/C: data is a dict — could hold a flat list under data.data,
    # or person-grouped items under data.items / data.data
    elif isinstance(data, dict):
        records = (
            data.get("data")
            or data.get("items")
            or data.get("shifts")
            or data.get("records")
            or []
        )
        if not isinstance(records, list):
            records = []
    else:
        return []

    out = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        # If this record itself looks like a shift (has a start time / shiftId),
        # take it directly.
        if any(k in rec for k in ("startTime", "startDate", "from", "startAt")) or \
           any(k in rec for k in ("shiftId", "id")) and any(k in rec for k in ("title", "endTime", "endDate")):
            out.append(rec)
            continue
        # Otherwise it's a person-grouped item → dig into the nested shifts.
        nested = (
            rec.get("occurrences")
            or rec.get("shifts")
            or rec.get("entries")
            or rec.get("events")
            or []
        )
        if isinstance(nested, list):
            for occ in nested:
                if isinstance(occ, dict):
                    out.append(occ)
    return out


def _shift_dedupe_key(shift):
    """Stable key to dedupe a shift across multiple sources. Prefer shiftId;
    fall back to id; finally a (start,end,title) tuple."""
    sid = shift.get("shiftId") or shift.get("id") or shift.get("_id")
    if sid:
        # Include the date so recurring-template expansions on different days
        # aren't collapsed into one.
        day = shift.get("date") or (shift.get("startTime") or "")[:10]
        return f"{sid}|{day}"
    start = shift.get("startTime") or shift.get("startDate") or shift.get("from") or ""
    end = shift.get("endTime") or shift.get("endDate") or shift.get("to") or ""
    title = shift.get("title") or shift.get("name") or ""
    return f"{start}|{end}|{title}"


def _merge_and_dedupe_shifts(results, shift_keys):
    """Flatten every shift source into one deduped list of shift dicts.

    `results` is the dict returned by _fetch_parallel; `shift_keys` the labels
    that hold shift data. Returns (merged_list, per_source_counts)."""
    seen = {}
    per_source = {}
    for key in shift_keys:
        raw = results.get(key)
        occs = _extract_occurrences(raw)
        per_source[key] = len(occs)
        for occ in occs:
            dk = _shift_dedupe_key(occ)
            if dk not in seen:
                seen[dk] = occ
    return list(seen.values()), per_source


def _fetch_parallel(fetchers):
    """Run multiple API calls concurrently. Each fetcher is a dict:
        {"label": <str>, "url": <str>, "params": <dict>}

    Returns {label: response_dict} for every fetcher.
    """
    if not fetchers:
        return {}
    with ThreadPoolExecutor(max_workers=len(fetchers)) as ex:
        futures = {
            ex.submit(call_target_api, method="GET", url=f["url"], query_params=f.get("params") or {}): f["label"]
            for f in fetchers
        }
        results = {}
        for fut, label in list(futures.items()):
            try:
                results[label] = fut.result()
            except Exception as e:
                results[label] = {"error": str(e), "status_code": 0}
        return results


# Six mobile shift endpoints total: 3 all-shifts (with date-range + filters)
# and 3 this-week-shifts (fast path, no params). All three this-week-shifts
# endpoints take no params; all three all-shifts share the same param shape:
#   type (required): allshift | available | accepted | completed
#   startDate / endDate: full UTC ISO datetime
#   search, page, limit, userLat, userLng
_MOBILE_ALL_SHIFTS_PATHS = [
    "/mobile/staff-shift/all-shifts",   # field / support-worker shifts
    "/mobile/isw-shift/all-shifts",     # ISW shifts
    "/mobile/client-shift/all-shifts",  # participant's own shifts
]

_MOBILE_THIS_WEEK_PATHS = [
    "/mobile/staff-shift/this-week-shifts",
    "/mobile/isw-shift/this-week-shifts",
    "/mobile/client-shift/this-week-shifts",
]


def _build_mobile_shifts_params(timeframe, from_iso, to_iso, mobile_type, search):
    """Build the params dict accepted by any /mobile/*-shift/all-shifts endpoint."""
    params = {"type": mobile_type}
    if from_iso and to_iso:
        params["startDate"] = from_iso
        params["endDate"] = to_iso
    elif timeframe == "this_week":
        sd, ed = _this_week_range_utc()
        params["startDate"] = sd
        params["endDate"] = ed
    if search:
        params["search"] = search
    return params


def _shift_source_label(path: str) -> str:
    """Build a friendly label from a shift path, e.g.
    '/mobile/staff-shift/all-shifts' → 'shifts_staff'.
    Works for both all-shifts and this-week-shifts variants."""
    # path segment 2 is e.g. 'staff-shift' / 'isw-shift' / 'client-shift'
    segment = path.split('/')[2]
    return f"shifts_{segment.replace('-shift', '')}"


# Endpoints the SENA UI itself calls on the Shifts page (confirmed from the
# browser network tab). These are the actual source of truth for shifts the
# UI shows — the descriptions in the JSON spec ("for shift participant
# picker") are misleading. We query them in parallel alongside the other
# shift stores so the agent finds shifts wherever the UI does.
_ORG_SHIFT_VIEW_PATHS = [
    "/organization/shift/staff/in-office",
    "/organization/shift/staff/support-worker",
    "/organization/shift/clients",
]


def _org_shift_view_fetchers(search):
    """Fetchers for the 3 UI-confirmed org shift endpoints. Same param shape
    across all three (page / limit / search). We pull page 1 with a generous
    limit; downstream merging dedupes by shift id."""
    params = {"page": 1, "limit": 50}
    if search:
        params["search"] = search
    return [
        {
            "label": f"shifts_org_{path.rsplit('/', 1)[-1].replace('-', '_')}",  # e.g. shifts_org_in_office
            "url": construct_api_url(path, {}),
            "params": dict(params),
        }
        for path in _ORG_SHIFT_VIEW_PATHS
    ]


def _all_mobile_shift_fetchers(timeframe, from_iso, to_iso, mobile_type, search, shift_filter):
    """Return fetcher dicts for all three mobile shift stores.

    Uses the fast `this-week-shifts` endpoints when timeframe is this_week
    AND no search/filter (those endpoints take no params). Otherwise uses the
    `all-shifts` endpoints with full date-range + type + search params.

    Admin / in-office staff can plausibly have shifts in any of these stores
    — field work (staff-shift), ISW work (isw-shift), or services received
    (client-shift). Querying all three in parallel costs ~max-of-three
    latency and catches every store.
    """
    use_this_week_fast_path = (
        timeframe == "this_week" and not (search or shift_filter)
    )

    if use_this_week_fast_path:
        return [
            {
                "label": _shift_source_label(path),
                "url": construct_api_url(path, {}),
                "params": {},
            }
            for path in _MOBILE_THIS_WEEK_PATHS
        ]

    params = _build_mobile_shifts_params(timeframe, from_iso, to_iso, mobile_type, search)
    return [
        {
            "label": _shift_source_label(path),
            "url": construct_api_url(path, {}),
            "params": dict(params),
        }
        for path in _MOBILE_ALL_SHIFTS_PATHS
    ]


def _user_tz():
    """Return the user's IANA timezone as a ZoneInfo. Reads from user_context
    (set by frontend), falls back to Australia/Sydney. zoneinfo handles DST
    automatically for every AUS zone (Sydney/Melbourne/Hobart observe DST,
    Brisbane/Perth/Darwin don't, Adelaide has the 30-min offset)."""
    return ZoneInfo(current_timezone())


def _aus_to_utc_iso(dt_local):
    """Convert an aware local-tz datetime to UTC ISO with Z suffix.

    `astimezone(timezone.utc)` respects the DST/offset state in the tz, so
    the conversion is correct regardless of which Australian zone is active.
    """
    return (
        dt_local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    )


def _start_of_day(dt):
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _end_of_day(dt):
    return dt.replace(hour=23, minute=59, second=59, microsecond=999000)


def _parse_aus_date(date_str):
    """Parse an ISO date string and attach Australia/Sydney tz (DST-aware).

    Using `.replace(tzinfo=_user_tz())` with a zoneinfo zone is correct —
    zoneinfo computes the right UTC offset based on the date itself (no manual
    DST math) and respects the user's actual state-level TZ.
    """
    return datetime.fromisoformat(date_str).replace(tzinfo=_user_tz())


def _timeframe_to_range(timeframe, from_date=None, to_date=None):
    """Return (from_iso_utc, to_iso_utc) for a timeframe.

    Returns (None, None) for "this_week" — callers using `this-week-shifts`
    endpoints don't need date params; callers using `all-shifts` should still
    compute the explicit range from the current Monday→Sunday window.
    """
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
    """Explicit current-week range in UTC, computed in the user's local tz
    (Mon 00:00 → Sun 23:59). Pulls tz dynamically via current_timezone()."""
    now = datetime.now(_user_tz())
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

    if not user_context.get("authenticated") or not user_type:
        return ToolResult(
            error=(
                "User profile context is not loaded, so shifts cannot be "
                "retrieved yet."
            ),
            next_hint=(
                "This is an internal context problem. Do not say the user "
                "needs to log in or authenticate. Tell them you hit a snag "
                "loading their SENA profile and ask them to try again in a "
                "moment."
            ),
            meta={"timeframe": timeframe, "auth_context_missing": True},
        )

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
        if timeframe == "this_week" and not (search or shift_filter):
            # Fast path: dedicated this-week endpoint (no params needed)
            path = "/mobile/isw-shift/this-week-shifts"
            query_params = {}
        else:
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
            # Fast path: dedicated this-week endpoint (no params)
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
        # ADMIN — the SENA UI itself calls a different set of endpoints than
        # /organization-member/shift/list-view (which returns the admin's own
        # personal shifts as a member, not the org's shifts). To match what
        # the UI shows on the Shifts page, we hit the same 3 endpoints the
        # UI uses, plus the member calendar-view for the admin's personal
        # shifts. All five run in parallel below — `path` here is just a
        # label for the meta/error envelope; the actual fetches are wired
        # in the parallel block.
        path = "/organization/shift/[in-office+support-worker+clients]"
        query_params = {"page": 1, "limit": 50}
        if search:
            query_params["search"] = search

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

    # ---- PARALLEL MULTI-ENDPOINT FETCH ----
    # ADMIN persona uses a DIFFERENT set of endpoints than the other personas
    # (matches what the SENA UI itself calls — confirmed via browser network
    # tab). For every other persona, we use the single per-persona shift
    # endpoint plus a clients reference for cross-referencing names.
    clients_ref_path = _clients_ref_path_for_user()

    if user_type == "admin":
        # Admin shift fan-out — the SENA UI uses these endpoints. We hit them
        # all in parallel and let the LLM merge:
        #   1. /organization/shift/list-view/type — the AUTHORITATIVE shift
        #      list. Type maps from timeframe: thisweek / scheduled / completed.
        #   2. /organization-member/shift/calendar-view — admin's own personal
        #      shifts as an org member.
        #   3-5. The 3 participant-picker endpoints (in-office / support-worker
        #      / clients). These usually return participant directories but the
        #      SENA UI also pulls them on the Shifts page — include them as
        #      additional context for cross-referencing.
        #   6. /organization/client/list/all-clients — silent name lookup.
        # Picker endpoints (in-office / support-worker / clients) — match the
        # SENA UI exactly: page=1&limit=20.
        admin_params = {"page": 1, "limit": 20}
        if search:
            admin_params["search"] = search

        calendar_params = {}
        if from_iso and to_iso:
            calendar_params["from"] = from_iso
            calendar_params["to"] = to_iso
        elif timeframe == "this_week":
            sd, ed = _this_week_range_utc()
            calendar_params["from"] = sd
            calendar_params["to"] = ed

        # /organization/shift/list-view/type is the AUTHORITATIVE org shift list.
        # Its `type` semantics are awkward:
        #   type=thisweek   → SCHEDULED shifts in the current week (from/to ignored)
        #   type=scheduled  → upcoming SCHEDULED shifts EXCLUDING this week (from/to required)
        #   type=completed  → COMPLETED shifts in the from/to range (from/to required)
        #
        # A shift that already started this week flips to "completed", so for a
        # current-week query we must fetch BOTH type=thisweek (upcoming part)
        # AND type=completed (elapsed part) to show the whole week. Likewise a
        # month window spans past+future, so it needs completed + thisweek +
        # scheduled. We build the right set of calls per timeframe.
        now_utc = _aus_to_utc_iso(datetime.now(_user_tz()))
        wk_start, wk_end = _this_week_range_utc()

        list_view_calls = []
        if timeframe in ("yesterday", "last_week", "last_month"):
            # Purely past → completed only
            if from_iso and to_iso:
                list_view_calls.append(("shifts_completed", {"type": "completed", "from": from_iso, "to": to_iso, "page": 1, "limit": 50}))
        elif timeframe in ("this_week", "today", "arvo", "sarvo", "tomorrow"):
            # Current week → upcoming (thisweek) + already-happened (completed this week)
            list_view_calls.append(("shifts_thisweek", {"type": "thisweek", "page": 1, "limit": 50}))
            list_view_calls.append(("shifts_completed", {"type": "completed", "from": wk_start, "to": now_utc, "page": 1, "limit": 50}))
        elif timeframe == "this_month":
            # Month spans past + current week + future → all three
            list_view_calls.append(("shifts_completed", {"type": "completed", "from": from_iso, "to": now_utc, "page": 1, "limit": 50}))
            list_view_calls.append(("shifts_thisweek", {"type": "thisweek", "page": 1, "limit": 50}))
            if to_iso:
                list_view_calls.append(("shifts_scheduled", {"type": "scheduled", "from": now_utc, "to": to_iso, "page": 1, "limit": 50}))
        else:
            # Future (next_week, next_month, future date_range) → scheduled
            if from_iso and to_iso:
                list_view_calls.append(("shifts_scheduled", {"type": "scheduled", "from": from_iso, "to": to_iso, "page": 1, "limit": 50}))
            # A date_range that includes past days also needs completed
            if timeframe == "date_range" and from_iso and from_iso < now_utc:
                list_view_calls.append(("shifts_completed", {"type": "completed", "from": from_iso, "to": min(to_iso or now_utc, now_utc), "page": 1, "limit": 50}))

        fetchers = []
        for label, params in list_view_calls:
            if search:
                params["search"] = params.get("search") or search
            fetchers.append({
                "label": label,
                "url": construct_api_url("/organization/shift/list-view/type", {}),
                "params": params,
            })

        # PRIMARY org-wide shift source: /organization/shift/calendar.
        # Returns ALL org shift occurrences (any status, recurring expanded) in
        # the window, grouped by person. groupBy=staff catches shifts with staff
        # assigned; groupBy=participant catches shifts with clients assigned.
        # Unlike list-view/type (which filters by scheduled/completed/thisweek)
        # and calendar-view (scoped to where the admin is a participant), THIS
        # endpoint surfaces the org's whole roster. _extract_occurrences handles
        # the nested {items: [{occurrences: [...]}]} shape.
        cal_from, cal_to = from_iso, to_iso
        if not (cal_from and cal_to):
            cal_from, cal_to = _this_week_range_utc()
        for gb in ("staff", "participant"):
            cal_params = {"groupBy": gb, "from": cal_from, "to": cal_to, "page": 1, "limit": 50}
            if search:
                cal_params["search"] = search
            fetchers.append({
                "label": f"shifts_calendar_{gb}",
                "url": construct_api_url("/organization/shift/calendar", {}),
                "params": cal_params,
            })

        # Admin's own personal shifts via member calendar-view (catches shifts
        # where the admin is themselves a participant — covers any status).
        fetchers.append({
            "label": "shifts_my_calendar",
            "url": construct_api_url("/organization-member/shift/calendar-view", {}),
            "params": calendar_params,
        })

        # The 3 endpoints the SENA UI's Shifts page calls. They MAY return
        # participant directories OR shifts-grouped-by-person depending on
        # response shape — _extract_occurrences handles both (digs into any
        # nested occurrences/shifts array; contributes nothing if the items
        # are pure participant records). Belt-and-suspenders: include them so
        # we never miss shifts the UI surfaces here.
        fetchers.extend([
            {"label": "shifts_in_office",
             "url": construct_api_url("/organization/shift/staff/in-office", {}),
             "params": dict(admin_params)},
            {"label": "shifts_support_worker",
             "url": construct_api_url("/organization/shift/staff/support-worker", {}),
             "params": dict(admin_params)},
            {"label": "shifts_clients_view",
             "url": construct_api_url("/organization/shift/clients", {}),
             "params": dict(admin_params)},
        ])

        if clients_ref_path:
            fetchers.append({
                "label": "clients_reference",
                "url": construct_api_url(clients_ref_path, {}),
                "params": {},
            })

        results = _fetch_parallel(fetchers)
        raw_clients = results.get("clients_reference", {})

        # Collect every shift source we actually requested. (Picker endpoints
        # removed — they're participant directories, never shifts.)
        candidate_shift_keys = (
            "shifts_calendar_staff", "shifts_calendar_participant",      # org-wide calendar (PRIMARY)
            "shifts_thisweek", "shifts_scheduled", "shifts_completed",  # list-view/type
            "shifts_my_calendar",                                        # member calendar
            "shifts_in_office", "shifts_support_worker", "shifts_clients_view",  # UI picker endpoints
        )
        shift_keys = tuple(k for k in candidate_shift_keys if k in results)
        shift_sources = {k: results[k] for k in shift_keys}
        all_failed = bool(shift_sources) and all(
            isinstance(v, dict) and v.get("error") for v in shift_sources.values()
        )
        if all_failed:
            first = next(iter(shift_sources.values()))
            return ToolResult(
                error=f"All admin shift endpoints failed: {first.get('error') if isinstance(first, dict) else 'unknown'}",
                meta={"path": path, "shift_sources": list(shift_sources.keys())},
            )

        # Flatten + dedupe ALL sources into one clean list. This is the key
        # fix: the picker endpoints nest shifts inside person items, the
        # list-view/type endpoint has a flat list, calendar-view has another
        # shape. We normalise them all here so the LLM gets ONE list of
        # actual shift records — no nested-JSON spelunking, no source-shape
        # guessing, no "is this a participant or a shift" confusion.
        merged_shifts, per_source_counts = _merge_and_dedupe_shifts(results, shift_keys)

        data = {
            "shifts": merged_shifts,  # ← THE answer: flat, deduped shift list
            "shift_count": len(merged_shifts),
            "clients_reference": raw_clients,
            "_note": (
                "'shifts' is the FINAL merged + deduped list of shift records "
                "from every source — already flattened, so each entry is a "
                "real shift (with startTime/endTime/client/staff). Just read "
                "'shifts' directly. If it's empty, there genuinely are no "
                "shifts in the window. If non-empty, NEVER say 'no shifts'. "
                "Convert each startTime/endTime from UTC to the user's local "
                "timezone before displaying. 'clients_reference' is a SILENT "
                "name lookup for client ids — never reveal client counts "
                "unless the user explicitly asked about clients."
            ),
        }

        return ToolResult(
            data=data,
            meta={
                "path": path,
                "clients_ref_path": clients_ref_path,
                "shift_sources": list(shift_keys),
                "per_source_occurrence_counts": per_source_counts,
                "merged_shift_count": len(merged_shifts),
                "query_params": query_params,
                "timeframe": timeframe,
                "parallel_fetch": True,
            },
        )

    # ---- non-admin personas: primary shift endpoint + persona calendar-view
    # + (optional) clients reference. All run in parallel so an empty primary
    # response doesn't hide shifts that actually live in calendar-view. Same
    # pattern as the admin fix.
    calendar_path = _calendar_view_path_for_user()
    fetchers = [{"label": "shifts", "url": url, "params": query_params}]

    if calendar_path:
        calendar_params = {}
        if from_iso and to_iso:
            calendar_params["from"] = from_iso
            calendar_params["to"] = to_iso
        elif timeframe == "this_week":
            sd, ed = _this_week_range_utc()
            calendar_params["from"] = sd
            calendar_params["to"] = ed
        if search:
            calendar_params["search"] = search
        fetchers.append({
            "label": "shifts_calendar",
            "url": construct_api_url(calendar_path, {}),
            "params": calendar_params,
        })

    if clients_ref_path:
        fetchers.append({
            "label": "clients_reference",
            "url": construct_api_url(clients_ref_path, {}),
            "params": {},
        })

    # If we have at least 2 fetchers, run in parallel. Otherwise single-call.
    if len(fetchers) >= 2:
        results = _fetch_parallel(fetchers)
        raw_primary = results.get("shifts", {})
        raw_calendar = results.get("shifts_calendar")
        raw_clients = results.get("clients_reference")

        # Fail only if BOTH primary AND calendar errored (when calendar exists).
        primary_failed = isinstance(raw_primary, dict) and raw_primary.get("error")
        calendar_failed = (
            raw_calendar is None
            or (isinstance(raw_calendar, dict) and raw_calendar.get("error"))
        )
        if primary_failed and calendar_failed:
            return ToolResult(
                error=f"API error from {path}: {raw_primary.get('error') if isinstance(raw_primary, dict) else 'unknown'}",
                meta={"status_code": raw_primary.get("status_code") if isinstance(raw_primary, dict) else None, "path": path},
            )

        # Flatten + dedupe primary + calendar into one clean shift list, same
        # as the admin path. The LLM reads `shifts` directly.
        merge_keys = ["shifts"]
        if raw_calendar is not None:
            merge_keys.append("shifts_calendar")
        merged_shifts, per_source_counts = _merge_and_dedupe_shifts(results, merge_keys)

        data = {
            "shifts": merged_shifts,  # ← flat, deduped shift list
            "shift_count": len(merged_shifts),
            "_note": (
                "'shifts' is the FINAL merged + deduped list of real shift "
                "records (from the persona's primary endpoint + calendar-view, "
                "flattened). Read it directly. Empty = genuinely no shifts in "
                "the window. Non-empty = NEVER say 'no shifts'. Convert each "
                "startTime/endTime from UTC to the user's local timezone "
                "before displaying. 'clients_reference' (when present) is a "
                "SILENT name lookup — never reveal client counts unless the "
                "user explicitly asked about clients."
            ),
        }
        if raw_clients is not None:
            data["clients_reference"] = raw_clients

        return ToolResult(
            data=data,
            meta={
                "path": path,
                "calendar_view_path": calendar_path,
                "clients_ref_path": clients_ref_path,
                "per_source_occurrence_counts": per_source_counts,
                "merged_shift_count": len(merged_shifts),
                "query_params": query_params,
                "timeframe": timeframe,
                "parallel_fetch": True,
            },
        )

    # Single fetch — used for the 'client' persona (no other-clients list)
    # and any future personas we haven't mapped a clients-ref endpoint for.
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
