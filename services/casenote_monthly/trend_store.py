"""File-based trend storage for cross-month NDIS trend analysis.

Each month's section 5 (Trend Analysis) output is saved as:
    trends/{client_id}/{YYYY-MM}.json

On the next month's report generation, the previous month's entry is loaded
and injected into section 5's context so the model can produce ↑ ↓ → arrows.
"""
import json
import re
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRENDS_DIR = HERE / "trends"

_SAFE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SAFE_PERIOD = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _validate_name(value: str, label: str, pattern: re.Pattern = _SAFE_NAME) -> str:
    """These values become directory/file names — reject separators, dots, etc."""
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(f"Unsafe {label} for filesystem use: {value!r}")
    return value


def _client_dir(client_id: str) -> Path:
    d = TRENDS_DIR / _validate_name(client_id, "client_id")
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_trend(client_id: str, period: str, trend_text: str, saved_at: str) -> Path:
    """Save section 5 output for client + period (YYYY-MM).

    Returns the path written.
    """
    _validate_name(period, "period", _SAFE_PERIOD)
    path = _client_dir(client_id) / f"{period}.json"
    path.write_text(
        json.dumps({"client_id": client_id, "period": period,
                    "trend_text": trend_text, "saved_at": saved_at},
                   indent=2),
        encoding="utf-8",
    )
    return path


def get_trend(client_id: str, period: str) -> dict | None:
    """Return stored trend for an exact period, or None if not found."""
    path = _client_dir(client_id) / f"{period}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def get_previous_trend(client_id: str, current_period: str) -> dict | None:
    """Return the most recent trend strictly before current_period, or None."""
    d = _client_dir(client_id)
    year, month = map(int, current_period.split("-"))
    # Walk backwards up to 12 months
    check = date(year, month, 1)
    for _ in range(12):
        check = (check.replace(day=1) - timedelta(days=1)).replace(day=1)
        candidate = d / f"{check.strftime('%Y-%m')}.json"
        if candidate.exists():
            return json.loads(candidate.read_text(encoding="utf-8"))
    return None


def list_trends(client_id: str) -> list[dict]:
    """Return all stored trends for a client, sorted newest first."""
    d = _client_dir(client_id)
    if not d.exists():
        return []
    entries = []
    for f in sorted(d.glob("*.json"), reverse=True):
        if f.name.endswith("_stats.json"):
            continue  # companion stats files are not trend entries (lack trend_text)
        try:
            entry = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if "trend_text" in entry:  # only well-formed trend entries reach the API model
            entries.append(entry)
    return entries


def save_month_stats(client_id: str, period: str, stats: dict, saved_at: str) -> Path:
    """Save computed stats for cross-month MoM analysis.

    Stats saved as trends/{client_id}/{YYYY-MM}_stats.json
    """
    _validate_name(period, "period", _SAFE_PERIOD)
    path = _client_dir(client_id) / f"{period}_stats.json"
    path.write_text(
        json.dumps({"client_id": client_id, "period": period, "stats": stats, "saved_at": saved_at}, indent=2),
        encoding="utf-8",
    )
    return path


def get_previous_month_stats(client_id: str, current_period: str) -> dict | None:
    """Return the most recent stats strictly before current_period, or None.

    Walks back up to 12 months using the same logic as get_previous_trend.
    """
    d = _client_dir(client_id)
    year, month = map(int, current_period.split("-"))
    check = date(year, month, 1)
    for _ in range(12):
        check = (check.replace(day=1) - timedelta(days=1)).replace(day=1)
        candidate = d / f"{check.strftime('%Y-%m')}_stats.json"
        if candidate.exists():
            return json.loads(candidate.read_text(encoding="utf-8"))
    return None
