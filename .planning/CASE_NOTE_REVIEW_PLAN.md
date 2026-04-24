---
title: Case Note Review Service — Build Plan
updated: 2026-04-23
status: in_progress
phase: A (not started)
owner: pair-programming (AI-layer engineer)
service_path: sena-ai/services/case_review/
port: 8084
db: ai-db (port 5433, pgvector)
---

# Case Note Review — Implementable Build Plan

> **Portable plan** — any Claude/AI session can resume from this file alone. Read-order, phase gates, subagent assignments, and acceptance criteria are all here.

## 0. Resume protocol (new session? start here)

1. Read `CLAUDE.md` (project root) — hard rules
2. Read `.claude/SESSION_START.md` — session read-order
3. Read `.claude/tasks/TASKS.md` — find task #10 (Case Note Review)
4. Read THIS file — authoritative build plan
5. Check git log for last commit matching `case-review` → resume from next unchecked task in current phase
6. Verify service boots: `cd sena-ai/services/case_review && pip install -e . && uvicorn src.case_review.main:create_app --factory --reload --port 8084`

---

## 1. Context

**What this service is:**
SENA platform has case note workflow. Support workers meet clients, draft case notes after. Another engineer builds the **drafting** service (form fill, DB persist). We build the **review + intelligence layer** around it.

**Our job = 6 stages:**
1. Pre-meeting context brief (rolling summary of last 10 notes)
2. Paragraph input classification (free text → fields)
3. Missing-field re-ask loop
4. Risk + restrictive-practice + anomaly detection
5. Incident detection + autofill draft
6. Submit gate → case note register

