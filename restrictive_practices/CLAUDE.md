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

**Parallelism inside `run_pipeline()` (see `pipeline/graph.py`):**
- **Opt A:** `run_summary` fires as `asyncio.create_task()` at request start — runs in parallel with the full triage → rag → eval → cross_check graph traversal
- **Opt B:** when an incident is needed, `run_incident_draft` joins via `asyncio.gather()` with the already-running summary task
- **Opt C:** `fire_webhook` detaches via `asyncio.create_task()` on alert — caller gets response without waiting

| File | Role |
|------|------|
| `main.py` | FastAPI app (`app = create_app()`) + factory; `create_tables()` runs on startup (dev mode, no Alembic); serves `GET /demo` → `demo_ui.html` (auth-protected) |
| `config.py` | Pydantic settings, `SENA_AI_` env prefix, `.env` loaded by absolute path |
| `db/session.py` | Async SQLAlchemy engine + `get_db` dep; creates pgvector ext + HNSW index |
| `models/db.py` | ORM: `NDISPolicyChunk` (HALFVEC 1024), `BehaviourSupportPlan`, `CaseNoteRun` |
| `models/schemas.py` | Pydantic IO + enums: `PolicyViolationRisk`, `AuthorisationStatus` |
| `pipeline/triage.py` | Claude Haiku YES/NO gate via Bedrock `converse`; includes `FEW_SHOT_TRIAGE` inline; JSON extracted from free text |
| `pipeline/rag.py` | Embeds `triage.action_summary`, top-K cosine search; also `retrieve_style_chunks(query, document_type, db, top_k)` for style-standard RAG |
| `pipeline/evaluator.py` | Claude Sonnet grounded verdict via Bedrock `converse`; `maxTokens=8192`; includes `FEW_SHOT_EVAL_REASONING` + `STYLE_GUIDE` |
| `pipeline/cross_check.py` | Pure SQL BSP lookup, case-insensitive match on `practice_type` |
| `pipeline/summary.py` | Claude Haiku shift summariser; always runs; `SummaryOutput` (progress/risks/patterns/highlights + ai_confidence + quality fields); `FEW_SHOT_SUMMARY` + heuristic quality scorer |
| `pipeline/incident_draft.py` | Claude Sonnet NDIS incident report drafter; conditional on `incident_occurred=True` OR `UNAUTHORISED`; `IncidentDraftOutput` includes Phase 1 fields (severity, incident_categories, ongoing_risk_*) |
| `pipeline/drafter.py` | Stateless AI extraction: transcript -> 6-section case note; `FEW_SHOT_DRAFTER` + field-description guidance + quality scoring on return |
| `pipeline/style_examples.py` | Ultra-compact few-shot constants (`FEW_SHOT_TRIAGE`, `FEW_SHOT_SUMMARY`, `FEW_SHOT_DRAFTER`, `FEW_SHOT_INCIDENT`, `FEW_SHOT_EVAL_REASONING`, `STYLE_GUIDE`) — **single source of truth** for all prompt style. Update here when the client revises the gold standard. |
| `pipeline/quality_score.py` | Heuristic quality scorer: `score_note(note) -> (float, str, list[str])`; completeness + richness + tone vs Premium baselines; zero LLM cost |
| `pipeline/graph.py` | LangGraph wiring + `run_pipeline()` entry point; Opt A/B/C parallelism; node names use `_step` suffix to avoid TypedDict-key clash |
| `pipeline/transcription.py` | Amazon Transcribe batch STT: `run_transcription(audio_bytes, media_format, *, job_name) -> str`; also `resolve_media_format(content_type, filename) -> str`; S3 temp key deleted in finally |
| `api/routes.py` | All routes: `/evaluate`, `/draft`, `/bsp` CRUD, `/health` — see **API Routes** below |
| `ingestion/chunker.py` | PyMuPDF text extract + langchain text splitter |
| `ingestion/embedder.py` | Cohere Embed English v3 (1024-dim) via Bedrock `invoke_model`; upsert via `ON CONFLICT DO UPDATE` |
| `scripts/ingest_docs.py` | CLI: `--sample` or `--pdf <path> --category <c> --source <s>` |
| `scripts/ingest_style_standards.py` | Ingests client gold-standard doc into pgvector (15 chunks: 4 casenotes + 6 field sections + 5 incident reports, 3 new document_type values) |
| `scripts/test_quality_score.py` | Smoke test for quality scorer — 3 fixtures (Premium/Average/Poor) |
| `scripts/test_sarah_note.py` | Realistic end-to-end fixture — complex multi-practice shift note (physical + chemical + seclusion); good regression canary |
| `scripts/test_form_api.py` | 8-scenario comprehensive test covering all 4 verdict outcomes and all 5 practice types using structured form fields |
| `scripts/test_draft_endpoint.py` | 10-scenario smoke test for `/draft` — calls `run_drafter()` directly |
| `scripts/test_incident_draft.py` | Smoke test for `pipeline/incident_draft.py` — verifies incident report fields |
| `scripts/test_summary.py` | Smoke test for `pipeline/summary.py` — verifies summary block fields |
| `scripts/test_perf_baseline.py` | Pipeline performance baseline — records processing_time_ms per step |
| `scripts/_debug_pipeline.py` | Interactive debug harness — runs pipeline with verbose step logging; not for CI |

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
| `GET` | `/demo` | Serves `demo_ui.html` browser UI. Auth-protected (same Basic auth as `/evaluate`). |
| `POST` | `/draft/audio` | Transcribe audio → extract into pre-filled case note. `multipart/form-data`: `audio` file + form fields (`worker_id`, `client_id`, `shift_date`, `shift_time`, `worker_position`, `case_note_id`). Requires `SENA_AI_TRANSCRIPTION_BUCKET`. Returns same shape as `/draft`. |

