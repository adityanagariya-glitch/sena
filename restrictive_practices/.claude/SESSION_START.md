---
title: Restrictive Practices Detection — Session Start Guide
updated: 2026-04-30
---

## Read This First Every Session

1. This file — what was built, what's next
2. `.claude/tasks/TASKS.md` — live task status
3. `CLAUDE.md` (project root) — coding rules, architecture, hooks

---

## What Was Built (Last Session: 2026-04-28)

Full 7-step NDIS restrictive practice detection pipeline — implemented and end-to-end verified.

| Step | File(s) | Status |
|------|---------|--------|
| 1 | `models/db.py`, `db/session.py` | Done — `HALFVEC(3072)` column + HNSW index |
| 2 | `ingestion/chunker.py`, `embedder.py`, `scripts/ingest_docs.py` | Done — Gemini `gemini-embedding-2` (3072 dims) |
| 3 | `pipeline/triage.py` | Done — `gemini-2.5-flash` YES/NO gate |
| 4 | `pipeline/rag.py` | Done — pgvector cosine similarity, top-K |
| 5 | `pipeline/evaluator.py` | Done — `gemini-2.5-pro` structured verdict |
| 6 | `pipeline/cross_check.py` | Done — SQL BSP authorisation lookup |
| 7 | `pipeline/graph.py`, `api/routes.py` | Done — LangGraph + FastAPI `/evaluate` |

### Pipeline flow
```
POST /v1/restrictive-practices/evaluate
  → triage_step  (Flash: YES/NO)
      → [CLEAN]  END — no LLM cost
      → [FLAGGED] rag_step → evaluator_step → cross_check_step → END
  → CaseNoteRun audit row written to DB
```

---

## Critical Gotchas (Do NOT Re-Derive)

| Problem | Fix |
|---------|-----|
| `HalfVector(3072)` in mapped_column | Use `HALFVEC(3072)` — uppercase = DDL type |
| HNSW index operator class | `halfvec_cosine_ops` not `vector_cosine_ops` |
| `response.parsed` is None | Use `json.loads(response.text)` for gemini-2.5-x |
| Models deprecated | `gemini-2.0-flash`, `gemini-1.5-pro` gone — use `gemini-2.5-flash`/`gemini-2.5-pro` |
| LangGraph node name conflicts | Node names must NOT match `TypedDict` keys — append `_step` |
| `.env` not loaded from scripts | `config.py` uses `Path(__file__).parent / ".env"` (absolute) |
| Evaluator truncated JSON | `max_output_tokens=4096` minimum for evaluator |

---

## What To Do Next Session

1. **HTTP smoke test** — verify the live API endpoint:
```bash
cd C:\Users\Admin\Documents\SENA\sena-ai && docker-compose up -d
cd C:\Users\Admin\Documents\SENA\restrictive_practices
uvicorn main:app --reload --port 8084
```
Then POST:
```bash
curl -s -X POST http://localhost:8084/v1/restrictive-practices/evaluate \
  -H "Content-Type: application/json" \
  -d "{\"case_note_id\":\"$(python -c 'import uuid; print(uuid.uuid4())')\",\"client_id\":\"client-001\",\"worker_id\":\"worker-001\",\"transcript\":\"I gave him 5mg of diazepam to calm him down before the activity.\"}"
```
Check DB audit row:
```bash
docker exec -it sena-ai-db psql -U sena_ai -d sena_ai -c "SELECT case_note_id, triage_flagged, authorisation_status, alert_required, processing_time_ms FROM rp_case_note_runs ORDER BY created_at DESC LIMIT 5;"
```

2. **Real NDIS PDFs** — `python scripts/ingest_docs.py --pdf <path/to/ndis_policy.pdf>`
3. **Webhook** — implement alert POST to `SENA_AI_RP_WEBHOOK_URL`
4. **Auth** — wire `X-User-Id` header into FastAPI routes

---

## Environment

- Python env: `conda activate sena_env`
- DB: Docker `sena-ai-db` on port 5433 (start with `docker-compose up -d` from `sena-ai/`)
- API: `uvicorn main:app --reload --port 8084` from `restrictive_practices/`
- Gemini: AI Studio key in `.env` (`SENA_AI_GEMINI_API_KEY`)
