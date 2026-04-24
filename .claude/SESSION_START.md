---
title: Session Start Guide
updated: 2026-04-24
purpose: Single entry-point doc. Future-Claude reads this FIRST in a new session to land in same state.
---

# Read-order for resuming SENA work

Read these files IN ORDER at the start of any new session. Stop when you have enough context for the user's current request.

## 1. MUST-READ (always)

| # | File | Why |
|---|------|-----|
| 1 | `CLAUDE.md` (project root) | Hard rules, architecture, Gemini API rules, cleanup rule, demo stack |
| 2 | `.claude/SESSION_START.md` (this file) | Tells you what to read next |
| 3 | `.claude/tasks/TASKS.md` | Current task state, active/completed/backlog |
| 4 | `.claude/issues-solved/INDEX.md` | Grep-first symptom→fix table. Check BEFORE debugging anything. |
| 5 | `.planning/ONBOARDING_VOICE_API_PLAN.md` | Active build plan — onboarding voice API, phases A–F. Follow this plan exactly. |
| 6 | `~/.claude/projects/C--Users-Admin-Downloads-SENA/memory/MEMORY.md` | Memory index — points to all user/project/feedback memories |

## 2. READ-IF-RELEVANT (task-dependent)

| Task area | Read |
|-----------|------|
| Voice demo / Gemini Live bugs | `wiki/pages/gemini-live-multi-turn-config.md`, `memory/feedback_gemini_live_patterns.md`, `memory/project_voice_demo_working.md` |
| What's left to build (voice) | `.planning/GEMINI_LIVE_NATIVE_SCOPE.md` (Gemini-native only) + `.planning/FEATURES_LEFT.md` (full scope) |
| Case Note Review service (task #10) | `.planning/CASE_NOTE_REVIEW_PLAN.md` — phases A–G, subagent policy, blockers |
| Architecture / domain | `wiki/index.md` → follow wikilinks |
| Code-level structure | `graphify-out/GRAPH_REPORT.md` |
| NDIS domain | `wiki/NDIS.md` (synthesis) + `ndis_wiki/index.md` (regulatory sources) |
| Client spec gaps | `wiki/pages/open-questions.md` |

## 3. DO-NOT-READ

- `/archive/`, `.venv/`, `.vscode/` — token waste, ignored per CLAUDE.md
- `ndis_markdown_docs/` — raw NDIS source docs, massive token cost. Use `ndis_wiki/` pages instead. Only read this if `ndis_wiki/` genuinely doesn't answer the question — and only the specific file, never the whole folder.
- Raw source docs — wiki pages already synthesize these

---

## Current state snapshot (2026-04-24)

**What works:**
- Voice demo (`sena-ai/demo_live_server.py` + `demo_client.html`) — multi-turn conversation end-to-end
- Docker infra (Redis + ai-db pgvector + shared-db)
- **Onboarding service Phase A** (`sena-ai/services/onboarding/`) — 36/36 tests passing
  - REST API: session create/get/put/complete + health
  - Redis FormStateRepo (state, schema, transcript, WS lock, resumption handles)
  - Webhook dispatcher (3-retry exp backoff)
  - StepSchema + FormState Pydantic models (visible_if, repeatable sections)
  - 5 fixture schemas from real app screens (personal info → medical)
- **Onboarding service Phase B** — WS + Gemini Live + form-aware system prompt (2026-04-21)
  - `api/ws_routes.py` — start handshake, WS lock, ready event, error close codes
  - `services/gemini_live.py` — b2g/g2b tasks, VAD config, transcript→Redis, JSON events
  - `services/prompt_builder.py` — renders schema + FormState into system_instruction
  - `prompts/onboarding_system.md` — prompt template with `__PLACEHOLDER__` markers
- **Onboarding service Phase C** — Tool calling (2026-04-21, 48/48 tests)
  - `services/tools.py` — `ToolDispatcher` + `FUNCTION_DECLS` (4 tools)
  - `update_field` — schema-validated, coerces types, emits `field_updated` + `state`
  - `get_session_context` — condensed {filled, missing_required, completion}
  - `advance_step` — re-validates completion → fires webhook → emits `step_completed`, flags WS close
  - `escalate_incident` — appends `EscalationRecord`, emits `escalated`, session continues
  - `gemini_live.py` — `tools=[Tool(function_declarations=...)]` + `msg.tool_call` branch + `send_tool_response`
  - `g2b.add_done_callback` cancels `b2g` when step completes (unblocks WS)
- **Onboarding service Phase F (partial)** — browser test harness (2026-04-21)
  - `sena-ai/services/onboarding/test_harness.html` — Phase A/B/C panels, transcript, live form render, completion bar
  - `main.py` — `GET /harness` + `GET /harness/fixtures/{step_id}` routes added (path-traversal guarded)
  - **IMPORTANT:** service uses src-layout → must `pip install -e .` from `sena-ai/services/onboarding/` before uvicorn
- **Case Review service Phase A** (`sena-ai/services/case_review/`) — scaffold complete (2026-04-24)
  - 4 DB tables: `rolling_summary`, `review_session`, `incident_draft`, `review_audit_log`
  - RLS policies on `tenant_id` (legal mandate)
  - Stub `CaseNoteClient` returning fixture notes from `fixtures/sample_notes.json`
  - All 6 endpoints stubbed (501), health routes live
  - 22/22 tests passing
- **Case Review service Phase B** — `/context` rolling summary (2026-04-24) ✓
  - `services/llm/summarizer.py` — Gemini `gemini-3-flash-preview` structured output
  - `services/context_service.py` — fetch → diff `processed_note_ids` → LLM → upsert (idempotent)
  - `POST /v1/case-review/context` returns real Gemini-processed summary
  - Dev defaults prefilled: empty `{}` body works, no headers required
  - DB creds: `sena_ai:sena_ai@localhost:5433/sena_ai`

**How to run case review service:**
```bash
cd sena-ai/services/case_review
pip install -e .          # required once — src-layout editable install
uvicorn src.case_review.main:create_app --factory --reload --port 8084
# Test: curl -s -X POST http://localhost:8084/v1/case-review/context -H "Content-Type: application/json" -d '{}'
```

**How to run onboarding service:**
```bash
cd sena-ai/services/onboarding
pip install -e .          # required once — src-layout editable install
uvicorn src.onboarding.main:create_app --factory --reload --port 8083
# Test harness: http://localhost:8083/harness
```

**What's next (Case Review):**
Phase C — `/classify` paragraph → structured fields + reask prompts
- `services/llm/classifier.py` — Gemini structured output → `{classified_fields, missing_required, confidence}`
- `prompts/classify.md` — system prompt with field schema injected
- `services/classify_service.py` — persists to `review_session`, logs to `review_audit_log`
- Re-ask: if `missing_required` non-empty, response includes `reask_prompts`

**What's next (Onboarding — PAUSED):**
Phase D — Vision ingress (camera + screen frames) — BLOCKED (office dep)
- Resume via `.planning/paused_state_phase_d_camera_screen_ingress.md`

**Blocked:**
- Case Review Phase F (submit gate) — waiting on other engineer's register schema
- RAG (NDIS docs) — waiting client sample docs
- Multi-tenant auth / RLS — waiting client JWT claims structure
- OCR service — waiting document samples

---

## How to verify state on session start

Run these to confirm nothing rotted since 2026-04-21:

```bash
# 1. Demo still runs?
cd sena-ai && uvicorn demo_live_server:app --reload --port 8082
# Open http://localhost:8082 → Start → speak → expect reply

# 2. Git clean?
git status
git log --oneline -10

# 3. Env file present?
ls sena-ai/.env  # must contain SENA_AI_GEMINI_API_KEY + SENA_AI_GEMINI_LIVE_MODEL_ID=gemini-3.1-flash-live-preview
```

If demo breaks: first suspect `session.receive()` retry loop (`while True: ... continue`) and `realtime_input_config` presence. See `feedback_gemini_live_patterns.md`.

---

## Hook-enforced maintenance (how these docs stay live)

Three hooks in `.claude/settings.json` keep this system deterministic:

| Hook | Script | What it does |
|------|--------|--------------|
| `SessionStart` | `.claude/hooks/session-start.sh` | Injects this read-order as additionalContext on every new session — Claude sees the protocol before the first prompt |
| `Stop` | `.claude/hooks/stop.sh` | Emits reminder to verify `TASKS.md` is current at every session boundary (including /clear, /compact, resume) |
| `PostToolUse` (Write\|Edit) | `.claude/hooks/bump-updated.sh` | Auto-bumps `updated: YYYY-MM-DD` frontmatter on SESSION_START.md, TASKS.md, MEMORY.md, CLAUDE.md whenever Claude edits them |

**You never need to manually update `updated:` fields.** The hook does it. If a file lacks frontmatter (e.g., CLAUDE.md), the hook no-ops safely.

If a hook seems broken: check `/hooks` menu, or run `bash .claude/hooks/<name>.sh` directly with a fake stdin payload to diagnose.

---

## Rules you MUST reload every session

From `CLAUDE.md`:
- Gemini code → invoke `Skill: gemini-live-api-dev` BEFORE editing
- Use `send_realtime_input(audio=Blob(...))` — NOT `session.send(LiveClientRealtimeInput(...))`
- Current model: `gemini-3.1-flash-live-preview`
- Do NOT delete "dead code" without grepping full codebase first
- NEVER read `/archive`, `.venv`, `.vscode`

From memory (`feedback_gemini_live_patterns.md`):
- `session.receive()` returns per-turn — wrap in `while True` with `continue`
- Multi-turn REQUIRES `realtime_input_config` with explicit VAD
- Use `await b2g`, not `asyncio.wait(FIRST_COMPLETED)`
- Single AudioContext on browser for mic+playback
- Manual 24kHz→native upsample before `createBuffer`
- **NEVER gate mic audio on `_agent_speaking` flag** — causes VAD to die after 2-4 turns. Send audio unconditionally; Gemini's native VAD + `START_OF_ACTIVITY_INTERRUPTS` handles barge-in.
- Use `START_SENSITIVITY_LOW` — HIGH fires on ambient noise and exhausts VAD budget