**Privacy response headers** (set on every `/evaluate` response):
- `X-Privacy-Classification: Sensitive-Health-Information-APP3`
- `X-Data-Retention: No-Retention-Session-Only`

### DB conventions

- Tables prefixed `rp_` for module isolation: `rp_ndis_policy_chunks`, `rp_case_note_runs`. (`behaviour_support_plans` is unprefixed — shared with the wider platform.)
- Lives in the SENA `sena-ai-db` instance, port **5433** (started via `docker-compose -f docker-compose_db.yml up -d` from `restrictive_practices/`).
- HNSW index uses `halfvec_cosine_ops` (matches the `HALFVEC` column type).
- `create_tables()` runs on FastAPI startup — replace with Alembic before production.
- Production compose file: `docker-compose.prod.yml` (adds environment-specific overrides).

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

`POST /draft` accepts a `DraftInput` (transcript + shift metadata) and returns a pre-filled `CaseDraftResponse` (all 6 case note sections + `draft_note` gap-detection field). Uses `evaluator_model` (Claude Sonnet, Bedrock). Stateless — no DB reads or writes. The worker reviews and edits the returned fields before calling `/evaluate`.

**`draft_note` field:** if the transcript is sparse, the model populates this with a 1–3 sentence note describing what's missing. If the transcript is comprehensive, it returns `null`.

### AI Summary

Every `/evaluate` call returns a `summary` section in `EvaluateResponse`. Generated by `pipeline/summary.py` (Claude Haiku, `maxTokens=1024`).

Fields: `ai_confidence` (0.0–1.0), `confidence_label`, `progress_identified`, `potential_risks`, `patterns_detected`, `flagged_highlights`, **`note_quality_score`** (0.0–1.0), **`note_quality_label`** (Premium/Average/Poor), **`quality_gaps`** (list of actionable suggestions).

Quality scoring is heuristic — zero LLM cost. Runs via `pipeline/quality_score.score_note()`. Also returned by `/draft` in `CaseDraftResponse`.

### Incident Report Draft

When `incident_occurred=True` OR the pipeline verdict is `UNAUTHORISED`, an `incident_report` section is included in `EvaluateResponse`. Generated by `pipeline/incident_draft.py` (Claude Sonnet, `maxTokens=4096`).

Trigger: `note.incident_occurred == True` OR (`evaluator.confidence != LOW` AND `cross_check.authorisation_status == UNAUTHORISED`).

Fields: all existing fields + Phase 1 additions: **`severity`** (Low/Medium/High/Critical), **`incident_categories`** (multi-select list), **`ongoing_risk_present`**, **`participant_currently_safe`**, **`staff_currently_safe`**, **`emergency_services_required`**.

Notification timeframes: 24h (Category 1 — death/serious injury/abuse/assault/sexual misconduct), 5 business days (Category 2 — unauthorised restrictive practice).

### Gold-Standard Prompts

All 5 LLM prompts now include `STYLE_GUIDE` (third-person clinical register) and an ultra-compact few-shot snippet from `pipeline/style_examples.py`. Single source of truth — update `style_examples.py` when the client revises the gold standard.

