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
START → triage_step (Flash, thinking_budget=0)
          ├─ flagged=False  → END   (≈70% of notes; no further LLM cost)
          └─ flagged=True   → rag_step  (pgvector HNSW cosine, top-K)
                            → evaluator_step  (Pro, structured verdict)
                            → cross_check_step  (SQL only, no LLM)
                            → END
→ CaseNoteRun audit row written for every run regardless of outcome
```

| File | Role |
|------|------|
| `main.py` | FastAPI app (`app = create_app()`) + factory; `create_tables()` runs on startup (dev mode, no Alembic) |
| `config.py` | Pydantic settings, `SENA_AI_` env prefix, `.env` loaded by absolute path |
| `db/session.py` | Async SQLAlchemy engine + `get_db` dep; creates pgvector ext + HNSW index |
| `models/db.py` | ORM: `NDISPolicyChunk` (HALFVEC 3072), `BehaviourSupportPlan`, `CaseNoteRun` |
| `models/schemas.py` | Pydantic IO + enums: `PolicyViolationRisk`, `AuthorisationStatus` |
| `pipeline/triage.py` | Gemini Flash YES/NO gate; no `response_schema` (avoids verbose thinking) |
| `pipeline/rag.py` | Embeds `triage.action_summary` (not full transcript), top-K cosine search |
| `pipeline/evaluator.py` | Gemini Pro grounded verdict; `response_schema` enforced; `max_output_tokens=4096` |
| `pipeline/cross_check.py` | Pure SQL BSP lookup, case-insensitive match on `practice_type` |
| `pipeline/graph.py` | LangGraph wiring; node names use `_step` suffix to avoid TypedDict-key clash |
| `api/routes.py` | All routes: `/evaluate`, `/bsp` CRUD, `/health` — see **API Routes** below |
| `ingestion/chunker.py` | PyMuPDF text extract + langchain text splitter |
| `ingestion/embedder.py` | Gemini embed (3072-dim) + upsert via `ON CONFLICT DO UPDATE` |
| `scripts/ingest_docs.py` | CLI: `--sample` or `--pdf <path> --category <c> --source <s>` |
| `scripts/test_*.py` | Standalone smoke runners (not pytest); per-step verification |
| `scripts/test_sarah_note.py` | Realistic end-to-end fixture — complex multi-practice shift note (physical + chemical + seclusion); good regression canary |

### API Routes

All routes under prefix `/v1/restrictive-practices`:

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/evaluate` | Run a case note through the full pipeline. Sets privacy response headers (see below). |
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
| `NO_INCIDENT` | `evaluator.incident_detected=False` | False |
| `AUTHORISED_USE` | active BSP found for `(client_id, practice_type)` | False |
| `UNAUTHORISED` | no active BSP found | **True** |

Webhook (`pipeline/webhook.py`) fires only when `alert_required=True` — not on every run.

BSP match is case-insensitive on `practice_type`; `valid_from/until = NULL` means unbounded.

### Provider toggle

`google-genai` SDK supports both AI Studio and Vertex AI. Switch is automatic:
- `SENA_AI_GCP_PROJECT` empty → AI Studio (uses `SENA_AI_GEMINI_API_KEY`)
- `SENA_AI_GCP_PROJECT` set → Vertex AI (uses ADC, region from `SENA_AI_GCP_LOCATION`)

Embedder client is module-level — no per-call construction.

## Environment Variables (key overrides)

All use `SENA_AI_` prefix in `.env` at the module root.

| Var | Default | Notes |
|-----|---------|-------|
| `SENA_AI_GEMINI_API_KEY` | — | AI Studio key; leave blank if using Vertex AI |
| `SENA_AI_GCP_PROJECT` | `""` | Set to enable Vertex AI mode |
| `SENA_AI_GCP_LOCATION` | `australia-southeast1` | Vertex AI region — AU data residency (APP 8) |
| `SENA_AI_RP_DATABASE_URL` | `postgresql+asyncpg://...@localhost:5433/sena_ai` | |
| `SENA_AI_EMBEDDING_MODEL` | `text-embedding-004` | AI Studio: `gemini-embedding-2`; Vertex AI: `gemini-embedding-001` — must match at ingest AND query time |
| `SENA_AI_TRIAGE_MODEL` | `gemini-3-flash-preview` | Fast YES/NO gate, `thinking_budget=0` |
| `SENA_AI_EVALUATOR_MODEL` | `gemini-3.1-pro-preview` | Complex reasoning for compliance verdicts |

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

- `HALFVEC(3072)` (uppercase, DDL type) in `mapped_column()` — `HalfVector` is the runtime value class, wrong here
- `json.loads(response.text)` — `response.parsed` returns `None` on gemini-2.5-x and gemini-3.x; never use `response.parsed`
- `temperature=0.0` on every LLM call — compliance decisions must be deterministic
- LangGraph node names must NOT collide with `TypedDict` state keys (`_step` suffix convention)
- Triage uses `thinking_budget=0` and no `response_schema` — both cut latency on the hot path
- Evaluator needs `max_output_tokens=4096` minimum — lower truncates the JSON verdict
- Models: `gemini-3-flash-preview` (triage), `gemini-3.1-pro-preview` (evaluator); 2.5/2.0/1.5 deprecated
- Embedding model is whatever `config.embedding_model` says — treat `config.py` as source of truth, not SESSION_START.md
- **`google-genai >= 1.74.0` required** — older SDK lacks `ThinkingConfig.thinking_budget`; triage will fail at runtime on anything older
- **Embedding model name differs by provider**: AI Studio uses `gemini-embedding-2`; Vertex AI uses `gemini-embedding-001`. Using the wrong name returns a 404. Chunks must be re-ingested if the model changes — query-time and ingest-time models must match.
- **If evaluator 404s on Vertex AI** — model availability varies by region/project. Flash fallback: `SENA_AI_EVALUATOR_MODEL=gemini-3-flash-preview`. AI Studio always has both models available.
- `SettingsConfigDict(extra="ignore")` is intentional — the shared `.env` contains keys for other SENA modules; without it, startup raises a validation error
- All Gemini SDK calls are synchronous and offloaded via `asyncio.to_thread` — do not call them directly in async functions
- **Swagger UI 422 errors**: usually caused by literal newlines in JSON string values — press Enter inside a string creates invalid JSON. Use `\n` escape or keep transcript on one line. See issues-solved 0010.
- **Before debugging**: grep `.claude/issues-solved/INDEX.md` — 11 issues documented, saves hours of re-debugging
