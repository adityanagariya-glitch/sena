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


# City / state / abbreviation → IANA mapping.
# Keys must be lowercase; matching is case-insensitive substring.
_LOCATION_TO_IANA = {
    # NSW
    "sydney": "Australia/Sydney",
    "nsw": "Australia/Sydney",
    "new south wales": "Australia/Sydney",
    "wollongong": "Australia/Sydney",
    "newcastle": "Australia/Sydney",
    # ACT — shares NSW rules
    "canberra": "Australia/Sydney",
    "act": "Australia/Sydney",
    "australian capital territory": "Australia/Sydney",
    # VIC
    "melbourne": "Australia/Melbourne",
    "vic": "Australia/Melbourne",
    "victoria": "Australia/Melbourne",
    "geelong": "Australia/Melbourne",
    # QLD (no DST)
    "brisbane": "Australia/Brisbane",
    "qld": "Australia/Brisbane",
    "queensland": "Australia/Brisbane",
    "gold coast": "Australia/Brisbane",
    "sunshine coast": "Australia/Brisbane",
    "cairns": "Australia/Brisbane",
    "townsville": "Australia/Brisbane",
    "toowoomba": "Australia/Brisbane",
    # SA (30-min offset)
    "adelaide": "Australia/Adelaide",
    "sa": "Australia/Adelaide",
    "south australia": "Australia/Adelaide",
    # WA (no DST)
    "perth": "Australia/Perth",
    "wa": "Australia/Perth",
    "western australia": "Australia/Perth",
    "fremantle": "Australia/Perth",
    # TAS
    "hobart": "Australia/Hobart",
    "tas": "Australia/Hobart",
    "tasmania": "Australia/Hobart",
    "launceston": "Australia/Hobart",
    # NT (no DST)
    "darwin": "Australia/Darwin",
    "nt": "Australia/Darwin",
    "northern territory": "Australia/Darwin",
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
}


def _resolve(input_str: str) -> str | None:
    """Map a user-supplied location/timezone string to a canonical IANA zone."""
    if not input_str:
        return None
    norm = input_str.strip().lower()

    # Exact IANA match
    if norm in _VALID_IANA:
        # Re-canonicalize capitalization
        return "Australia/" + norm.split("/", 1)[1].capitalize().replace("act", "Sydney")

    # Substring match against known locations — try longer keys first to avoid
    # "Sydney" matching when user says "North Sydney" etc.
    for loc in sorted(_LOCATION_TO_IANA.keys(), key=len, reverse=True):
        if loc in norm:
            return _LOCATION_TO_IANA[loc]

    return None


def _run(inputs):
    raw = (inputs or {}).get("timezone_or_location", "").strip()
    if not raw:
        return ToolResult(error="Missing required input: timezone_or_location.")

    tz_iana = _resolve(raw)
    if not tz_iana:
        return ToolResult(
            data={"saved": False, "input": raw},
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
                    "'Brisbane', 'Australia/Adelaide', 'Western Australia'."
                ),
            },
        },
        "required": ["timezone_or_location"],
    },
    run=_run,
)