The gold-standard client doc is ingested into pgvector as 15 chunks (3 document_type values). Run `python scripts/ingest_style_standards.py` once after DB setup. `retrieve_style_chunks()` in `pipeline/rag.py` fetches these by document_type for RAG-grounded prompting in drafter, summary, and incident_draft.

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
- `to_text()` is called by every LLM step (triage, RAG, evaluator). It returns `transcript` directly if set; otherwise builds a structured narrative from all form sections. Never pass raw form fields to the LLM — always call `note.to_text()`.
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
| `SENA_AI_BASIC_AUTH_USER` | `""` | Optional — if set (with PASSWORD), `/evaluate` and `/demo` require HTTP Basic auth |
| `SENA_AI_BASIC_AUTH_PASSWORD` | `""` | Optional — must be set together with USER; passthrough if either is empty |
| `SENA_AI_DEMO_HOST` | `""` | Optional — sets CORS `allow_origins`; defaults to `["*"]` when empty |
| `SENA_AI_TRANSCRIPTION_BUCKET` | `""` | S3 bucket for temp audio files; **required** for `POST /draft/audio`; returns 503 if blank |
| `SENA_AI_TRANSCRIPTION_LANGUAGE` | `"en-AU"` | Amazon Transcribe language code |
| `SENA_AI_TRANSCRIPTION_VOCAB_NAME` | `""` | Custom Transcribe vocabulary name — create once via `python scripts/setup_transcribe_vocab.py` |

## Run Commands

```bash
# Activate env first
conda activate sena_env

# ── Infrastructure ────────────────────────────────────────────────────────────
make up              # docker-compose -f docker-compose_db.yml up -d (Postgres + pgvector, port 5433)
make down            # stop DB

# ── Full demo setup ───────────────────────────────────────────────────────────
make demo-setup      # up + ingest-ndis + seed-demo (Makefile fixed to use docker-compose_db.yml)
python scripts/ingest_style_standards.py         # ingest gold-standard doc (15 chunks) — once only
python scripts/setup_transcribe_vocab.py         # create NDIS Transcribe vocabulary — once; set SENA_AI_TRANSCRIPTION_VOCAB_NAME after

# ── API server ─────────────────────────────────────────────────────────────────
make server          # uvicorn main:app --reload --port 8084
# → Swagger UI at http://localhost:8084/docs
# → Demo UI at http://localhost:8084/demo (Basic auth required if BASIC_AUTH_USER set)

# ── Data ingestion ─────────────────────────────────────────────────────────────
make ingest          # ingest sample NDIS policies (no PDF required — quick testing)
make ingest-ndis     # download + ingest all official NDIS PDFs
make seed-demo       # seed demo BSPs into DB

# Ingest a real PDF manually:
make ingest-pdf PDF=path/to/guide.pdf CATEGORY="Chemical Restraint" SOURCE="NDIS Guide 2023" RISK="High Risk"
# or directly:
python scripts/ingest_docs.py --pdf path/to/guide.pdf \
    --category "Chemical Restraint" \
    --source "NDIS Regulated Restrictive Practices Guide 2023" \
    --risk "High Risk" --document-type "Regulatory"

# ── Smoke tests (standalone — not pytest) ─────────────────────────────────────
make test            # triage → rag → evaluator → cross_check → pipeline
make test-sarah      # realistic complex fixture (physical + chemical + seclusion)
python scripts/test_form_api.py          # 8 real-data scenarios (all 4 outcomes, all 5 practice types)
python scripts/test_draft_endpoint.py   # 10 drafter scenarios; calls run_drafter() directly
python scripts/test_incident_draft.py   # incident report drafter smoke test
python scripts/test_summary.py          # summary step smoke test
python scripts/test_perf_baseline.py    # processing_time_ms baseline per step

# Individual steps:
python scripts/test_triage.py
python scripts/test_rag.py
python scripts/test_evaluator.py
python scripts/test_cross_check.py
python scripts/test_pipeline.py

# ── Code quality ───────────────────────────────────────────────────────────────
make lint            # ruff check .
make format          # ruff format .
make typecheck       # mypy . --ignore-missing-imports

# ── DB inspection ──────────────────────────────────────────────────────────────
make audit           # last 5 pipeline run rows
make audit-chunks    # chunk counts by document type

# Direct psql (container name: sena-ai-db)
docker exec -it sena-ai-db psql -U sena_ai -d sena_ai
```

**Pytest (voice assistant):** `tests/test_voice/` contains 38 pytest tests for the voice package. Run via `python -m pytest tests/test_voice/ -q`. Requires `fakeredis` — install with `pip install fakeredis pytest pytest-asyncio`.

