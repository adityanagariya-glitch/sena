---
title: Wiki Log
type: topic
tags: [log, changelog]
created: 2026-04-15
updated: 2026-04-17
---

# Wiki Log

Append-only chronological record of wiki operations. Newest entries at the bottom.

---

## [2026-04-15] bootstrap | Archive Ingestion

Batch ingestion of all archive/ documents to seed the wiki. Sources processed: TECHNICAL_DECISIONS, SENA_Architecture_Audit, FlowB, QUESTIONS_FOR_CLIENT, REMAINING_QUESTIONS, MULTI_AGENT_SYSTEM_DESIGN, plan series (5 files), SPRINT_0_PLAN + related sprint docs, voice-assistant-repo-research, voice_architecture_analysis, reporesearch. Also referenced: .planning/PROJECT.md, .planning/REQUIREMENTS.md.

**Pages created:**
- `wiki/index.md` -- master index with categorised links to all wiki pages
- `wiki/overview.md` -- living synthesis of SENA project state
- `wiki/log.md` -- this file
- `wiki/NDIS.md` -- hub for NDIS domain knowledge
- `wiki/Architecture.md` -- hub for technical architecture
- `wiki/Client-Requirements.md` -- hub for client requirements and integration

**Source summaries:** 15 placeholder entries registered in index (to be expanded on individual ingest).

**Detail pages:** 30+ page stubs registered in index across entities, concepts, decisions, and topics (to be created as individual pages during source-by-source ingest).

---

## [2026-04-16] lint | Full Wiki Lint Pass

Ran full lint pass covering: orphan pages, broken wikilinks, missing pages for frequently-mentioned entities, contradictions between pages, and missing cross-references.

**Findings and fixes:**

- **0 orphan pages** — all pages have ≥2 inbound links. No action needed.
- **Broken wikilink `[[postgres]]`** — fixed in previous session (points to `[[pgvector|PostgreSQL]]`). Confirmed clean.
- **Source status** — updated all 15 source entries in index from "placeholder" → "ingested".
- **11 orphan pages not in index** — added all to index.md (approval-workflow, auth-mode-decision, aws-sns, cloud-provider-decision, flow-b-voice-dictation, llm-provider-decision, ndia, plan-evolution, rate-limiting, sena-common, team-capacity).
- **Contradiction flagged** — `llm-provider-decision.md` described a Gemini Live + Bedrock split stack as decided, but the current codebase uses Bedrock only. Added `[!warning]` callout marking Gemini Live as planned/not-yet-implemented.
- **3 missing pages created** — `ndis-participant.md`, `support-worker.md`, `personal-details-flow.md` (all referenced in code and requirements but had no wiki page).
- **Cross-references added** — Architecture hub updated with approval-workflow, personal-details-flow, flow-b-voice-dictation, support-worker, ndis-participant sections. approval-workflow.md Connections updated to include [[sns-events]] and [[support-worker]].

**Web search gaps flagged (not yet filled — require external sources):**
- Current NDIS Practice Standards version and digital record-keeping requirements
- Australian Privacy Act APP 8/11 specifics for cloud-hosted health/disability data
- LiveKit v2 SDK breaking changes (client team owns mobile SDK integration)

## [2026-04-16 00:23:07] tool-use | Edit
File modified: test.py

---

## [2026-04-16] update | Gemini Integration + Hooks + CLAUDE.md Sync

**Gemini LLM integration (personal details onboarding flow):**
- Created `sena-ai/services/voice/src/voice/services/gemini_service.py` — `GeminiService` with identical interface to `BedrockService.run_personal_details_turn()`. Uses `google-genai` SDK, `gemini-2.0-flash` model, reuses existing prompts verbatim.
- Updated `personal_details_service.py` — swapped `BedrockService` → `GeminiService`
- Updated `api/routes.py` — instantiates `GeminiService`, passes to `PersonalDetailsService`; Flow B dictation unchanged (still Bedrock)
- Added `google-genai>=1.0.0` to `services/voice/pyproject.toml`
- Added `SENA_AI_GEMINI_API_KEY` + `SENA_AI_GEMINI_MODEL_ID` to `settings.py` and `.env.example`

**Hooks created:**
- `.claude/hooks/post-tool-use.sh` — auto-regenerates `requirements.txt` per service using `pipreqs` whenever a `.py` file is edited. Activates `.venv` at repo root before running so versions match venv packages.
- `.claude/hooks/pre-tool-use.sh` — minimal stub (was registered in settings.json but missing)

**CLAUDE.md synced with root:**
- Added root-level file tree (`api_contracts.py`, `AGENTS.md`, `requirements.txt`)
- Updated `sena-ai/` tree to include `migrations/`, `scripts/`, `Makefile`
- Corrected "No API contracts exist" → `api_contracts.py` exists at root
- Added LLM split table (Gemini for personal details, Bedrock for Flow B)
- Added Setup Rules section (Context7 + Playwright MCP)

**Wiki pages updated:**
- `llm-provider-decision.md` — removed divergence warning, updated status to PARTIALLY IMPLEMENTED, added implementation details
- `personal-details-flow.md` — architecture section updated to reflect GeminiService, added GEMINI_API_KEY requirement

---

## [2026-04-17] update | Gemini Live API Migration + Demo + Cleanup

