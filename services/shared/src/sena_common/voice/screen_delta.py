"""
Delta screen state tracking — send only what changed to Gemini.

Reduces tokens: 120 tokens/full-state → 10 tokens/delta = 12x savings per field focus.

Flow:
  1. First screen injection → send FULL state (establish baseline)
  2. User taps field → compute delta vs last state → send only changes
  3. On resume/reconnect → send FULL state again (reset baseline)
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class ScreenStateDelta:
    """What changed since last injection."""

    step_id: str | None = None
    focused_section: str | None = None
    focused_field: str | None = None
    added: dict[str, str] = field(default_factory=dict)  # newly appeared on screen → status
    filled_changed: list[str] = field(default_factory=list)  # existing field empty→filled (update)
    emptied: list[str] = field(default_factory=list)  # existing field filled→empty (clear)
    invalid_changed: dict[str, str] = field(default_factory=dict)  # field → error reason
    removed: list[str] = field(default_factory=list)  # fields no longer on screen (hidden/deleted)
    repeatable_rows_changed: dict[str, int] = field(default_factory=dict)  # section → count
    is_empty: bool = False  # True if no changes detected

    def render(self) -> str:
        """Render delta as minimal [SCREEN_DELTA] block."""
        if self.is_empty:
            return "[SCREEN_DELTA] (no changes)"

        lines = ["[SCREEN_DELTA]"]

        if self.step_id:
            lines.append(f"Step: {self.step_id}")

        if self.focused_section or self.focused_field:
            focus_parts = [p for p in [self.focused_section, self.focused_field] if p]
            lines.append("Focus: " + " / ".join(focus_parts))

        if self.added:
            # New fields/rows appeared (user added a row or a conditional field
            # opened). Annotate each with its state so Gemini knows what to ask.
            parts = [f"{p} ({s})" for p, s in sorted(self.added.items())]
            lines.append("Added to screen: " + ", ".join(parts))

        if self.filled_changed:
            lines.append("Newly filled: " + ", ".join(sorted(self.filled_changed)))
        if self.emptied:
            lines.append("Cleared: " + ", ".join(sorted(self.emptied)))

        if self.invalid_changed:
            parts = []
            for path, reason in sorted(self.invalid_changed.items()):
                parts.append(f"{path} ({reason})")
            lines.append("Invalid changes: " + ", ".join(parts))

        if self.removed:
            # Fields hidden by conditional logic or deleted rows — tell Gemini to
            # drop them from context so it never re-asks a field that's gone.
            lines.append("Removed (no longer ask): " + ", ".join(sorted(self.removed)))

        if self.repeatable_rows_changed:
            rows_str = ", ".join(
                f"{sec}={count}" for sec, count in sorted(self.repeatable_rows_changed.items())
            )
            lines.append("Row counts: " + rows_str)

        return "\n".join(lines)


class ScreenDeltaTracker:
    """Track screen state changes and compute deltas."""

    def __init__(self) -> None:
        """Initialize with no baseline state."""
        self._last_state: dict | None = None
        self._is_first_injection: bool = True
        self._injection_count: int = 0  # Track delta version (v1=full, v2+=deltas)

    def reset_baseline(self) -> None:
        """Reset baseline on reconnect/resume. Forces next injection to be FULL state."""
        self._last_state = None
        self._is_first_injection = True
        self._injection_count = 0

    def get_delta_version(self) -> str:
        """Get human-readable delta version: 'v1' (full), 'v2+' (deltas)."""
        if self._injection_count == 0:
            return "v1 (full-state)"
        return f"v{self._injection_count + 1} (delta)"

    def increment_injection_count(self) -> int:
        """Increment counter and return current version number."""
        self._injection_count += 1
        return self._injection_count

    def set_full_state(self, state: dict) -> None:
        """Record full state after injection. Call this after sending FULL state to Gemini."""
        self._last_state = state
        self._is_first_injection = False

    def compute_delta(self, current_state: dict) -> tuple[ScreenStateDelta, bool]:
        """
        Compute what changed between last state and current state.

        Returns: (delta, should_send_full_state)
        - delta: the changes
        - should_send_full_state: True if this is first injection or after reset
        """
        # First injection or after reset → always send full state to establish baseline
        if self._last_state is None:
            return ScreenStateDelta(is_empty=True), True

        delta = ScreenStateDelta()

        # Compare step_id
        last_step = self._last_state.get("step_id")
        curr_step = current_state.get("step_id")
        if last_step != curr_step:
            delta.step_id = curr_step

        # Compare focus
        last_section = self._last_state.get("focused_section")
        curr_section = current_state.get("focused_section")
        if last_section != curr_section:
            delta.focused_section = curr_section

        last_field = self._last_state.get("focused_field")
        curr_field = current_state.get("focused_field")
        if last_field != curr_field:
            delta.focused_field = curr_field

        # Compare field_status (filled, empty, invalid)
        last_status = self._last_state.get("field_status", {})
        curr_status = current_state.get("field_status", {})

        for path, status in curr_status.items():
            last_st = last_status.get(path)
            if last_st is None:
                # Field newly APPEARED on screen — a user "add" (new row) or a
                # conditional field opening. Record with its state; don't mislabel
                # a brand-new empty field as "cleared".
                delta.added[path] = status
                if status == "invalid":
                    reason = current_state.get("field_errors", {}).get(path, "")
                    delta.invalid_changed[path] = reason
            elif last_st != status:
                # Existing field changed fill-state — a user "update"/"clear".
                if status == "filled":
                    delta.filled_changed.append(path)
                elif status == "empty":
                    delta.emptied.append(path)
                elif status == "invalid":
                    reason = current_state.get("field_errors", {}).get(path, "")
                    delta.invalid_changed[path] = reason

        # Detect REMOVED fields — present last time, gone now. Happens when the
        # user hides a conditional field (e.g. "service address same as home")
        # or deletes a repeatable row. Gemini must drop these from context so it
        # never re-asks a field that no longer exists on screen.
        for path in last_status:
            if path not in curr_status:
                delta.removed.append(path)

        # Compare field_errors (for invalid fields). Skip paths already removed —
        # a gone field's stale error must not resurrect it into the delta.
        last_errors = self._last_state.get("field_errors", {})
        curr_errors = current_state.get("field_errors", {})
        for path, reason in curr_errors.items():
            if path not in curr_status:
                continue
            if last_errors.get(path) != reason:
                delta.invalid_changed[path] = reason

        # Compare repeatable_rows — both count changes AND whole-section removal.
        last_rows = self._last_state.get("repeatable_rows", {})
        curr_rows = current_state.get("repeatable_rows", {})
        for section, count in curr_rows.items():
            if last_rows.get(section) != count:
                delta.repeatable_rows_changed[section] = count
        for section in last_rows:
            if section not in curr_rows:
                # Section gone entirely → signal 0 rows so Gemini stops asking.
                delta.repeatable_rows_changed[section] = 0

        # Mark as empty if nothing changed
        if (
            not delta.step_id
            and not delta.focused_section
            and not delta.focused_field
            and not delta.added
            and not delta.filled_changed
            and not delta.emptied
            and not delta.invalid_changed
            and not delta.removed
            and not delta.repeatable_rows_changed
        ):
            delta.is_empty = True

        return delta, False

    def injection_type(self, current_state: dict) -> Literal["full", "delta", "none"]:
        """Determine what to send: full state, delta, or nothing."""
        if self._last_state is None:
            return "full"

        delta, should_send_full = self.compute_delta(current_state)
        if should_send_full:
            return "full"
        if delta.is_empty:
            return "none"
        return "delta"


@dataclass
class DeltaLogEntry:
    """One delta operation logged for 30-minute retention."""

    timestamp: float
    session_id: str
    delta_version: int
    delta_type: str  # "v1-full" or "v{N}-delta"
    fields_changed: int
    focus_section: str | None
    focus_field: str | None

    def age_seconds(self) -> float:
        """Seconds since this entry was logged."""
        return time.time() - self.timestamp

    def is_expired(self, ttl_seconds: int = 1800) -> bool:
        """Check if older than TTL (default 30 min)."""
        return self.age_seconds() > ttl_seconds

    def __str__(self) -> str:
        """Format for log output."""
        age = self.age_seconds()
        return (
            f"[{age:.0f}s ago] session={self.session_id} {self.delta_type} "
            f"focus={self.focus_section}/{self.focus_field} changes={self.fields_changed}"
        )


class DeltaLogBuffer:
    """Keep 30 minutes of delta operations in memory for diagnostics."""

    def __init__(self, ttl_seconds: int = 1800):
        """Init with 30-min TTL."""
        self._ttl_seconds = ttl_seconds
        self._entries: deque = deque(maxlen=1000)  # Keep last 1000 operations

    def record(
        self,
        session_id: str,
        delta_version: int,
        delta_type: str,
        fields_changed: int,
        focus_section: str | None,
        focus_field: str | None,
    ) -> None:
        """Record a delta operation."""
        entry = DeltaLogEntry(
            timestamp=time.time(),
            session_id=session_id,
            delta_version=delta_version,
            delta_type=delta_type,
            fields_changed=fields_changed,
            focus_section=focus_section,
            focus_field=focus_field,
        )
        self._entries.append(entry)

    def get_session_deltas(self, session_id: str) -> list[DeltaLogEntry]:
        """Get all non-expired deltas for a session."""
        return [
            e for e in self._entries
            if e.session_id == session_id and not e.is_expired(self._ttl_seconds)
        ]

    def get_recent_deltas(self, limit: int = 50) -> list[DeltaLogEntry]:
        """Get last N non-expired deltas (newest first)."""
        valid = [e for e in self._entries if not e.is_expired(self._ttl_seconds)]
        return list(reversed(valid))[-limit:]

    def summary(self) -> str:
        """Get summary of delta buffer."""
        valid = [e for e in self._entries if not e.is_expired(self._ttl_seconds)]
        sessions = set(e.session_id for e in valid)
        return (
            f"DeltaLogBuffer: {len(valid)} entries, {len(sessions)} sessions, "
            f"TTL={self._ttl_seconds}s"
        )