## Critical Rules

- `HALFVEC(1024)` (uppercase, DDL type) in `mapped_column()` — `HalfVector` is the runtime value class, wrong here
- `json.loads(response["output"]["message"]["content"][0]["text"])` — Bedrock `converse` response path; never use `response.text` (that was Gemini)
- Bedrock models often wrap JSON in markdown fences — use `_extract_json()` with `json.JSONDecoder().raw_decode(text, text.find("{"))` — handles fences + trailing text; see issues-solved 0016
- Bedrock models may return nested JSON — add explicit flat-key instruction to prompt: "Respond with a single flat JSON object — no nested objects"; see issues-solved 0017
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
- boto3 credentials: pydantic-settings does NOT inject into `os.environ`; always pass creds explicitly: `boto3.client(..., aws_access_key_id=settings.aws_access_key_id, ...)` — see issues-solved 0015
- **Swagger UI 422 errors**: usually caused by literal newlines in JSON string values — press Enter inside a string creates invalid JSON. Use `\n` escape or keep transcript on one line. See issues-solved 0010.
- **Before debugging**: grep `.claude/issues-solved/INDEX.md` — issues documented there, saves hours of re-debugging
- `transcript` is optional in `CaseNoteInput` — but at least one of `transcript`, `describe`, `behavioural_events`, `observations`, `carer_feedback`, `assisted`, or `mood` must be non-null (enforced by `_require_content` validator)
- Never pass form fields directly to LLM — always call `note.to_text()` which handles both transcript-first and form-narrative rendering
- `behavioural_events` is the highest-signal field for detection — when constructing test notes, put restrictive practice evidence there
- `bsp_mentioned_in_note` must NOT gate `alert_required` — model sets it True even for negative mentions; rely on cross_check SQL only. See issues-solved 0018.

## Voice Assistant (voice/)

Real-time case-note form assistant using Gemini Live. Worker speaks; assistant fills missing fields in real time. Does NOT call `/evaluate` — worker presses Submit manually.

### Architecture

```
POST /v1/restrictive-practices/voice/session  → create session, issue WS token, seed initial_values into Redis
WSS  /v1/restrictive-practices/voice/ws/{id}?token=…  → Gemini Live bridge

voice/
  schema.py          build_case_note_schema() — 7 sections, 27 fields
  state.py           CaseNoteVoiceState — Pydantic v2 session state
  state_repo.py      VoiceStateRepo — Redis ops, key prefix sena:rp_voice:
  tools.py           ToolDispatcher — 5 tools: update_field/clear_field/get_session_context/finish_session/escalate_incident
  prompt_builder.py  build_system_prompt() — injects LIVE_STATE_JSON + schema
  gemini_live.py     GeminiLiveSession — audio bridge (copy of onboarding with 3 import rewires)
  prompts/
    case_note_system.md  System prompt for case-note context
  validators/        sequencing.py (no repeatables), field_rules.py (injury_description rule)
```

### Key rules

- All Redis keys use `sena:rp_voice:` prefix — never `sena:onboarding:` (enforced in tests/test_voice/test_state_repo.py)
- `finish_session` validates all required fields filled, emits `session_complete` with `to_case_note_payload()`, sets `state.completed=True` — NEVER calls `/evaluate`
- `voice_coverage=[]` means all fields are voice-eligible (no coverage gate)
- `safety.injury_description` has `visible_if={"any_injuries": True}` — only appears in schema/prompt when `any_injuries=True`
- Send `screen_state_v2` from Flutter when `any_injuries` toggles so the server re-evaluates `visible_if`

### Env vars (voice-specific)

| Var | Default | Notes |
|-----|---------|-------|
| `SENA_AI_GEMINI_API_KEY` | `""` | Required for voice |
| `SENA_AI_GEMINI_LIVE_MODEL_ID` | `gemini-3.1-flash-live-preview` | |
| `SENA_AI_REDIS_URL` | `redis://localhost:6379/0` | Start via `docker-compose -f docker-compose_db.yml up -d` |
| `SENA_AI_VOICE_SESSION_MAX_SEC` | `3600` | Session TTL |
| `SENA_AI_VOICE_SILENCE_TIMEOUT_SEC` | `8` | Silence watchdog; 0 = disabled |

### Tests

```bash
python -m pytest tests/test_voice/ -q   # 38 tests, fakeredis, no live services needed
```

### Flutter contract

See `FLUTTER_VOICE_INTEGRATION.md` for the full WS event contract, `screen_state_v2` shape, and field section reference.
