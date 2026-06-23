# Flutter Dev — Backend "screen mismatch" safety net REMOVED (2026-06-23)

> **Self-contained.** Read this alone — no other doc required. **TL;DR:** the backend feature that made the
> voice agent say *"it looks like we might be on different screens — close and reopen the app"* has been
> **removed**. It was firing **false positives** (saying "wrong screen" while you were on the right screen).
> **No Flutter code change is required for this removal** — but read §3, because screen↔session correctness
> is now entirely your side with no backend warning.

---

## 1. What was removed and why

A backend safety net (added 2026-06-22) compared, on every `get_current_state` tool call, the **live screen
id** the client reports against the **session's step**, and if they differed it logged
`screen_session_mismatch` and injected a directive telling the agent to ask the participant to reopen the app.

**Why it's gone:** the two values legitimately differ during normal operation (the live screen id and the
session's `schema.step_id` are not guaranteed identical moment-to-moment), so the check fired on the
**correct** screen — the agent kept insisting "you're on the wrong screen," and only worked after the user
manually said "no, you're on the right screen." It broke working flows. Net-negative → removed.

## 2. Exactly what changed (backend only)

In `services/onboarding/voice/tools.py` (`ToolDispatcher`):
- Removed the `expected_step_id` constructor parameter and its stored field.
- Removed the `get_current_state` post-call hook that ran the comparison.
- Removed the `_flag_screen_mismatch(...)` method (the `screen_session_mismatch` log + the
  `screen_mismatch_warning` directive injected into the `get_current_state` result).

In `services/onboarding/api/ws_routes.py`:
- Removed the `expected_step_id=schema.step_id` argument passed to `ToolDispatcher(...)`.

Tests: the three `test_get_current_state_*` mismatch tests were removed.

**Nothing else changed.** `update_field`, `submit_step`, `get_current_state` (still returns the live state
normally), `confirm_dialog`, `add_row`/`delete_row`, audio streaming, transcripts, and all WS events behave
exactly as before. The only behavioural delta: the agent will **no longer** spontaneously say "we might be on
different screens / reopen the app."

## 3. What this means for you (important)

- ✅ **No false "wrong screen" interruptions anymore.** The agent won't tell users to reopen the app.
- ⚠️ **The backend will no longer warn you about a real screen↔session binding bug.** It used to be a loud
  signal; now it's silent. So the correctness of the binding is **fully on the Flutter side**:
  - Each voice screen must **create and dispose its own session** (don't let a previous screen's controller
    answer the next screen's `tool_request` frames).
  - Each screen's session must be created with the correct **`schema.step_id`** for that screen (this is what
    selects the agent's prompt — e.g. `consent_overview` / `consent` / `consent_review`).
- ✅ **`screen_state_v2` is unaffected.** Keep pushing it — it is still used for surfacing on-screen
  validation errors to the agent (the `field_errors` / `validation_failed` path). It is simply no longer
  compared for screen-mismatch detection.

## 4. Nothing for you to deploy for this change
This removal is backend-only and requires **no Flutter change**. Your existing per-screen session handling
keeps working — it just won't get a backend nag if a binding is stale. If you want a guard back later, the
safer option is a **create-time** check (reject a session create where the top-level `step` ≠
`schema.step_id`) rather than the live per-turn comparison that was removed — ask the backend team.

## 5. Verify (after backend redeploys)
- Run a consent / any voice screen normally → the agent never says "we might be on different screens" or
  "close and reopen the app."
- Backend logs show **no** `screen_session_mismatch` lines.
- All field updates, submits, and transcripts still work as before.
