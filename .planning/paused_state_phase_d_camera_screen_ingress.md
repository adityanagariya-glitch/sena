---
title: Paused State — Phase D Camera + Screen Ingress
status: PAUSED - BLOCKED
paused_on: 2026-04-22
blocker: Office dependency — other dev busy, context-switch to new feature
last_commit: 4f4250b
---

# Paused: Phase D — Camera + Screen Frame Ingress

## Last Action
Session resumed + renamed. No code written. Tree clean at `4f4250b`.

## Blocker
External dev unavailable. Switching to new feature per user.

## Uncommitted Work
None. `git status` clean. No stash, no WIP branch.

## Active Thoughts (carry forward)
- Phase D adds vision to existing onboarding voice WS
- Entry point: `sena-ai/services/onboarding/src/onboarding/api/ws_routes.py`
- Bridge: `services/gemini_live.py` — already has b2g/g2b pattern
- Send shape: `session.send_realtime_input(video=Blob(data, "image/jpeg"))`
- Rate limit: 2 fps per frame type, Redis token bucket
- Prompt addendum: reference visible frames in system prompt

## Pending Checklist
- [ ] WS JSON inbound: `camera_frame` + `screen_frame` (base64 JPEG)
- [ ] Base64 decode + size/MIME validation
- [ ] Redis token bucket — 2 fps cap per frame type per session
- [ ] Route to `session.send_realtime_input(video=Blob(...))`
- [ ] Prompt addendum in `prompts/onboarding_system.md` for visible images
- [ ] Unit tests — frame decode, rate limit, Gemini forwarding
- [ ] Harness UI — add camera/screen toggle + send button
- [ ] Integration test — end-to-end frame → Gemini → ack

## EXACT Next Step On Resume
1. `cd sena-ai/services/onboarding && pip install -e .`
2. Read `.planning/ONBOARDING_VOICE_API_PLAN.md` Phase D section
3. Invoke `Skill: gemini-live-api-dev` (mandatory per CLAUDE.md)
4. Open `api/ws_routes.py` — add `camera_frame` / `screen_frame` msg branches
5. Write failing test first → implement → run 48+ test suite

## Read-Order On Resume
1. This file
2. `.planning/ONBOARDING_VOICE_API_PLAN.md` Phase D
3. `memory/feedback_gemini_live_patterns.md`
4. `wiki/pages/gemini-live-multi-turn-config.md`
5. `memory/project_qa_architecture_findings_2026-04-22.md` — Q&A session architectural conclusions (NEW)

## Session Q&A Findings (2026-04-22) — carry into Phase D + E

Captured during pause conversation. Affect Phase D scope and Phase E design.

**Frames vs JSON (Phase D scope tightener):**
- JSON schema stays primary form-driver (cheap, structured, already built).
- Frames = ADDITIVE grounding only — doc OCR (Medicare card in camera) + focused-field hint (screen frame).
- Consider cheaper alternative: mobile sends `{"type":"form_snapshot","focused_field":"dob","filled":{...}}` JSON on focus-change instead of screen JPEG. Same signal, zero image-token cost. Decide in Phase D kickoff.

**Mobile screen-share pipeline (Phase D constraint):**
- Android: `MediaProjection` + per-session consent prompt.
- iOS: `ReplayKit` — partial screen without broadcast extension.
- Bandwidth budget: 2 fps × ~30KB JPEG = ~480 kbps upstream. Cellular-risky.
- Gemini image-token cost non-trivial. Budget check before committing.

**Pagewise context locked (affects Phase E resume design):**
- One WS == one onboarding step — already baked into architecture.
- Resume semantics must work per-step, not across-full-onboarding.

**Tool calling confirmed correct direction:**
- Phase C (`update_field`, `get_session_context`, `advance_step`, `escalate_incident`) = right pattern.
- Do NOT regress to transcript-parsing NER.
- Regex format validators stay INSIDE ToolDispatcher (post-call), not in transcript parser.

**Session resume — two-layer design (Phase E spec refinement):**
- Layer A (hot, <30min): Gemini `session_resumption.handle` via `SessionResumptionConfig`. Native recall.
- Layer B (cold, >30min): FormState replay from Redis + prompt-builder re-inject + prepended `last_summary`.
- NEW piece to build in Phase E: `summary_generator` — on WS close, run `get_session_context` → persist `last_summary` in Redis alongside FormState → prompt includes "Welcome back — last time we covered X, Y. Pick up at Z."

**Phase E acceptance addendum:**
- Kill WS mid-step + reconnect <30min → handle restores natively.
- Kill WS + wait >30min → new session replays FormState + summary, agent opens with "welcome back" line.
