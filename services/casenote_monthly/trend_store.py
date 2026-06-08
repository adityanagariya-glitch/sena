"""File-based trend storage for cross-month NDIS trend analysis.

Each month's section 5 (Trend Analysis) output is saved as:
    trends/{client_id}/{YYYY-MM}.json

On the next month's report generation, the previous month's entry is loaded
and injected into section 5's context so the model can produce ↑ ↓ → arrows.
"""
import json
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRENDS_DIR = HERE / "trends"


def _client_dir(client_id: str) -> Path:
    d = TRENDS_DIR / client_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_trend(client_id: str, period: str, trend_text: str, saved_at: str) -> Path:
    """Save section 5 output for client + period (YYYY-MM).

    Returns the path written.
    """
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
        try:
            entries.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return entries
