# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Session Start Protocol

1. `.claude/SESSION_START.md` — last session summary, gotchas, next steps
2. `.claude/tasks/TASKS.md` — live task list
3. `.claude/issues-solved/INDEX.md` — grep before debugging anything

## Issues-Solved Knowledge Base (MANDATORY — CHECK BEFORE DEBUGGING)

Path: `.claude/issues-solved/`

**Rule:** before debugging ANY issue, grep `.claude/issues-solved/INDEX.md` for symptom keywords.
- If match → read linked detail file → apply fix. Do NOT re-derive.
- If no match → solve, then append a new entry via `TEMPLATE.md`.

**When to add an entry:** issue took >2 debugging iterations OR >5 min OR required external research. One file per issue, numbered `NNNN-kebab-symptom.md`, row added to `INDEX.md` (newest first).

**Goal:** zero re-solved bugs, zero token-waste on problems already cracked.

## Module Overview

AI pipeline detecting NDIS regulated restrictive practices from support-worker case notes. Lives inside the broader SENA monorepo — see `C:\Users\Admin\Documents\SENA\CLAUDE.md` for platform context. Entry point: `POST /v1/restrictive-practices/evaluate`.

## Architecture

Five-step LangGraph pipeline with cost-saving early exit:

```
START → triage_step (Haiku, Bedrock converse, maxTokens=512)
          ├─ flagged=False  → summary_step  (Haiku, shift summary)
          └─ flagged=True   → rag_step  (pgvector HNSW cosine, top-K)
                            → evaluator_step  (Sonnet, structured verdict)
                            → cross_check_step  (SQL only, no LLM)
                            → summary_step  (Haiku, shift summary)
→ summary_step → incident_draft_step  (Sonnet, when incident_occurred=True OR UNAUTHORISED)
               → END  (when no incident)
→ CaseNoteRun audit row written for every run regardless of outcome
```

| File | Role |
|------|------|
| `main.py` | FastAPI app (`app = create_app()`) + factory; `create_tables()` runs on startup (dev mode, no Alembic) |
| `config.py` | Pydantic settings, `SENA_AI_` env prefix, `.env` loaded by absolute path |
| `db/session.py` | Async SQLAlchemy engine + `get_db` dep; creates pgvector ext + HNSW index |
| `models/db.py` | ORM: `NDISPolicyChunk` (HALFVEC 1024), `BehaviourSupportPlan`, `CaseNoteRun` |
| `models/schemas.py` | Pydantic IO + enums: `PolicyViolationRisk`, `AuthorisationStatus` |
| `pipeline/triage.py` | Claude Haiku YES/NO gate via Bedrock `converse`; JSON extracted from free text |
| `pipeline/rag.py` | Embeds `triage.action_summary` (not full transcript), top-K cosine search |
| `pipeline/evaluator.py` | Claude Sonnet grounded verdict via Bedrock `converse`; JSON extracted from free text; `maxTokens=8192` |
| `pipeline/cross_check.py` | Pure SQL BSP lookup, case-insensitive match on `practice_type` |
| `pipeline/summary.py` | Claude Haiku shift summariser; always runs; produces `SummaryOutput` (progress/risks/patterns/highlights + ai_confidence) |
| `pipeline/incident_draft.py` | Claude Sonnet NDIS incident report drafter; conditional on `incident_occurred=True` OR `UNAUTHORISED` verdict; produces `IncidentDraftOutput` |
| `pipeline/drafter.py` | Stateless AI extraction: voice transcript → structured 6-section case note form; used by `POST /draft` |
| `pipeline/graph.py` | LangGraph wiring; node names use `_step` suffix to avoid TypedDict-key clash |
| `api/routes.py` | All routes: `/evaluate`, `/draft`, `/bsp` CRUD, `/health` — see **API Routes** below |
| `ingestion/chunker.py` | PyMuPDF text extract + langchain text splitter |
| `ingestion/embedder.py` | Cohere Embed English v3 (1024-dim) via Bedrock `invoke_model`; upsert via `ON CONFLICT DO UPDATE` |
| `scripts/ingest_docs.py` | CLI: `--sample` or `--pdf <path> --category <c> --source <s>` |
| `scripts/test_*.py` | Standalone smoke runners (not pytest); per-step verification |
| `scripts/test_sarah_note.py` | Realistic end-to-end fixture — complex multi-practice shift note (physical + chemical + seclusion); good regression canary |
| `scripts/test_form_api.py` | 8-scenario comprehensive test covering all 4 verdict outcomes and all 5 practice types using structured form fields (not transcript); real-data scenarios sourced from NDIS Commission guides |
| `scripts/test_draft_endpoint.py` | 10-scenario smoke test for `/draft` — calls `run_drafter()` directly; covers routine shift, restraint, injury, sparse transcript (gap detection), and rich all-sections transcript |

