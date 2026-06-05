"""get_current_time — current time, timezone, and daytime indicator.

Shows the user their current time with timezone and whether it's day or night.
Respects the user's stored timezone preference (or falls back to Sydney).
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from state import current_timezone, timezone_short_label
from tools.base import ToolSpec, ToolResult


def _run(inputs: dict | None) -> ToolResult:
    tz_name = current_timezone()
    now = datetime.now(ZoneInfo(tz_name))

    # Determine daytime (roughly 6 AM - 6 PM)
    hour = now.hour
    is_daytime = 6 <= hour < 18
    period = "daytime" if is_daytime else "nighttime"

    # Format time nicely: "3:45 PM" or "14:45" depending on context
    # Use 12-hour format for Australian English: "3:45 PM"
    time_str = now.strftime("%-I:%M %p").lstrip("0")  # Remove leading zero from hour

    # Get friendly timezone label
    tz_label = timezone_short_label(tz_name)

    # Construct response
    response_text = f"**{tz_label}** — {time_str} ({period})"

    return ToolResult(
        data={
            "timezone": tz_name,
            "timezone_label": tz_label,
            "time": time_str,
            "is_daytime": is_daytime,
            "period": period,
            "formatted": response_text,
        },
        meta={
            "tz_name": tz_name,
            "hour": hour,
        },
    )


TOOL = ToolSpec(
    name="get_current_time",
    description=(
        "Get the current time in your timezone. Shows the time, timezone name, "
        "and whether it's daytime or nighttime. Use this whenever the user asks "
        "'what time is it', 'time', 'current time', 'what's the time', etc. "
        "If the user mentions a location or timezone, call set_my_timezone first, "
        "then call this tool again to see the updated time."
    ),
    input_schema={
        "type": "object",
        "properties": {},
        "required": [],
    },
    run=_run,
)
