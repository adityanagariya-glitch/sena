"""Tee stderr + a rolling plain-text log file so [API]/[TOOL] traces stay visible.

Streamlit's newer Uvicorn-based runner can capture child fd 2, so writes to
sys.__stderr__ don't always reach the terminal where `streamlit run ui.py` was
started. This module exposes a `_TERMINAL` object that mirrors every line to
BOTH the original stderr AND a plain-text file you can tail in a second terminal:

    tail -f /tmp/sena_activity.log

Override the path with env SENA_ACTIVITY_LOG=/some/other/path. Line-buffered so
output streams live (no waiting for a full buffer).
"""
import os
import sys

_PATH = os.getenv("SENA_ACTIVITY_LOG", "/tmp/sena_activity.log")


class _Tee:
    """Write to multiple streams; one bad stream never breaks the others."""

    def __init__(self, *streams):
        self._streams = streams

    def write(self, data):
        for s in self._streams:
            try:
                s.write(data)
            except Exception:
                pass
        return len(data)

    def flush(self):
        for s in self._streams:
            try:
                s.flush()
            except Exception:
                pass


try:
    _logfile = open(_PATH, "a", buffering=1, encoding="utf-8")  # line-buffered
    _logfile.write(f"\n--- activity log session started (pid {os.getpid()}) ---\n")
except Exception:
    _logfile = None

_TERMINAL = _Tee(sys.__stderr__, _logfile) if _logfile else sys.__stderr__

# Path is exposed so other code (and the user) can find it.
ACTIVITY_LOG_PATH = _PATH if _logfile else None
