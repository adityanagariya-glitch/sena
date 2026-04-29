---
title: Restrictive Practices Detection Module — Task List
updated: 2026-04-28
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
- [ ] HTTP smoke test — start uvicorn, POST to `/v1/restrictive-practices/evaluate`, verify audit row in DB

## Backlog
- [ ] Real NDIS PDF ingestion — `python scripts/ingest_docs.py --pdf <path>`
- [ ] Webhook integration — POST alert to `rp_webhook_url` when `alert_required=True`
- [ ] Auth middleware — wire `X-User-Id` / JWT header into FastAPI routes
- [ ] Unit tests for each pipeline step (pytest + pytest-asyncio)
- [ ] Alembic migrations — replace `create_tables()` for production DB management
- [ ] Rate limiting + retry hardening on Gemini API calls
- [ ] Structured logging — JSON log format for production observability
