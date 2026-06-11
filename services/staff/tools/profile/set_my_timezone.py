"""set_my_timezone — save the user's IANA timezone for 30 days.

The agent calls this when the user volunteers their timezone or location:
  - "I'm in Perth"            → Australia/Perth
  - "set my timezone to NSW"  → Australia/Sydney
  - "I'm in Brisbane Queensland" → Australia/Brisbane

Accepts either an IANA name OR a city/state name; resolves to one of the
seven Australian IANA zones and persists via memory._save_user_timezone
(AgentCore preferences + DDB chat_audit, 30-day TTL).
"""
import sys

from config import VERBOSE
from tools.base import ToolSpec, ToolResult


_LOCATION_TO_IANA = {
    # NSW
    "sydney": "Australia/Sydney",
    "nsw": "Australia/Sydney",
    "new south wales": "Australia/Sydney",
    "newcastle": "Australia/Sydney",
    "wollongong": "Australia/Sydney",
    "central coast": "Australia/Sydney",
    "broken hill": "Australia/Broken_Hill",

    # ACT
    "canberra": "Australia/Sydney",      # or Australia/Canberra
    "act": "Australia/Sydney",

    # VIC
    "melbourne": "Australia/Melbourne",
    "vic": "Australia/Melbourne",
    "victoria": "Australia/Melbourne",
    "geelong": "Australia/Melbourne",

    # QLD
    "brisbane": "Australia/Brisbane",
    "qld": "Australia/Brisbane",
    "queensland": "Australia/Brisbane",
    "gold coast": "Australia/Brisbane",
    "sunshine coast": "Australia/Brisbane",
    "cairns": "Australia/Brisbane",
    "townsville": "Australia/Brisbane",

    # SA
    "adelaide": "Australia/Adelaide",
    "sa": "Australia/Adelaide",
    "south australia": "Australia/Adelaide",

    # WA
    "perth": "Australia/Perth",
    "wa": "Australia/Perth",
    "western australia": "Australia/Perth",
    "eucla": "Australia/Eucla",

    # TAS
    "hobart": "Australia/Hobart",
    "tas": "Australia/Hobart",
    "tasmania": "Australia/Hobart",

    # NT
    "darwin": "Australia/Darwin",
    "nt": "Australia/Darwin",
    "northern territory": "Australia/Darwin",

    # External
    "norfolk island": "Pacific/Norfolk",
    "christmas island": "Indian/Christmas",
    "cocos islands": "Indian/Cocos",
    "cocos": "Indian/Cocos",
    "lord howe": "Australia/Lord_Howe",
}

# Valid IANA zones we'll accept directly (case-insensitive match against lowercased input)
_VALID_IANA = {
    "australia/sydney",
    "australia/melbourne",
    "australia/brisbane",
    "australia/adelaide",
    "australia/perth",
    "australia/hobart",
    "australia/darwin",
    "australia/lord_howe",
    "australia/eucla",
}

def _resolve(input_str: str) -> str | None:
    """Map a user-supplied location/timezone string to a canonical IANA zone."""
    if not input_str:
        return None
    norm = input_str.strip().lower()

    # Exact IANA match — .title() capitalizes each segment incl. after "_"
    # ("australia/lord_howe" → "Australia/Lord_Howe"); .capitalize() would
    # produce the invalid "Lord_howe".
    if norm in _VALID_IANA:
        return norm.title()

    # Substring match against known locations — try longer keys first to avoid
    # "Sydney" matching when user says "North Sydney" etc.
    for loc in sorted(_LOCATION_TO_IANA.keys(), key=len, reverse=True):
        if loc in norm:
            return _LOCATION_TO_IANA[loc]

    return None


def _latlong_to_iana(lat: float, lon: float) -> str | None:
    """Approximate lat/long → Australian IANA zone via state borders.

    Coarse boxes are fine here: every supported zone is state-sized, and the
    only borders where the offset actually differs are WA|SA (lon 129),
    NT|SA (lat -26), SA|QLD/NSW (lon 141), and QLD|NSW (lat -28.2, DST split).
    Returns None outside Australian bounds so the caller can fall back.
    """
    if not (-44.5 <= lat <= -9.0):
        return None
    # Lord Howe Island sits ~159.08°E, well east of the mainland (max ~153.6°E)
    if 158.0 <= lon <= 160.0:
        return "Australia/Lord_Howe"
    if not (112.0 <= lon <= 154.5):
        return None
    if lon < 125.5:
        return "Australia/Perth"
    if lon < 129.0:
        # Eucla strip (UTC+8:45) hugs the south coast; the rest is Perth time
        return "Australia/Eucla" if lat < -28.0 else "Australia/Perth"
    if lon < 138.0:
        return "Australia/Darwin" if lat > -26.0 else "Australia/Adelaide"
    if lon < 141.0:
        return "Australia/Brisbane" if lat > -26.0 else "Australia/Adelaide"
    if lat < -39.5:
        return "Australia/Hobart"
    if lat > -28.2:
        return "Australia/Brisbane"
    return "Australia/Melbourne" if lat < -36.0 else "Australia/Sydney"


