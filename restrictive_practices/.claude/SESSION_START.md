---
title: Restrictive Practices Detection — Session Start Guide
updated: 2026-05-12
---

## Read This First Every Session

1. This file — what was built, what's next
2. `.claude/tasks/TASKS.md` — live task status
3. `.claude/issues-solved/INDEX.md` — grep before debugging anything
4. `CLAUDE.md` (project root) — coding rules, architecture, hooks

---

## What Was Built (Last Session: 2026-05-01)

Full demo-ready NDIS restrictive practice detection pipeline — implemented, ingested with real NDIS PDFs, and verified end-to-end via Swagger UI and curl.

| Step | File(s) | Status |
|------|---------|--------|
| 1 | `models/db.py`, `db/session.py` | Done — `HALFVEC(3072)` column + HNSW index + `document_type` column |
| 2 | `ingestion/chunker.py`, `embedder.py`, `scripts/ingest_docs.py` | Done — Gemini embedding (3072 dims), configurable chunk size |
| 3 | `pipeline/triage.py` | Done — `gemini-3-flash-preview` YES/NO gate, `thinking_budget=0` |
| 4 | `pipeline/rag.py` | Done — pgvector cosine similarity, top-K, `document_type` in results |
| 5 | `pipeline/evaluator.py` | Done — `gemini-3.1-pro-preview` structured verdict + reporting obligations |
| 6 | `pipeline/cross_check.py` | Done — SQL BSP authorisation lookup |
| 7 | `pipeline/graph.py`, `api/routes.py` | Done — LangGraph + FastAPI `/evaluate` + privacy headers |
| 8 | `pipeline/webhook.py` | Done — HMAC-signed alert POST on `alert_required=True` |
| 9 | `scripts/ingest_ndis_policies.py` | Done — 5 official NDIS PDFs ingested (~400+ chunks) |
| 10 | `scripts/seed_demo.py` | Done — BSPs seeded for all 3 auth paths |
| 11 | `DEMO.md` | Done — 5 curl scenarios + privacy compliance guide |

### Pipeline flow
```
POST /v1/restrictive-practices/evaluate
  → triage_step  (Flash: YES/NO, thinking_budget=0)
      → [CLEAN]   END — no further LLM cost (≈70% of notes)
      → [FLAGGED] rag_step → evaluator_step → cross_check_step → webhook → END
  → CaseNoteRun audit row written regardless of outcome
```

### Demo BSPs seeded
| client_id | practice_type | Path |
|-----------|--------------|------|
| `client-demo-auth` | Physical Restraint | AUTHORISED_REVIEW |
| `client-demo-chem` | Chemical Restraint | AUTHORISED_REVIEW |
| `client-demo-mech` | Mechanical Restraint | AUTHORISED_REVIEW |
| `liam-001` | Physical Restraint, Chemical Restraint, Environmental Restraint | AUTHORISED_REVIEW |
| `client-demo-unauth` | (no BSP) | UNAUTHORISED + alert |

---

## Critical Gotchas (Do NOT Re-Derive)

| Problem | Fix | Issue # |
|---------|-----|---------|
| `HalfVector(3072)` in mapped_column | Use `HALFVEC(3072)` — uppercase = DDL type | 0005 |
| HNSW index operator class | `halfvec_cosine_ops` not `vector_cosine_ops` | 0005 |
| `response.parsed` is None | Use `json.loads(response.text)` for gemini-2.5-x | 0004 |
| Models deprecated | `gemini-2.5-x`, `gemini-2.0-x`, `gemini-1.5-x` all deprecated — use `gemini-3-flash-preview` / `gemini-3.1-pro-preview` | — |
| LangGraph node name conflicts | Node names must NOT match `TypedDict` keys — append `_step` | 0006 |
| `.env` not loaded from scripts | `config.py` uses `Path(__file__).parent / ".env"` (absolute) | — |
| Evaluator truncated JSON | `max_output_tokens=4096` minimum for evaluator | — |
| SSL error on NDIS PDF download | `verify=False` + browser User-Agent in httpx client | 0001 |
| ReadTimeout on NDIS PDFs | Check URL path — government sites restructure URLs; use local pdfs/ fallback | 0002 |
| PDF filename mismatch in pdfs/ | Check both `local_filename` AND URL basename as candidates | 0003 |
| 422 from Swagger UI | Literal newlines in JSON string — use `\n` escape or single line | 0010 |
| Evaluator 404 on Vertex AI | Flash fallback: `SENA_AI_EVALUATOR_MODEL=gemini-3-flash-preview`; AI Studio always has both | 0008 |
| Embedding model 404 | AI Studio: `gemini-embedding-2`; Vertex: `gemini-embedding-001` | 0009 |
| Extra `.env` keys crash startup | `SettingsConfigDict(extra="ignore")` — shared `.env` has other module keys | 0011 |
| SDK missing `thinking_budget` | `google-genai>=1.74.0` required | 0007 |

---

## What To Do Next Session

1. **Verify DB audit rows** after live demo run:
```bash
docker exec -it sena-ai-db psql -U sena_ai -d sena_ai \
  -c "SELECT case_note_id, triage_flagged, authorisation_status, alert_required, processing_time_ms FROM rp_case_note_runs ORDER BY created_at DESC LIMIT 5;"
```

2. **Verify gemini-3.1-pro-preview** is accessible on the active provider (AI Studio or Vertex AI australia-southeast1)
   — if 404, use `SENA_AI_EVALUATOR_MODEL=gemini-3-flash-preview` as fallback

3. **Unit tests** — pytest + pytest-asyncio for each pipeline step

4. **Alembic migrations** — replace `create_tables()` for production DB management

5. **Auth middleware** — wire `X-User-Id` / JWT header into FastAPI routes

---

## Environment

- Python env: `conda activate sena_env`
- DB: Docker `sena-ai-db` on port 5433 (start with `docker-compose up -d` from `restrictive_practices/`)
- API: `uvicorn main:app --reload --port 8084` from `restrictive_practices/`
- Gemini: AI Studio key in `.env` (`SENA_AI_GEMINI_API_KEY`)
- Quick setup: `make demo-setup && make server`