### API Routes

All routes under prefix `/v1/restrictive-practices`:

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/evaluate` | Run a case note through the full pipeline. Requires basic auth if env vars set. Sets privacy response headers (see below). |
| `POST` | `/draft` | Extract a voice transcript into a pre-filled structured case note. Stateless — no DB. No auth required. |
| `POST` | `/bsp` | Register a new Behaviour Support Plan (called by platform backend on practitioner approval). |
| `GET` | `/bsp/{client_id}` | List all BSP records for a client, ordered newest-first. |
| `PATCH` | `/bsp/{bsp_id}/status` | Update BSP status — valid values: `Active`, `Expired`, `Revoked`. |
| `GET` | `/health` | Health check. |

**Privacy response headers** (set on every `/evaluate` response):
- `X-Privacy-Classification: Sensitive-Health-Information-APP3`
- `X-Data-Retention: No-Retention-Session-Only`

### DB conventions

- Tables prefixed `rp_` for module isolation: `rp_ndis_policy_chunks`, `rp_case_note_runs`. (`behaviour_support_plans` is unprefixed — shared with the wider platform.)
- Lives in the SENA `sena-ai-db` instance, port **5433** (started via `docker-compose up -d` from `restrictive_practices/`).
- HNSW index uses `halfvec_cosine_ops` (matches the `HALFVEC` column type).
- `create_tables()` runs on FastAPI startup — replace with Alembic before production.

### Verdict outcomes and authorisation

| `VerdictOutcome` | Trigger | `alert_required` |
|-----------------|---------|-----------------|
| `CLEAR` | `triage.flagged=False` (early exit) | False |
| `NO_INCIDENT` | `evaluator.incident_detected=False` OR `confidence=LOW` | False |
| `AUTHORISED_USE` | active BSP found for `(client_id, practice_type)` | False |
| `ADMINISTRATIVE_REVIEW` | BSP mentioned in note (`bsp_mentioned_in_note=True`) but no DB record | False |
| `POSSIBLE` | `confidence=MEDIUM` and no active BSP found | False |
| `UNAUTHORISED` | `confidence=HIGH`, incident detected, no active BSP | **True** |

Verdict routing is in `api/routes.py:_build_response()` — reads `evaluator.confidence`, `evaluator.bsp_mentioned_in_note`, and `cross_check.authorisation_status` in priority order.

Webhook (`pipeline/webhook.py`) fires only when `alert_required=True` — not on every run.

BSP match is case-insensitive on `practice_type`; `valid_from/until = NULL` means unbounded.

### Draft endpoint

`POST /draft` accepts a `DraftInput` (transcript + shift metadata) and returns a pre-filled `CaseDraftResponse` (all 6 case note sections + `draft_note` gap-detection field). Uses `evaluator_model` (Gemini Pro). Stateless — no DB reads or writes. The worker reviews and edits the returned fields before calling `/evaluate`.

**`draft_note` field:** if the transcript is sparse, the model populates this with a 1–3 sentence note describing what's missing. If the transcript is comprehensive, it returns `null`.

### AI Summary

Every `/evaluate` call returns a `summary` section in `EvaluateResponse`. It is generated by `pipeline/summary.py` (Claude Haiku, `maxTokens=1024`) from the case note form text.

Fields: `ai_confidence` (0.0–1.0), `confidence_label` (High/Medium/Low), `progress_identified`, `potential_risks`, `patterns_detected`, `flagged_highlights`.

### Incident Report Draft

When `incident_occurred=True` OR the pipeline verdict is `UNAUTHORISED`, an `incident_report` section is included in `EvaluateResponse`. It is generated by `pipeline/incident_draft.py` (Claude Sonnet, `maxTokens=4096`).

Trigger condition: `note.incident_occurred == True` OR (`evaluator.confidence != LOW` AND `cross_check.authorisation_status == UNAUTHORISED`).

Fields mirror Case Note 6.png + NDIS Commission reportable-incident categories: `incident_type`, `date_of_incident`, `immediate_actions_taken`, `restrictive_practice_used`, `contributing_factors`, `follow_up_actions`, `compliance_checks`, `reportable`, `notification_timeframe` (24 hours / 5 business days / null).

### CaseNoteInput — Structured Form Model

`CaseNoteInput` (`models/schemas.py`) was expanded to mirror the real case note form used by support workers. It is no longer a flat transcript wrapper.

**Structure:**
- `case_note_id` / `client_id` / `worker_id` — required identifiers
- `transcript: str | None` — optional voice transcript; takes priority in `to_text()` if present
- **Section 1** — Shift summary (`describe`)
- **Section 2** — Activities (`assisted`, `practised_skill`, `participants_level_of_independence`, `observations`)
- **Section 3** — Wellbeing & behaviour (`mood`, `behavioural_events`, `any_concerns`)
- **Section 4** — Outcomes (`what_went_well`, `what_needs_further_support`, `participant_comments`)
- **Section 5** — Safety (`medication_reminders_given`, `safety_hazards_observed`, `any_injuries`, `injury_description`, `uploaded_documents`)
- **Section 6** — Notes (`carer_feedback`, `incident_occurred`)

**Key invariants:**
- `_require_content` validator enforces that at least one of `transcript`, `describe`, `behavioural_events`, `observations`, `carer_feedback`, `assisted`, or `mood` is non-null — an all-empty payload returns HTTP 422.
- `to_text()` is called by every LLM step (triage, RAG, evaluator). It returns `transcript` directly if set; otherwise builds a structured narrative from all form sections. Never pass raw form fields to Gemini — always call `note.to_text()`.
- `behavioural_events` is the most important field for detection — triage, RAG query, and evaluator all weight it highest via the narrative structure.

## Environment Variables (key overrides)

All use `SENA_AI_` prefix in `.env` at the module root.

| Var | Default | Notes |
|-----|---------|-------|
| `SENA_AI_AWS_REGION` | `ap-southeast-2` | Bedrock region — Sydney for AU data residency (APP 8) |
| `AWS_ACCESS_KEY_ID` | `""` | Read without `SENA_AI_` prefix; leave blank to use IAM role / `~/.aws/credentials` |
| `AWS_SECRET_ACCESS_KEY` | `""` | Same — standard boto3 env var |
| `SENA_AI_RP_DATABASE_URL` | `postgresql+asyncpg://...@localhost:5433/sena_ai` | |
| `SENA_AI_EMBEDDING_MODEL` | `cohere.embed-english-v3` | 1024-dim; must match at ingest AND query time |
| `SENA_AI_TRIAGE_MODEL` | `anthropic.claude-haiku-4-5-20251001-v1:0` | Fast YES/NO gate via Bedrock `converse` |
| `SENA_AI_EVALUATOR_MODEL` | `anthropic.claude-sonnet-4-6-v1:0` | Compliance verdicts + case note drafting; also used by `/draft` |
| `SENA_AI_BASIC_AUTH_USER` | `""` | Optional — if set (with PASSWORD), `/evaluate` requires HTTP Basic auth |
| `SENA_AI_BASIC_AUTH_PASSWORD` | `""` | Optional — must be set together with USER; passthrough if either is empty |