def _run(inputs: dict | None) -> ToolResult:
    inputs = inputs or {}
    raw = (inputs.get("timezone_or_location") or "").strip()
    lat, lon = inputs.get("latitude"), inputs.get("longitude")

    if not raw and lat is None:
        return ToolResult(error="Missing input: timezone_or_location (or latitude+longitude).")

    tz_iana = _resolve(raw) if raw else None

    # Optional GPS fallback — frontend may pass device coordinates so the
    # timezone resolves even when the user never names a city/state.
    if not tz_iana and lat is not None and lon is not None:
        try:
            tz_iana = _latlong_to_iana(float(lat), float(lon))
        except (TypeError, ValueError):
            tz_iana = None
        if tz_iana and VERBOSE:
            print(f"[set_my_timezone] ({lat}, {lon}) → {tz_iana}", file=sys.stderr)
    if not tz_iana:
        return ToolResult(
            data={"saved": False, "input": raw or f"({lat}, {lon})"},
            next_hint=(
                f"Couldn't work out '{raw}' as an Australian location. Ask the user "
                "in a friendly way to pick one of: Sydney (NSW), Melbourne (VIC), "
                "Brisbane (QLD), Adelaide (SA), Perth (WA), Hobart (TAS), or Darwin "
                "(NT). Use simple language — these are city or state names. Do NOT "
                "use technical terms like 'IANA' or 'timezone identifier'."
            ),
        )

    if VERBOSE:
        print(f"[set_my_timezone] '{raw}' → {tz_iana}", file=sys.stderr)

    # Lazy imports to avoid circulars
    from memory import _save_user_timezone
    from state import (
        timezone_observes_dst,
        timezone_dst_active_now,
        timezone_short_label,
    )

    _save_user_timezone(tz_iana)

    observes_dst = timezone_observes_dst(tz_iana)
    dst_active_now = timezone_dst_active_now(tz_iana)
    short_label = timezone_short_label(tz_iana)

    return ToolResult(
        data={
            "saved": True,
            "timezone": tz_iana,
            "short_label": short_label,
            "observes_dst": observes_dst,
            "dst_active_now": dst_active_now,
            "ttl_days": 30,
        },
        next_hint=(
            f"Confirm to the user that you've saved their timezone as "
            f"{short_label} and you'll remember it. NEVER mention how long "
            f"it's stored for. Briefly note you'll use this for all date/time "
            f"questions from now on. "
            f"{'They observe daylight saving — the clock change in Oct/Apr is handled automatically by the system so you do not need to do anything when DST starts or ends.' if observes_dst else 'Their region does not observe daylight saving — the time stays constant year-round.'} "
            f"If they had asked a time-sensitive question just before, offer "
            f"to re-run it with the correct timezone."
        ),
    )


TOOL = ToolSpec(
    name="set_my_timezone",
    description=(
        "Save the user's timezone (or Australian state/city) so it persists "
        "for future sessions. Call this whenever the user volunteers their "
        "location or timezone — e.g. 'I'm in Perth', 'my timezone is Brisbane', "
        "'I'm based in NSW', 'set my timezone to Adelaide', 'I'm in Sydney'. "
        "Accepts a city, state, abbreviation (NSW/VIC/QLD/WA/SA/TAS/NT), or "
        "full IANA name like 'Australia/Perth'. After calling, briefly confirm "
        "to the user — do NOT mention any retention period or expiry."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "timezone_or_location": {
                "type": "string",
                "description": (
                    "The user's location or timezone. Examples: 'Perth', 'NSW', "
                    "'Brisbane', 'Australia/Adelaide', 'Western Australia'. "
                    "May be empty when latitude/longitude are provided instead."
                ),
            },
            "latitude": {
                "type": "number",
                "description": (
                    "Optional device latitude (e.g. -33.87). Only pass when the "
                    "message context includes GPS coordinates from the app."
                ),
            },
            "longitude": {
                "type": "number",
                "description": (
                    "Optional device longitude (e.g. 151.21). Pair with latitude."
                ),
            },
        },
        "required": [],
    },
    run=_run,
)