**Gemini Live API integration (real-time bidirectional voice):**
- Created `sena-ai/demo_live_server.py` — standalone FastAPI server bridging browser WebSocket ↔ Gemini Live. No DB/Redis/auth — pure audio pipeline for demo/testing.
- Created `sena-ai/demo_client.html` — browser UI with mic capture (16 kHz PCM16 downsample), audio playback (24 kHz), and file-upload test mode.
- Created `sena-ai/services/voice/src/voice/services/gemini_live_service.py` (production version) + `sena-ai/services/voice/src/voice/api/ws_routes.py` (production WebSocket endpoint).
- Added `SENA_AI_GEMINI_LIVE_MODEL_ID` to `core/settings.py` + `.env`.

**Model migration — IMPORTANT:**
- **From:** `gemini-2.5-flash-native-audio-latest` (deprecated, closes session after first turn when triggered by text input)
- **To:** `gemini-3.1-flash-live-preview` (current stable Live model)
- Updated: `.env`, `demo_live_server.py` default, `settings.py` default.

**API surface migration — IMPORTANT:**
- `session.send(input=..., end_of_turn=True)` — REMOVED. This maps to `send_client_content` which is now reserved for seeding initial history.
- `LiveClientRealtimeInput(media_chunks=[Blob(...)])` — REMOVED. Old wire format.
- `session.send_realtime_input(audio=Blob(...))` — NEW pattern for audio.
- `session.send_realtime_input(text="...")` — NEW pattern for text mid-conversation.
- `session.send_realtime_input(audio_stream_end=True)` — NEW signal to flush VAD when mic pauses.
- `Content(parts=[...], role="user")` on `system_instruction` — removed `role` field (not in current docs).

**Session lifecycle fix:**
- `asyncio.wait([b2g, g2b], return_when=FIRST_COMPLETED)` — REMOVED. Killed the Gemini session as soon as `session.receive()` drained one turn.
- Replaced with: `await b2g; finally: g2b.cancel()` — session stays alive until the BROWSER disconnects.

**Proactive audio limitation:**
- `gemini-3.1-flash-live-preview` does NOT support proactive audio (model speaking first without user input). Removed server-side text greeting trigger. Greeting now happens when user first speaks (system prompt instruction).

**Tooling setup:**
- Installed `gemini-live-api-dev` and `gemini-api-dev` skills globally via `npx skills add google-gemini/gemini-skills`.
- Added `gemini-api-docs-mcp` MCP server (`https://gemini-api-docs-mcp.dev`) via `claude mcp add`.

**Cleanup (dead code removal):**
- Deleted: `sena-ai/test_gemini.py`, `sena-ai/test_gemini_live.py` (untracked smoke tests)
- Deleted: `sena-ai/services/voice/requirements.txt`, `sena-ai/services/ocr/requirements.txt` (untracked/empty)
- Deleted: `sena-ai/services/ocr/Dockerfile`, `services/ocr/src/ocr/api/`, `core/`, `models/`, `service/`, `tests/` (scaffold-only)
- Minimized: `services/ocr/src/ocr/main.py` (was 35 lines of comments → 10 lines of working stub)
- NOT deleted (audit false-positive): `services/voice/src/voice/services/gemini_service.py` — actively called at runtime by HTTP `/v1/voice/personal-details/session/turn` via `personal_details_service.py:128`.

**Pages Updated:**
- `llm-provider-decision.md` — model version updated, Live API section added
- `personal-details-flow.md` — dual-mode architecture (HTTP REST + WebSocket Live), demo stack documented

**Outstanding:**
- Voice demo still not behaving conversationally — needs push-to-talk button instead of continuous mic (tracked in tasks).

---

## [2026-04-17] update | Voice demo multi-turn WORKING

4+ hour debug session. Demo pivoted from push-to-talk → continuous streaming + native VAD. End-to-end multi-turn conversation verified via `USER_SAID` / `GEMINI_SAID` transcription logs.

**Root causes found and fixed:**
1. `session.receive()` in google-genai SDK returns after each turn batch — not at session end. Outer `while True` with `continue` on iterator-end is required. A `return` silently killed conversations after turn 1.
2. Multi-turn on `gemini-3.1-flash-live-preview` requires explicit `realtime_input_config` with `automatic_activity_detection`. Without it, Gemini closes session after first turn → `1011 keepalive timeout`.
3. `asyncio.wait(FIRST_COMPLETED)` tore down session when g2b exited. Reverted to `await b2g`.
4. Windows Chrome browser playback — dual AudioContext (mic + playback) silently drops output. Consolidated to single shared AudioContext.
5. Browser's internal 24kHz→native resampler fails silently on some Windows drivers. Added manual linear-interp upsample.
6. `playCtx.resume()` not awaited before scheduling = silent playback against frozen clock. Awaited now with 80ms lookahead.

**Pages Updated:**
- `wiki/pages/gemini-live-multi-turn-config.md` — NEW. Authoritative reference for future Gemini Live work.
- `wiki/pages/personal-details-flow.md` — should be reviewed next session to reflect new demo state.

**Memories written:**
- `feedback_gemini_live_patterns.md` — hard rules for multi-turn (session.receive loop, VAD config, browser playback)
- `project_voice_demo_working.md` — demo stack current state + run command

