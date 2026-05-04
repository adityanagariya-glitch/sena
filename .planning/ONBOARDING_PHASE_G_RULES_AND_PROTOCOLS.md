---
title: Onboarding Phase G — Behavioural Rules + Voice Protocols
status: COMPLETE
shipped: 2026-05-02
plan_artifact: ~/.claude/plans/cozy-waddling-river.md
source_spec: SENA_AI/Issues_left_to_solve.xml
---

# Phase G — 7 Rules + Voice Protocols

Adds the behavioural contract layer on top of the v2 onboarding API (Phase F).
Every rule from `Issues_left_to_solve.xml` is delivered backend-side; Flutter
consumes via 3 new wire-contract additions documented in
`SENA_AI/FLUTTER_VOICE_INTEGRATION_FIXES.md` (Issues 7, 8, 9).

## Rule → Implementation

| Rule | Implementation surface |
|------|------------------------|
| 1. Strict Session Isolation | `[LIVE_STATE_JSON]` block is the SOLE authority. System prompt explicitly forbids "remembering" prior sessions. Per-session Redis key `sena:onboarding:session:{sid}:bootstrap`. |
| 2. Multi-Page Handoff | `SessionBootstrap.mode ∈ {new_user, returning_same_page, page_handoff}` + `prior_pages` map. Prompt rule acknowledges `participant_display_name` on `page_handoff`. |
| 3. Pre-filled Verify | `_readonly_paths` set on `ToolDispatcher` rejects writes; first-utterance verify rule in system prompt. |
| 4. Multi-Value | `update_field` tool exposes `values: array<string>` alongside `value`; dispatcher prefers array, logs `multi_value applied count=N`. |
| 5. Proactive Optional | System prompt rule iterates `required: false` after required fields filled. |
| 6. Dynamic UI | `add_repeatable_row` tool emits `row_added` event (already shipped Phase F; Flutter subscribe documented in Issue 9). |
| 7. Validation Loop | `ScreenStateV2.field_errors: dict[str, str]` surfaces reasons in `Invalid (re-ask): path (reason)` line. |

## Voice Protocols

| Protocol | Implementation |
|----------|----------------|
| Interrupt recovery | `_last_interrupted_intent` preserved on `sc.interrupted`; hidden `[INTERRUPTED]` text turn injected so Gemini addresses interruption AND finishes prior thought. |
| Silence two-step | `_silence_warned` flag tracks first 25s warn vs 60s pending-fields summary. Reset on any user audio. |
| Long-session compression | `LiveConnectConfig.context_window_compression = ContextWindowCompressionConfig(sliding_window=SlidingWindow())` — verified via Context7 against `/googleapis/js-genai`. SDK-version fallback gracefully skips when types unavailable. |

## Files Touched

Backend (`SENA_AI/sena-ai/services/onboarding/`):
- `src/onboarding/models/session_bootstrap.py` (NEW)
- `src/onboarding/repositories/state_repo.py`
- `src/onboarding/api/routes.py`
- `src/onboarding/api/ws_routes.py`
- `src/onboarding/services/prompt_builder.py`
- `src/onboarding/services/screen_context.py`
- `src/onboarding/services/tools.py`
- `src/onboarding/services/gemini_live.py`
- `src/onboarding/prompts/onboarding_system.md` (full rewrite — 50→200 lines)

Tests:
- `tests/test_tools.py` — handler-count assertion updated (4→5)
- `tests/test_screen_context.py` — 4 stale v1-signature tests rewritten to v2; 2 new Rule-7 tests added

Docs:
- `SENA_AI/CLAUDE.md` — `models/session_bootstrap.py` added to onboarding service table
- `SENA_AI/FLUTTER_VOICE_INTEGRATION_FIXES.md` — Issues 7, 8, 9 appended

## Verification

```bash
cd SENA_AI/sena-ai/services/onboarding
PYTHONPATH=src python -m pytest tests/ -q
# Expected: 78 passed
```

End-to-end matrix per rule lives in `~/.claude/plans/cozy-waddling-river.md` §Verification.

## Operational notes

1. The `pip install -e` registration pointing to a stale clone bit during this
   work — see `.claude/issues-solved/0005-editable-install-wrong-clone.md` for
   the diagnostic command and fix.

2. The system prompt is now ~200 lines; future rule additions should slot into
   the existing `Rule N — Name` blocks rather than appending free-form
   paragraphs, so Gemini parses them consistently.

3. Bootstrap envelope is read-once at WS open; mid-session updates require the
   client to reconnect with a fresh `?bootstrap=...` (or new session). This is
   intentional — Rule 1's hygiene contract demands a clean cut.
