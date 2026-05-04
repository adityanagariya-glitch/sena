---
title: Session Start Guide
updated: 2026-04-30
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
| Voice demo / Gemini Live bugs | `memory/feedback_gemini_live_patterns.md`, `memory/project_voice_demo_working.md` |
| What's left to build (voice) | `.planning/GEMINI_LIVE_NATIVE_SCOPE.md` (Gemini-native only) + `.planning/FEATURES_LEFT.md` (full scope) |
| Case Note Review service (task #10) | `.planning/CASE_NOTE_REVIEW_PLAN.md` — phases A–G, subagent policy, blockers |
| Architecture / code structure | `graphify-out/GRAPH_REPORT.md` |
| NDIS domain / compliance | specific files in `ndis_markdown_docs/` (never the whole folder) |

## 3. DO-NOT-READ

- `/archive/`, `.venv/`, `.vscode/` — token waste, ignored per CLAUDE.md
- `ndis_markdown_docs/` (whole folder) — massive token cost. Read only a specific file when an NDIS compliance question requires it.

---

## ✅ DONE: onboarding 7-rules + voice protocols (2026-05-02)

Task #11 — implemented every rule from `SENA_AI/Issues_left_to_solve.xml` plus interrupt-recovery, silence-watchdog two-step, and Gemini context_window_compression. Tests 78/78. **Plan artifact:** `~/.claude/plans/cozy-waddling-river.md`. **Flutter delta:** Issues 7–9 in `FLUTTER_VOICE_INTEGRATION_FIXES.md`. See TASKS.md #11 for full file list.

**Key entry points for resuming:**
- `models/session_bootstrap.py` — Rule 1/2 envelope; rendered into prompt as `[LIVE_STATE_JSON]`
- `prompts/onboarding_system.md` — fully rewritten with all 7 rules and voice protocols
- `services/screen_context.py::ScreenStateV2.field_errors` — Rule 7 reason hints
- `services/tools.py` — `update_field.values` array parameter (Rule 4); `_readonly_paths` set on dispatcher (Rule 3)

## ✅ DONE: onboarding v2 implemented (2026-04-29)

All 14 files complete. See TASKS.md #9 for full file list. **Next task: Case Note Review #10 Phase D** (`/review` endpoint — risks + restrictive practices + anomalies). Read `.planning/CASE_NOTE_REVIEW_PLAN.md` to resume.

### v2 summary (for reference)
- `screen_state_v2` WS message + `ScreenStateV2` model + `from_v1()` adapter
- `field_apply` envelope drives Flutter GetX controllers directly
- `add_repeatable_row` Gemini tool for growing repeatable sections
- `coverage.py` + `field_apply.py` — pure enforcement modules
- `voice_coverage` / `voice_repeatable_sections` on `StepSchema` (fixtures updated)
- `bio` → `about_me` in `schema_personal_information.json`
- `prompt_version:"v2"` + `coverage` array in ready envelope

### REMOVED: 14-step implementation recipe

**STEP 1 — models/schema_spec.py** (`sena-ai/services/onboarding/src/onboarding/models/schema_spec.py`)
After `sections: list[SectionSpec]` add:
```python
    voice_coverage: list[str] = Field(default_factory=list)
    voice_repeatable_sections: list[str] = Field(default_factory=list)
```

**STEP 2 — models/form_state.py**
After `completed_at: datetime | None = None` add:
```python
    repeatable_rows: dict[str, int] = Field(default_factory=dict)
```
After `def touch(self)` body add new method:
```python
    def increment_repeatable_row(self, section_id: str) -> int:
        current = self.repeatable_rows.get(section_id, 0)
        self.repeatable_rows[section_id] = current + 1
        self.touch()
        return current
```

**STEP 3 — core/settings.py**
After `onboarding_frame_fps_limit: int = 2` add:
```python
    voice_coverage_enforced: bool = True
    field_apply_log_level: str = "DEBUG"
```

**STEP 4 — services/coverage.py** (NEW file — Write tool):
```python
"""Voice coverage check — pure module (no IO)."""
from __future__ import annotations
from onboarding.models.schema_spec import StepSchema

def is_eligible(section_id: str, field_id: str, schema: StepSchema) -> bool:
    if not schema.voice_coverage:
        return False
    return f"{section_id}.{field_id}" in schema.voice_coverage

def is_repeatable_eligible(section_id: str, schema: StepSchema) -> bool:
    return section_id in schema.voice_repeatable_sections

def coverage_paths(schema: StepSchema) -> list[str]:
    return list(schema.voice_coverage)
```

**STEP 5 — services/field_apply.py** (NEW file — Write tool):
```python
"""field_apply envelope builder — pure module (no IO)."""
from __future__ import annotations
import logging
from onboarding.models.schema_spec import StepSchema
from onboarding.services.coverage import is_eligible

log = logging.getLogger(__name__)

def build_envelope(section_id: str, field_id: str, value: object, *, row_index: int | None = None, confidence: float = 1.0, schema: StepSchema, enforced: bool = True) -> dict | None:
    confidence = max(0.0, min(1.0, float(confidence)))
    if enforced and not is_eligible(section_id, field_id, schema):
        log.debug("field_apply_blocked section=%s field=%s", section_id, field_id)
        return None
    return {"type": "field_apply", "section_id": section_id, "field_id": field_id, "row_index": row_index, "value": value, "source": "voice", "confidence": confidence}
```

**STEP 6 — services/screen_context.py** (FULL REWRITE — Write tool, overwrite entire file):
See PRD §screen_state_v2 contract. Key items:
- `ScreenStateV2(BaseModel)`: step_id, focused_section, focused_field, field_status (dict[str, Literal["filled","empty","invalid"]]), repeatable_rows (dict[str,int]), ui_flags (dict[str,Any])
- `ScreenStateV2Message(BaseModel)`: type, data: ScreenStateV2
- Keep `ScreenData` + `ScreenStateMessage` (v1) for adapter
- `from_v1(msg, *, session_step_id) -> ScreenStateV2`: maps current_screen→focused_section, prefilled keys→filled in field_status
- `render_injection_text(state: ScreenStateV2) -> str`: produces multi-line `[SCREEN]\nStep: ...\nFocus: ...\nFilled: ...\nEmpty: ...\nInvalid (re-ask): ...\nRows: ...\nFlags: ...`
- Keep `payload_hash(data: dict) -> str` unchanged

**STEP 7 — services/tools.py** (Edit — 3 changes):
1. Add imports at top: `from onboarding.services.coverage import is_repeatable_eligible` and `from onboarding.services import field_apply as _fa`
2. Add 5th entry to `FUNCTION_DECLS`: `{"name":"add_repeatable_row","description":"Add a new row to a repeatable section. Only for voice-eligible repeatable sections.","parameters":{"type":"object","properties":{"section_id":{"type":"string","description":"Repeatable section id (e.g. ndis_goals)"}},"required":["section_id"]}}`
3. In `dispatch()` handler dict, add: `"add_repeatable_row": self._add_repeatable_row`
4. In `_update_field()`, after the existing two `self._emit(...)` calls, add:
```python
        envelope = _fa.build_envelope(section_id, field_id, typed_value, row_index=repeatable_index if section.is_repeatable else None, confidence=confidence, schema=self._schema, enforced=settings.voice_coverage_enforced)
        if envelope is not None:
            await self._emit(envelope)
```
5. Add new `_add_repeatable_row` handler method:
```python
    async def _add_repeatable_row(self, args: dict) -> dict:
        section_id = args.get("section_id", "").strip()
        if not section_id: return {"ok": False, "error": "section_id required"}
        section = self._schema.get_section(section_id)
        if section is None: return {"ok": False, "error": f"unknown section: {section_id}"}
        if not section.is_repeatable: return {"ok": False, "error": f"not repeatable: {section_id}"}
        if not is_repeatable_eligible(section_id, self._schema): return {"ok": False, "error": f"section not voice-eligible: {section_id}"}
        state = await self._repo.get_state(self._session_id)
        if state is None: return {"ok": False, "error": "session state not found"}
        new_row_index = state.increment_repeatable_row(section_id)
        await self._repo.save_state(state, ttl_sec=settings.session_max_sec)
        await self._emit({"type": "row_added", "section_id": section_id, "new_row_index": new_row_index})
        return {"ok": True, "new_row_index": new_row_index}
```

**STEP 8 — services/prompt_builder.py** (Edit):
Add helper before `build_system_prompt`:
```python
def _voice_coverage_section(voice_coverage: list[str]) -> str:
    if not voice_coverage:
        return ""
    return "\nVOICE COVERAGE\nOnly collect values for these fields — do NOT ask about any others:\n" + "\n".join(f"  - {p}" for p in voice_coverage)
```
In `build_system_prompt`, add to replacements: `.replace("__VOICE_COVERAGE_SECTION__", _voice_coverage_section(schema.voice_coverage))`

**STEP 9 — services/gemini_live.py** (Edit — 3 changes):
1. Update import block to add: `ScreenStateV2Message, from_v1,` to the screen_context import
2. In `_handle_control`, add after the `screen_state` block:
```python
        elif msg_type == "screen_state_v2":
            await self._handle_screen_state(session, data, version=2)
```
3. Update `_handle_screen_state` signature to `(self, session, data, *, version: int = 1)` and body: for v2 parse `ScreenStateV2Message`, for v1 parse `ScreenStateMessage` then call `from_v1()`. Both pass a `ScreenStateV2` to `render_injection_text`.

**STEP 10 — api/ws_routes.py** (Edit — 2 changes):
1. Change `"prompt_version": "v1"` → `"prompt_version": "v2"`
2. Add `"coverage": schema.voice_coverage,` to the `ready` envelope dict

**STEP 11 — prompts/onboarding_system.md** (Edit):
1. Update the `[SCREEN]` rule in CRITICAL RULES to say: "When you receive a block starting with [SCREEN], use it to understand focus. Filled: = skip. Invalid (re-ask): = revisit. Focus: = prioritise next. Flags: = toggle states."
2. After `__GROUNDING_SECTION__` add `__VOICE_COVERAGE_SECTION__` on a new line
3. Update the `update_field` rule to add: "Never call update_field for a field not listed in VOICE COVERAGE."

**STEP 12 — 5 fixture files** (Edit each):
- `fixtures/schema_personal_information.json`: (a) rename `"id": "bio"` → `"id": "about_me"`, `"label": "A bit about me"` → `"label": "About Me"`, `"required": true` → `"required": false`. (b) After `"progress_percent": 20,` add: `"voice_coverage": ["basics.full_name","basics.date_of_birth","basics.phone","basics.email","basics.about_me"], "voice_repeatable_sections": [],`
- `fixtures/schema_ndis_plan_details.json`: After `"progress_percent": 60,` add: `"voice_coverage": ["plan_info.ndis_number","plan_info.plan_start","plan_info.plan_end","plan_info.plan_management"], "voice_repeatable_sections": ["ndis_goals"],`
- `fixtures/schema_participant_requirements.json`: After `"progress_percent": 40,` add: `"voice_coverage": [], "voice_repeatable_sections": [],`
- `fixtures/schema_documents.json`: After `"progress_percent": 80,` add: `"voice_coverage": [], "voice_repeatable_sections": [],`
- `fixtures/schema_medical_information.json`: After `"progress_percent": 100,` add: `"voice_coverage": [], "voice_repeatable_sections": [],`

**STEP 13 — HANDOFF_VOICE_ONBOARDING.md** (Write — full rewrite): Document v2 protocol: screen_state_v2 shape, field_apply envelope, row_added envelope, ready envelope with coverage list, voice coverage matrix per step, v1 adapter window note. Keep REST endpoints table. Update WS events table to include field_apply + row_added.

**STEP 14 — post-tool-use.sh** (Edit): After the pipreqs block, add a doc-update trigger: when the tool touches any file in `services/onboarding/src/onboarding/` (services/, models/, api/, fixtures/), regenerate `HANDOFF_VOICE_ONBOARDING.md` and `services/onboarding/docs/FLUTTER_VOICE_INTEGRATION.md` by appending a note: "⚠ Run: update HANDOFF and FLUTTER_VOICE_INTEGRATION.md after this session's changes."

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
| `Stop` | `.claude/hooks/stop.sh` | Rebuilds graphify graph + emits reminder to verify `TASKS.md` at every session boundary (including /clear, /compact, resume) |
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
