# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Session Start Protocol

1. `.claude/SESSION_START.md` — last session summary, gotchas, next steps
2. `.claude/tasks/TASKS.md` — live task list

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
| `main.py` | FastAPI factory; `create_tables()` runs on startup (dev mode, no Alembic) |
| `config.py` | Pydantic settings, `SENA_AI_` env prefix, `.env` loaded by absolute path |
| `db/session.py` | Async SQLAlchemy engine + `get_db` dep; creates pgvector ext + HNSW index |
| `models/db.py` | ORM: `NDISPolicyChunk` (HALFVEC 3072), `BehaviourSupportPlan`, `CaseNoteRun` |
| `models/schemas.py` | Pydantic IO + enums: `PolicyViolationRisk`, `AuthorisationStatus` |
| `pipeline/triage.py` | Gemini Flash YES/NO gate; no `response_schema` (avoids verbose thinking) |
| `pipeline/rag.py` | Embeds `triage.action_summary` (not full transcript), top-K cosine search |
| `pipeline/evaluator.py` | Gemini Pro grounded verdict; `response_schema` enforced; `max_output_tokens=4096` |
| `pipeline/cross_check.py` | Pure SQL BSP lookup, case-insensitive match on `practice_type` |
| `pipeline/graph.py` | LangGraph wiring; node names use `_step` suffix to avoid TypedDict-key clash |
| `api/routes.py` | `POST /v1/restrictive-practices/evaluate`, `GET .../health` |
| `ingestion/chunker.py` | PyMuPDF text extract + langchain text splitter |
| `ingestion/embedder.py` | Gemini embed (3072-dim) + upsert via `ON CONFLICT DO UPDATE` |
| `scripts/ingest_docs.py` | CLI: `--sample` or `--pdf <path> --category <c> --source <s>` |
| `scripts/test_*.py` | Standalone smoke runners (not pytest); per-step verification |

### DB conventions

- Tables prefixed `rp_` for module isolation: `rp_ndis_policy_chunks`, `rp_case_note_runs`. (`behaviour_support_plans` is unprefixed — shared with the wider platform.)
- Lives in the SENA `sena-ai-db` instance, port **5433** (started via `docker-compose up -d` from `sena-ai/`).
- HNSW index uses `halfvec_cosine_ops` (matches the `HALFVEC` column type).
- `create_tables()` runs on FastAPI startup — replace with Alembic before production.

### Authorisation outcomes

| Status | Trigger | `alert_required` |
|--------|---------|------------------|
| `NO_INCIDENT` | `evaluator.incident_detected=False` | False |
| `AUTHORISED_REVIEW` | active BSP found for `(client_id, practice_type)` | False |
| `UNAUTHORISED` | no active BSP found | **True** |

BSP match is case-insensitive on `practice_type`; `valid_from/until = NULL` means unbounded.

### Provider toggle

`google-genai` SDK supports both AI Studio and Vertex AI. Switch is automatic:
- `SENA_AI_GCP_PROJECT` empty → AI Studio (uses `SENA_AI_GEMINI_API_KEY`)
- `SENA_AI_GCP_PROJECT` set → Vertex AI (uses ADC, region from `SENA_AI_GCP_LOCATION`)

Embedder client is module-level — no per-call construction.

## Run Commands

```bash
# Infrastructure (Postgres + pgvector + Redis)
cd C:\Users\Admin\Documents\SENA\sena-ai && docker-compose up -d

# Ingest sample NDIS policies (no PDF required)
cd C:\Users\Admin\Documents\SENA\restrictive_practices
python scripts/ingest_docs.py --sample

# Ingest a real PDF
python scripts/ingest_docs.py --pdf path/to/guide.pdf \
    --category "Chemical Restraint" \
    --source "NDIS Regulated Restrictive Practices Guide 2023" \
    --risk "High Risk"

# API server
uvicorn main:app --reload --port 8084

# Smoke-test individual pipeline steps
python scripts/test_triage.py
python scripts/test_rag.py
python scripts/test_evaluator.py
python scripts/test_cross_check.py
python scripts/test_pipeline.py    # end-to-end
```

## Critical Rules

- `HALFVEC(3072)` (uppercase, DDL type) in `mapped_column()` — `HalfVector` is the runtime value class, wrong here
- `json.loads(response.text)` — `response.parsed` returns `None` on `gemini-2.5-x`
- `temperature=0.0` on every LLM call — compliance decisions must be deterministic
- LangGraph node names must NOT collide with `TypedDict` state keys (`_step` suffix convention)
- Triage uses `thinking_budget=0` and no `response_schema` — both cut latency on the hot path
- Evaluator needs `max_output_tokens=4096` minimum — lower truncates the JSON verdict
- Models: `gemini-2.5-flash` (triage), `gemini-2.5-pro` (evaluator); 2.0/1.5 deprecated
- Embedding model is whatever `config.embedding_model` says (`text-embedding-004` at time of writing) — `SESSION_START.md` may drift; treat `config.py` as source of truth
