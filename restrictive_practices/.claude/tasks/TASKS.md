---
title: Restrictive Practices Detection Module — Task List
updated: 2026-05-13
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
- [x] HTTP smoke test — uvicorn + curl POST returned HTTP 200; full pipeline verified end-to-end
- [x] `document_type` column added to `rp_ndis_policy_chunks` — `models/db.py`, `db/session.py`, `ingestion/chunker.py`, `ingestion/embedder.py`, `pipeline/rag.py`
- [x] Evaluator expanded with NDIS reporting obligations — `reporting_required`, `notification_timeframe` fields
- [x] Privacy compliance headers — `X-Privacy-Classification`, `X-Data-Retention` in `api/routes.py`
- [x] Webhook alert sender — `pipeline/webhook.py`, wired into `pipeline/graph.py`
- [x] Configurable chunk size — `config.py` `chunk_size=1200`, `chunk_overlap=120`; `ingestion/chunker.py` reads from settings
- [x] Real NDIS PDF ingestion — `scripts/ingest_ndis_policies.py`; 4 of 5 docs ingested from local pdfs/ folder (~400+ chunks)
- [x] Demo BSPs seeded — `scripts/seed_demo.py`; 3 auth paths covered + liam-001 fixture
- [x] DEMO.md — 5 curl scenarios, privacy compliance table, DB verification
- [x] Makefile, docker-compose.yml, pyproject.toml in correct directory (`restrictive_practices/`)
- [x] Issues-solved knowledge base — `.claude/issues-solved/` with 11 entries; hooks updated

## Backlog
- [ ] Verify `rp_case_note_runs` audit rows written during demo runs (check DB)
- [ ] Auth middleware — wire `X-User-Id` / JWT header into FastAPI routes
- [ ] Unit tests for each pipeline step (pytest + pytest-asyncio)
- [ ] Alembic migrations — replace `create_tables()` for production DB management
- [ ] Rate limiting + retry hardening on Bedrock API calls
- [ ] Structured logging — JSON log format for production observability

## Session Fixes Log
### 2026-05-13 (AWS Bedrock migration)
- Migrated all LLM calls from google-genai → AWS Bedrock (Claude Haiku 4.5 triage, Sonnet 4.6 eval/draft)
- Migrated embeddings from Gemini text-embedding → Cohere Embed English v3 (1024 dims); dropped + re-ingested 581 chunks
- Fixed boto3 credential chain: pydantic-settings doesn't set os.environ; pass creds explicitly in all _make_client()
- Fixed JSON parsing: Bedrock models wrap JSON in markdown fences; use `_extract_json()` with raw_decode
- Fixed nested JSON: added explicit flat-key instruction to evaluator/drafter prompts
- Fixed alert_required: removed `bsp_mentioned_in_note` gate — model sets True even for negative mentions; rely on cross_check SQL
- All 8 form API scenarios verified with correct alert outcomes

### 2026-05-01 (model upgrade)
- Upgraded triage model: `gemini-2.5-flash` → `gemini-3-flash-preview`
- Upgraded evaluator model: `gemini-2.5-flash` (fallback) → `gemini-3.1-pro-preview`
- Updated `.env`, `config.py` defaults, CLAUDE.md, SESSION_START.md, hooks, issues-solved 0012

### 2026-05-01
- SSL/ReadTimeout/filename issues with NDIS PDF download → documented in issues-solved 0001–0003
- `json.loads()` not `response.parsed` for gemini-2.5-x → issues-solved 0004
- `HALFVEC` uppercase DDL type → issues-solved 0005
- LangGraph node name collision → issues-solved 0006
- `google-genai>=1.74.0` required → issues-solved 0007
- `gemini-2.5-pro` 404 in australia-southeast1 → issues-solved 0008
- Embedding model name differs by provider → issues-solved 0009
- 422 from Swagger UI literal newlines → issues-solved 0010
- `SettingsConfigDict(extra="ignore")` for shared `.env` → issues-solved 0011

### 2026-04-30
- `config.py` — `SettingsConfigDict(extra="ignore")` so shared `.env` keys for other modules don't break startup
- Upgraded `google-genai` 1.2.0 → 1.74.0 — older SDK lacked `ThinkingConfig.thinking_budget`
- `.env` `SENA_AI_EMBEDDING_MODEL`: `gemini-embedding-2` → `gemini-embedding-001` (Vertex AI naming)
- `.env` `SENA_AI_EVALUATOR_MODEL`: `gemini-2.5-pro` → `gemini-2.5-flash` (Pro 404 in au-southeast1 for this project)
