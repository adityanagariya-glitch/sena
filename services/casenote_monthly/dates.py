"""Month-window helpers.

The backend stores/queries shift datetimes in UTC. SENA's convention (see
services/staff/api_router.find_best_api) is to reason about calendar windows in
Australia/Sydney local time, then convert the boundaries to UTC ISO with a literal
"Z" suffix for the API. We follow that here so a "month" lines up with what a user
in Australia would consider that month.
"""
import calendar
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

_AUS = ZoneInfo("Australia/Sydney")

# Candidate date fields on a content-mode note, most-specific first. The get-all-data
# body shape is undocumented, so we probe several names when filtering by month.
_DATE_KEYS = ("shiftStartDate", "shiftDate", "shiftEndDate", "date",
              "startTime", "caseNoteUpdatedAt", "updatedAt", "createdAt")


def _to_utc_z(dt: datetime) -> str:
    """Format an aware datetime as UTC ISO with millisecond precision + 'Z'."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def month_window(year: int, month: int) -> tuple[str, str]:
    """Return (from, to) UTC-Z bounds covering `month` of `year` in Australia/Sydney.

    Raises ValueError for month outside 1..12.
    """
    if not 1 <= month <= 12:
        raise ValueError("month must be between 1 and 12")
    last_day = calendar.monthrange(year, month)[1]
    start = datetime(year, month, 1, 0, 0, 0, 0, tzinfo=_AUS)
    end = datetime(year, month, last_day, 23, 59, 59, 999000, tzinfo=_AUS)
    return _to_utc_z(start), _to_utc_z(end)


def _parse_iso(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def note_in_month(note: dict, year: int, month: int) -> bool:
    """True if a content-mode note's shift/note date falls in the given month (AUS local).

    Used to filter get-all-data results (that endpoint has no server-side date filter).
    Checks several candidate date fields; if none parse, the note is INCLUDED (we'd
    rather over-include than silently drop a note whose date field we didn't recognise).
    """
    body = note.get("_body", note) if isinstance(note, dict) else note
    found_any = False
    for key in _DATE_KEYS:
        dt = _parse_iso((body or {}).get(key))
        if dt is None:
            continue
        found_any = True
        local = dt.astimezone(_AUS)
        if local.year == year and local.month == month:
            return True
    return not found_any  # no recognisable date → keep it