## Run Commands

```bash
# Activate env first
conda activate sena_env

# Full demo setup (one command)
make demo-setup      # docker-compose up + ingest real PDFs + seed BSPs

# Or step by step:
docker-compose up -d                        # Postgres + pgvector on port 5433
python scripts/ingest_ndis_policies.py      # ingest 5 official NDIS PDFs (place in pdfs/ if download blocked)
python scripts/seed_demo.py                 # seed demo BSPs

# API server
uvicorn main:app --reload --port 8084
# → Swagger UI at http://localhost:8084/docs

# Ingest sample NDIS policies (no PDF required — for quick testing)
python scripts/ingest_docs.py --sample

# Ingest a real PDF manually
python scripts/ingest_docs.py --pdf path/to/guide.pdf \
    --category "Chemical Restraint" \
    --source "NDIS Regulated Restrictive Practices Guide 2023" \
    --risk "High Risk" --document-type "Regulatory"

# Smoke-test individual pipeline steps (standalone — not pytest)
make test            # runs triage → rag → evaluator → cross_check → pipeline in sequence
make test-sarah      # realistic complex fixture (physical + chemical + seclusion)
python scripts/test_form_api.py  # 8 real-data scenarios (all 4 outcomes, all 5 practice types; uses structured form fields)
python scripts/test_draft_endpoint.py  # 10 drafter scenarios; calls run_drafter() directly, no server needed

# Or individual steps:
python scripts/test_triage.py
python scripts/test_rag.py
python scripts/test_evaluator.py
python scripts/test_cross_check.py
python scripts/test_pipeline.py

# Code quality
make lint            # ruff check .
make format          # ruff format .
make typecheck       # mypy . --ignore-missing-imports

# DB inspection
make audit           # last 5 pipeline run rows
make audit-chunks    # chunk counts by document type

# Direct psql (container name: sena-ai-db)
docker exec -it sena-ai-db psql -U sena_ai -d sena_ai
```

