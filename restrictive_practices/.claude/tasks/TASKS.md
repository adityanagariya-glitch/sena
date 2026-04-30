---
title: Restrictive Practices Detection Module — Task List
updated: 2026-04-30
---

## Done
- [x] Step 1: DB schema + pgvector setup (`models/db.py`, `db/session.py`)
- [x] Step 2: NDIS doc ingestion + embeddings (`ingestion/chunker.py`, `ingestion/embedder.py`, `scripts/ingest_docs.py`)
- [x] Step 3: Triage classifier — Gemini Flash YES/NO gate (`pipeline/triage.py`) — verified
- [x] Step 4: RAG retrieval — pgvector HNSW cosine search (`pipeline/rag.py`) — verified
- [x] Step 5: Evaluator agent — Gemini Pro structured verdict (`pipeline/evaluator.py`) — verified
- [x] Step 6: BSP cross-check — SQL authorisation lookup (`pipeline/cross_check.py`) — verified
- [x] Step 7: LangGraph pipeline wiring + FastAPI endpoint (`pipeline/graph.py`, `api/routes.py`) — verified
- [x] Session persistence — TASKS.md, SESSION_START.md, hooks wired

## In Progress
- [x] HTTP smoke test — uvicorn + curl POST returned HTTP 200; full pipeline verified end-to-end (triage flagged → RAG → evaluator → cross_check UNAUTHORISED → alert_required=true)

## Backlog
- [ ] Verify `rp_case_note_runs` audit row written for the smoke test run
- [ ] Request `gemini-2.5-pro` enablement on project `mobileappdev-2c1bd` in `australia-southeast1` — currently only Flash provisioned; evaluator running on Flash as fallback (lower-quality reasoning for compliance verdicts)
- [ ] Re-ingest NDIS chunks once embedding model finalised — chunks in DB embedded with whatever model was used during `--sample`; queries now hit `gemini-embedding-001`
- [ ] Real NDIS PDF ingestion — `python scripts/ingest_docs.py --pdf <path>`
- [ ] Webhook integration — POST alert to `rp_webhook_url` when `alert_required=True`
- [ ] Auth middleware — wire `X-User-Id` / JWT header into FastAPI routes
- [ ] Unit tests for each pipeline step (pytest + pytest-asyncio)
- [ ] Alembic migrations — replace `create_tables()` for production DB management
- [ ] Rate limiting + retry hardening on Gemini API calls
- [ ] Structured logging — JSON log format for production observability

## Session Fixes (2026-04-30)
- `config.py` — `SettingsConfigDict(extra="ignore")` so shared `.env` keys for other modules don't break startup
- Upgraded `google-genai` 1.2.0 → 1.74.0 — older SDK lacked `ThinkingConfig.thinking_budget`
- `.env` `SENA_AI_EMBEDDING_MODEL`: `gemini-embedding-2` → `gemini-embedding-001` (Vertex AI naming; `-2` is AI Studio only)
- `.env` `SENA_AI_EVALUATOR_MODEL`: `gemini-2.5-pro` → `gemini-2.5-flash` (Pro 404 in au-southeast1 for this project)
