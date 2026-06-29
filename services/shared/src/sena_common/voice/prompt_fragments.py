"""
Lazy prompt fragments — load a rule into the live session only when its trigger
condition first appears, instead of carrying it in the system prompt all session.

WHY
  The Gemini Live ``system_instruction`` is fixed for the whole session and is
  re-read (billed) on EVERY turn. A rule that only matters once a condition
  becomes true (e.g. "how to handle injury details" — relevant only after the
  ``anyInjuries`` toggle flips and Flutter reveals the child field) does not
  need to ride in the prompt for the entire session.

HOW (mirrors screen_delta.py — small, dependency-free, shared by both services)
  1. At session open, ``build_system_prompt`` appends a compact POINTER block —
     one line per fragment — so the agent KNOWS each rule exists and will arrive
     when relevant. The full rule text is NEVER baked into the prompt.
  2. On each ``screen_state`` update, ``InjectedFragmentTracker`` checks the
     triggers; a fragment whose trigger just became true is injected ONCE via
     the same ``send_realtime_input`` text channel the delta-screen already uses.
     A session that resumes mid-form with the field already present injects on
     the first screen_state — so the rule still always arrives.
  3. On resume/reconnect, ``reset()`` (called alongside the delta tracker's
     ``reset_baseline()``) clears the injected set so fragments re-inject against
     the freshly-rebuilt prompt.

SAFETY
  Triggers are VALUE-INDEPENDENT. The per-turn screen channel carries only
  ``field_status`` (filled/empty/invalid) and the delta's ``added`` set — not the
  boolean value of a parent toggle. Because Flutter renders a conditional child
  field ONLY when its parent condition is true, "the child field appeared on
  screen" is a faithful, value-free trigger. Predicates therefore key off field
  PRESENCE (a dotted path showing up in ``field_status`` / ``delta.added``).

  A block is NEVER silently dropped — the pointer always remains, so even if the
  runtime injection never fires the agent still knows the rule exists and can ask
  or call get_current_state. Safety-critical or always-required rules
  (confirmation gates, mandatory reminders) must NOT be modelled as lazy
  fragments — keep them baked into the system prompt. This module is only for
  genuinely conditional, low-risk rules.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PromptFragment:
    """A rule that loads on demand.

    key      — stable identifier, used for the pointer label, the inject log,
               and the injected-once bookkeeping (e.g. "case_review.injuryDetails").
    text     — the FULL rule, sent verbatim to the model when the trigger fires.
    pointer  — the one-line note shown at session open while the rule is still
               dormant, so the agent knows it exists and will arrive when needed.
    triggers_on — predicate over (delta_dict, current_state_dict) → bool. Returns
               True the moment the rule becomes relevant. ``delta_dict`` is a
               plain dict view of the screen delta (key ``added`` → paths that
               just appeared); ``current_state_dict`` is the screen state dict
               (``field_status``, ``field_errors``, ...). Keep predicates
               value-independent — trigger on field PRESENCE.
    """

    key: str
    text: str
    pointer: str
    triggers_on: Callable[[dict, dict], bool]


def field_present(path: str) -> Callable[[dict, dict], bool]:
    """Build a predicate: True when ``path`` is on screen now (or just appeared).

    Faithful, value-free trigger for a conditional child field — Flutter renders
    the child only when its parent toggle is true, so presence == relevance.
    """

    def _pred(delta: dict, state: dict) -> bool:
        added = delta.get("added") or {}
        if path in added:
            return True
        return path in (state.get("field_status") or {})

    return _pred


@dataclass
class FragmentRegistry:
    """An immutable set of conditional fragments for one prompt-set (per service)."""

    fragments: list[PromptFragment] = field(default_factory=list)

    def pointer_block(self) -> str:
        """Render the one-line pointers for the system prompt.

        Empty string when there are no fragments (caller no-ops the section).
        """
        if not self.fragments:
            return ""
        # Deliberately header-less and terse: this block rides in the system
        # prompt every turn, so its overhead must stay under the rule text it
        # defers. One compact line per fragment; the [RULE: …] message that
        # arrives later is self-describing, so no preamble is needed here.
        lines = [f"(On-demand rule — {f.pointer})" for f in self.fragments]
        return "\n" + "\n".join(lines) + "\n"


class InjectedFragmentTracker:
    """Per-session bookkeeping — mirrors ScreenDeltaTracker's lifecycle.

    Tracks which fragments have already been injected so each loads at most once
    per connection. ``reset()`` is called at the same site as the delta tracker's
    ``reset_baseline()`` so a resume re-injects against the rebuilt prompt.
    """

    def __init__(self, registry: FragmentRegistry | None = None) -> None:
        self._registry = registry or FragmentRegistry()
        self._injected: set[str] = set()

    def reset(self) -> None:
        """Forget what's been injected (call on resume/reconnect)."""
        self._injected.clear()

    def fragments_to_inject(self, delta: dict, current_state: dict) -> list[PromptFragment]:
        """Return not-yet-injected fragments whose trigger is now satisfied.

        Marks them injected as a side effect, so each fires exactly once.
        """
        out: list[PromptFragment] = []
        for f in self._registry.fragments:
            if f.key in self._injected:
                continue
            if f.triggers_on(delta, current_state):
                self._injected.add(f.key)
                out.append(f)
        return out
