# CLAUDE.md — Restrictive Practices Detection Module

## Session Start Protocol (READ EVERY SESSION)

1. `.claude/SESSION_START.md` — what was built last session, critical gotchas, what to do next
2. `.claude/tasks/TASKS.md` — live task list (done / in-progress / backlog)

## Module Overview

AI pipeline detecting NDIS regulated restrictive practices from support worker case notes.
Sits inside the broader SENA monorepo — see `C:\Users\Admin\Documents\SENA\CLAUDE.md` for platform context.

**Pipeline:** `POST /v1/restrictive-practices/evaluate`
```
triage (Flash) → [CLEAN] END
               → [FLAGGED] rag → evaluator (Pro) → cross_check (SQL) → CaseNoteRun audit
```

## Key Files

| File | Purpose |
|------|---------|
| `config.py` | Pydantic settings — all env vars via `SENA_AI_` prefix |
| `models/db.py` | ORM: NDISPolicyChunk, BehaviourSupportPlan, CaseNoteRun |
| `models/schemas.py` | Pydantic I/O schemas for every pipeline step |
| `pipeline/triage.py` | Gemini Flash YES/NO gate |
| `pipeline/rag.py` | pgvector HNSW cosine retrieval |
| `pipeline/evaluator.py` | Gemini Pro structured verdict |
| `pipeline/cross_check.py` | SQL BSP authorisation lookup |
| `pipeline/graph.py` | LangGraph wiring + audit persistence |
| `api/routes.py` | FastAPI `/evaluate` endpoint |
| `ingestion/embedder.py` | Gemini embedding upsert to pgvector |
| `scripts/ingest_docs.py` | CLI: `--sample` or `--pdf <path>` |

## Run Commands

```bash
# Infrastructure
cd C:\Users\Admin\Documents\SENA\sena-ai && docker-compose up -d

# Ingest sample NDIS policy data
cd C:\Users\Admin\Documents\SENA\restrictive_practices
python scripts/ingest_docs.py --sample

# Start API
uvicorn main:app --reload --port 8084
```

## Critical Rules

- `HALFVEC(3072)` not `HalfVector(3072)` in `mapped_column()`
- `json.loads(response.text)` not `response.parsed` — gemini-2.5-x doesn't auto-parse
- `temperature=0.0` on ALL LLM calls — compliance decisions must be deterministic
- LangGraph node names must NOT match TypedDict state keys — use `_step` suffix
- Models: `gemini-2.5-flash` (triage), `gemini-2.5-pro` (evaluator) — 2.0/1.5 deprecated

## Hooks (auto-enforced)

- **SessionStart** — injects SESSION_START.md + TASKS.md context automatically
- **PostToolUse** — bumps `updated:` date in TASKS.md + SESSION_START.md on every file write
- **Stop** — reminds to update TASKS.md before session ends