**What we do NOT own:**
- Case note storage (other engineer's service)
- Draft form UI (other engineer)
- Case note register schema (TBD — webhook vs shared schema, waiting on other engineer)

**Source of truth for case notes:** other engineer's API. We call `GET /case-notes?staff_id=&client_id=&limit=10` → returns `{ note_id, date, transcript, drafted_note, staff_id, client_id }[]`. Until real API lands, stub returns fixtures.

---

## 2. Architecture boundary

```
┌────────────────────────┐           ┌─────────────────────────┐
│  Other engineer's      │◄──fetch───│  case_review (us, 8084) │
│  drafting service      │           │                         │
│  - stores case notes   │           │  - rolling_summary DB   │
│  - stores transcripts  │           │  - review_session DB    │
│  - exposes GET API     │           │  - incident_draft DB    │
└────────────────────────┘           │  - audit_log DB         │
        ▲                            │  - LLM classify/review  │
        │                            │  - LLM summary compress │
        └──webhook/shared schema─────┤  - incident autofill    │
          (submit path, TBD)         └─────────────────────────┘
```

---

## 3. DB schema (ai-db, Postgres 16 + pgvector)

```sql
rolling_summary
  id UUID PK
  tenant_id UUID NOT NULL
  staff_id  UUID NOT NULL
  client_id UUID NOT NULL
  summary_text TEXT
  metadata JSONB                    -- {note_count, last_dates[], incident_count, risk_flags[]}
  processed_note_ids TEXT[]          -- replay-proof double-process guard
  updated_at TIMESTAMP
  created_at TIMESTAMP
  UNIQUE (tenant_id, staff_id, client_id)

review_session
  id UUID PK
  tenant_id UUID NOT NULL
  staff_id UUID, client_id UUID
  drafted_case_note_id TEXT          -- FK-by-ID to other engineer's note
  raw_paragraph TEXT
  classified_fields JSONB
  missing_fields JSONB
  flags JSONB                        -- {risks[], restrictive_practices[], anomalies[], improvements[]}
  incident_detected BOOL DEFAULT false
  status TEXT                        -- input|classified|reviewed|submitted
  created_at, updated_at

incident_draft
  id UUID PK
  tenant_id UUID NOT NULL
  review_session_id UUID NULL FK → review_session(id)
  autofill_source JSONB
  draft_fields JSONB
  staff_confirmed BOOL DEFAULT false
  status TEXT                        -- draft|confirmed|submitted
  created_at

review_audit_log
  id UUID PK
  tenant_id UUID NOT NULL
  review_session_id UUID FK → review_session(id)
  actor_user_id UUID
  action TEXT                        -- ai_flag_raised|staff_acknowledged|submitted|...
  payload JSONB
  created_at TIMESTAMP
```

RLS policies on all 4 tables, scoped by `tenant_id`. Mirror pattern from voice service.

---

## 4. API surface

```
POST   /v1/case-review/context          # pre-meeting: fetch + summarize last N notes
POST   /v1/case-review/classify         # paragraph → field map + missing list
POST   /v1/case-review/review           # risk flags + restrictive practices + anomalies
POST   /v1/case-review/incident/detect  # detect incident in case note text
POST   /v1/case-review/incident/draft   # autofill incident form from case note
POST   /v1/case-review/submit           # final gate → write to register
GET    /health/live, /health/ready
```

All routes require `tenant_id` in auth context. Dev-mode header auth for now (consistent with voice service).

---

## 5. Phase breakdown

Each phase = atomic commit-ready unit. Do NOT cross phase boundaries in one PR.

### Phase A — Scaffold + DB + stub client
**Goal:** service boots, 4 tables exist, stub returns fixture notes.
**Subagent:** `general-purpose` for scaffold generation; `Explore` to copy patterns from onboarding service.

- [x] A1. Create `sena-ai/services/case_review/` skeleton (mirror onboarding layout)
- [x] A2. `pyproject.toml` — deps: fastapi, sqlalchemy[asyncio], asyncpg, alembic, pydantic-settings, httpx, google-genai
- [x] A3. `src/case_review/core/settings.py` — Pydantic settings, `SENA_AI_` prefix
- [x] A4. `src/case_review/models/db.py` — SQLAlchemy ORM for 4 tables
- [x] A5. `src/case_review/models/schemas.py` — Pydantic DTOs (request/response for all 6 endpoints)
- [x] A6. `src/case_review/repositories/review_repo.py` — CRUD for all 4 tables, upsert for rolling_summary
- [x] A7. `src/case_review/clients/case_note_client.py` — stub returning fixture DTOs
- [x] A8. `src/case_review/api/routes.py` — stubbed 6 endpoints returning 501 + health routes
- [x] A9. `src/case_review/main.py` — FastAPI app factory
- [x] A10. Alembic init + 1 migration: create 4 tables + RLS policies
- [x] A11. `fixtures/sample_notes.json` — 3 fake case notes for stub client
- [x] A12. `tests/test_repo.py` — repo CRUD tests (pytest-asyncio)
- [x] A13. `tests/test_routes.py` — route smoke tests (all return expected shape even if 501)
- [x] A14. Add service to `docker-compose.yml`
- [x] A15. Update `sena-ai/.env.example` with new vars

**Acceptance:** `pytest services/case_review/tests/` green. `curl localhost:8084/health/ready` → 200. Alembic upgrade clean.

**Commit:** `feat(case_review): Phase A scaffold + DB schema + stub client`

---

### Phase B — Context endpoint (rolling summary) ✓ COMPLETE (2026-04-24)
**Goal:** `/context` fetches notes, compresses to rolling summary, returns brief.
**Verified:** real Gemini API call end-to-end with fixture data. Dev defaults prefilled in deps + schemas (empty body `{}` works).

- [x] B1. `services/llm/summarizer.py` — Gemini-based compressor. Input: `(past_summary, new_notes[])`. Output: `{summary_text, metadata}`
- [x] B2. `prompts/summarize.md` — prompt template with `{past_summary}` + `{new_notes}` placeholders
- [x] B3. `services/context_service.py` — orchestrates: fetch via `CaseNoteClient` → diff against `processed_note_ids` → summarize → upsert
- [x] B4. Wire `POST /v1/case-review/context` → returns `{ summary_text, metadata, notes_included: N }`
- [x] B5. Tests: cold-start (no prior summary), incremental update, replay-guard (same note twice → no-op)
- [ ] B6. Fixture: add 5 more fake notes spanning 3 months for realistic compression test

**Acceptance:** calling `/context` twice in a row returns same summary (idempotent). Adding new note updates summary + metadata.

**Commit:** `feat(case_review): Phase B context + rolling summary`

---

### Phase C — Paragraph classifier + re-ask loop
**Goal:** paragraph → structured field map + missing list.
**Subagent:** Skill `gemini-api-dev`. Use structured output (JSON schema) for reliability.

- [ ] C1. Define temporary case-note field schema (freeze once figma arrives — park as `models/case_note_field_schema.py`)
- [ ] C2. `services/llm/classifier.py` — Gemini structured output → `{classified_fields: {...}, missing_required: [...], confidence: {...}}`
- [ ] C3. `prompts/classify.md` — system prompt with field schema injected
- [ ] C4. `services/classify_service.py` — persists to `review_session`, logs to `review_audit_log`
- [ ] C5. Wire `POST /v1/case-review/classify` → creates or updates review_session
- [ ] C6. Re-ask endpoint behavior: if `missing_required` non-empty, response includes `reask_prompts: [...]`
- [ ] C7. Tests: full paragraph classifies cleanly; thin paragraph returns reask prompts; malformed JSON from LLM is retried

**Acceptance:** ~80%+ field fill on well-formed paragraph; reask prompts surface for thin input.

**Commit:** `feat(case_review): Phase C paragraph classify + reask`

---

### Phase D — Review layer (risks + restrictive practices + anomalies)
**Goal:** analyze classified fields + compare against history → flags.
**Subagent:** `Explore` to pull restrictive-practice taxonomy from `ndis_wiki/pages/concepts/`. NEVER invent categories.

- [ ] D1. Pull restrictive-practice taxonomy from `ndis_wiki/` (physical, chemical, mechanical, environmental, seclusion — canonical NDIS Code of Conduct categories)
- [ ] D2. `services/llm/reviewer.py` — Gemini with structured output. Input: `(classified_fields, rolling_summary, taxonomy)`. Output: `{risks[], restrictive_practices[], anomalies[], improvements[]}`
- [ ] D3. `prompts/review.md` — injects NDIS taxonomy + rolling summary context
- [ ] D4. `services/review_service.py` — runs reviewer, writes flags to `review_session`, logs each flag to audit
- [ ] D5. Wire `POST /v1/case-review/review` → returns full flag set
- [ ] D6. Tests: restrictive practice detection (synthetic case with physical restraint), anomaly vs history, false-positive baseline

**Acceptance:** known restrictive-practice markers trigger specific taxonomy category; low false-positive rate on benign notes.

**Commit:** `feat(case_review): Phase D review layer (risks + restrictive + anomalies)`

---

### Phase E — Incident detection + autofill draft
**Goal:** AI flags incident from case note → pre-fills incident form → staff confirms.
**Subagent:** Skill `gemini-api-dev`. Coordinate with other engineer on incident form schema.

- [ ] E1. Confirm incident form schema (ask other engineer — park if not available, stub field set)
- [ ] E2. `services/llm/incident_detector.py` — binary classifier + extracted markers
- [ ] E3. `services/incident_service.py` — on detect → insert `incident_draft` row → return to UI for staff confirm
- [ ] E4. Wire `POST /v1/case-review/incident/detect` + `POST /v1/case-review/incident/draft`
- [ ] E5. Staff confirm flow: `PATCH /v1/case-review/incident/{id}/confirm` flips `staff_confirmed`
- [ ] E6. Tests: incident trigger, no-false-positive, draft persistence, confirm flow

**Acceptance:** incident markers (injury, medication error, behavioural incident) trigger draft; non-incident case notes do not.

**Commit:** `feat(case_review): Phase E incident detect + autofill`

---

### Phase F — Submit gate + routing
**Goal:** final submit endpoint that writes to case note register + routes incident separately.
**Subagent:** `general-purpose` — blocked on other engineer's decision (webhook vs shared schema).

- [ ] F1. Decide routing (unblock: ask other engineer). Options: webhook to their service, or direct write to shared table.
- [ ] F2. `services/submit_service.py` — validates all flags acknowledged → commits review_session status=submitted → fires webhook/write
- [ ] F3. Incident route: if `incident_detected && staff_confirmed` → separate submission channel
- [ ] F4. Wire `POST /v1/case-review/submit`
- [ ] F5. Audit log entry per submit
- [ ] F6. Tests: happy path, unacknowledged-flag rejection, incident route triggered

**Acceptance:** submit writes durable record + fires downstream notification.

**Commit:** `feat(case_review): Phase F submit gate + routing`

---

### Phase G — Hardening + docs (optional but recommended)

- [ ] G1. OpenAPI spec published at `/openapi.json`
- [ ] G2. `openapi/` dir with exported schema for mobile team
- [ ] G3. Rate limiting (Redis token bucket) on LLM endpoints
- [ ] G4. Structured logging (JSON) — all events
- [ ] G5. Add routes to root `api_contracts.py`
- [ ] G6. README.md for service

---

## 6. Subagent usage policy (per-phase)

| When you need | Use |
|---|---|
| Scaffold generation / copying onboarding layout | `general-purpose` agent |
| Exploring other services' patterns (RLS, auth, settings) | `Explore` agent |
| Writing Gemini-touching code | Skill `gemini-api-dev` or `gemini-live-api-dev` FIRST, then write |
| Pulling NDIS taxonomy from ndis_wiki | `Explore` agent, thoroughness=quick |
| Designing complex multi-file implementation | `Plan` agent for strategy before coding |
| Reviewing written phase code | `gsd-code-review` skill after each phase |
| Debugging stuck state | `gsd-debug` skill |

**Rule:** do NOT ask subagent to write a phase end-to-end. Use subagents for discrete sub-tasks (copy pattern, find taxonomy, review diff). The main thread owns the build.

---

## 7. Open blockers (update as resolved)

| # | Blocker | Impact | Owner |
|---|---|---|---|
| B1 | Other engineer's `GET /case-notes` contract unknown | Stub client is fine for A–D; real client blocks prod | Ask other engineer |
| B2 | Case note register submission: webhook or shared schema? | Blocks Phase F only | Ask other engineer |
| B3 | Case note field schema (exact fields) | Blocks Phase C strong typing | Waiting on figma |
| B4 | Incident form schema | Blocks Phase E strong typing | Ask other engineer |
| B5 | JWT claims structure | Blocks prod auth | Platform team |

---

## 8. Verification between sessions

After resuming, run to confirm state:

```bash
cd sena-ai/services/case_review
pip install -e .
pytest                                          # all green?
uvicorn src.case_review.main:create_app --factory --reload --port 8084
curl localhost:8084/health/ready                # 200?
git log --oneline | grep case_review            # last phase committed?
```

Compare `git log` to phase checklist — first unchecked task = resume point.

---

## 9. Non-negotiables (NDIS + platform rules)

- Multi-tenant `tenant_id` on every row + RLS policy enforced (legal mandate)
- Human-in-the-loop: NO AI output auto-submits. Staff must acknowledge every flag.
- Audit log entry for every AI flag raised + staff action + submit
- Australian data residency: Gemini region = `australia-southeast1` (check env)
- Restrictive practice taxonomy: use NDIS Code of Conduct canonical categories, not invented ones

---

## 10. Change log

| Date | Change |
|---|---|
| 2026-04-23 | Initial plan authored |