## Critical Rules

- `HALFVEC(1024)` (uppercase, DDL type) in `mapped_column()` — `HalfVector` is the runtime value class, wrong here
- `json.loads(response["output"]["message"]["content"][0]["text"])` — Bedrock `converse` response path; never use `response.text` (that was Gemini)
- `temperature=0.0` on every LLM call — compliance decisions must be deterministic
- LangGraph node names must NOT collide with `TypedDict` state keys (`_step` suffix convention)
- Triage uses `maxTokens=512` via Bedrock — no thinking_budget concept; Claude Haiku is fast without it
- Evaluator needs `maxTokens=8192` — lower truncates the JSON verdict; drafter needs 4096
- Models: `anthropic.claude-haiku-4-5-20251001-v1:0` (triage), `anthropic.claude-sonnet-4-6-v1:0` (evaluator + drafter)
- Embedding: `cohere.embed-english-v3` at **1024 dims** via Bedrock `invoke_model` — must match at ingest AND query time; re-ingest all chunks if model changes
- **Cohere `input_type` matters**: `"search_document"` for ingest (`embed_text`), `"search_query"` for RAG (`embed_query`) — mixing types degrades retrieval quality
- **AU data residency**: Bedrock region `ap-southeast-2` (Sydney) for APP 8. Verify Claude 4.x model availability there before prod; fallback `us-east-1` breaks residency
- `SettingsConfigDict(extra="ignore")` is intentional — the shared `.env` contains keys for other SENA modules; without it, startup raises a validation error
- All Bedrock SDK calls are synchronous and offloaded via `asyncio.to_thread` — do not call them directly in async functions
- **Swagger UI 422 errors**: usually caused by literal newlines in JSON string values — press Enter inside a string creates invalid JSON. Use `\n` escape or keep transcript on one line. See issues-solved 0010.
- **Before debugging**: grep `.claude/issues-solved/INDEX.md` — 11 issues documented, saves hours of re-debugging
- `transcript` is optional in `CaseNoteInput` — but at least one of `transcript`, `describe`, `behavioural_events`, `observations`, `carer_feedback`, `assisted`, or `mood` must be non-null (enforced by `_require_content` validator)
- Never pass form fields directly to LLM — always call `note.to_text()` which handles both transcript-first and form-narrative rendering
- `behavioural_events` is the highest-signal field for detection — when constructing test notes, put restrictive practice evidence there
