---
title: Restrictive Practices Detection — Session Start Guide
updated: 2026-05-20
---

## Read This First Every Session

1. This file — what was built, what's next
2. `.claude/tasks/TASKS.md` — live task status
3. `.claude/issues-solved/INDEX.md` — grep before debugging anything
4. `CLAUDE.md` (project root) — coding rules, architecture, hooks

---

## What Was Built (Last Session: 2026-05-14)

**AWS Bedrock migration complete.** Pipeline migrated from google-genai/Gemini to AWS Bedrock (Claude + Cohere). All 8 form API scenarios verified end-to-end with correct alert_required logic.

| Step | File(s) | Status |
|------|---------|--------|
| 1 | `models/db.py`, `db/session.py` | Done — `HALFVEC(1024)` column (changed from 3072) + HNSW index |
| 2 | `ingestion/chunker.py`, `embedder.py` | Done — Cohere Embed English v3 (1024 dims) via Bedrock invoke_model |
| 3 | `pipeline/triage.py` | Done — Claude Haiku 4.5 YES/NO gate |
| 4 | `pipeline/rag.py` | Done — pgvector cosine similarity, top-K |
| 5 | `pipeline/evaluator.py` | Done — Claude Sonnet 4.6 structured verdict |
| 6 | `pipeline/cross_check.py` | Done — SQL BSP authorisation lookup (unchanged) |
| 7 | `pipeline/graph.py` | Done — alert_required logic fixed (removed bsp_mentioned_in_note gate) |
| 8 | `pipeline/drafter.py` | Done — Claude Sonnet 4.6 case note drafter |
| 9 | `scripts/ingest_ndis_policies.py` | Done — 581 chunks stored across 5 NDIS PDFs |
| 10 | `scripts/seed_demo.py` | Done — BSPs seeded for all auth paths |
| 11 | `pipeline/summary.py` | Done — Claude Haiku shift summariser; always runs; `summary` block in every `/evaluate` response |
| 12 | `pipeline/incident_draft.py` | Done — Claude Sonnet incident report drafter; conditional on `incident_occurred=True` OR `UNAUTHORISED` verdict |

### Pipeline flow
```
POST /v1/restrictive-practices/evaluate
  → triage_step  (Haiku: YES/NO)
      → [CLEAN]   summary_step → END
      → [FLAGGED] rag_step → evaluator_step → cross_check_step → summary_step
                  → incident_draft_step  (when incident_occurred=True OR UNAUTHORISED)
                  → webhook (when alert_required=True) → END
  → CaseNoteRun audit row written regardless of outcome
```

`/evaluate` response now always includes `summary` (ai_confidence, progress_identified, potential_risks, patterns_detected, flagged_highlights). Includes `incident_report` when `incident_occurred=True` OR verdict is `UNAUTHORISED`.

`/draft` response now includes `transcript` and `uploaded_documents` pass-through fields alongside the 6 case note sections.

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
| `HalfVector(1024)` in mapped_column | Use `HALFVEC(1024)` — uppercase = DDL type | 0005 |
| HNSW index operator class | `halfvec_cosine_ops` not `vector_cosine_ops` | 0005 |
| boto3 ignores pydantic-settings `.env` | pydantic-settings does NOT inject into os.environ; pass creds explicitly: `boto3.client(..., aws_access_key_id=settings.aws_access_key_id, ...)` | — |
| AWS creds `SENA_AI_` prefix bypass | Use `Field(validation_alias="AWS_ACCESS_KEY_ID")` — no SENA_AI_ prefix for standard AWS env vars | — |
| Bedrock returns JSON in markdown fences | Use `_extract_json()` with `json.JSONDecoder().raw_decode(text, text.find("{"))` — handles fences + trailing text | — |
| Bedrock returns nested JSON | Add explicit flat-key instruction to prompt: "Respond with a single flat JSON object — no nested objects" | — |
| `bsp_mentioned_in_note` blocks alerts | Model sets True even for negative mentions. Drop this from alert_required condition; use cross_check SQL result only | — |
| LangGraph node name conflicts | Node names must NOT match `TypedDict` keys — append `_step` | 0006 |
| `.env` not loaded from scripts | `config.py` uses `Path(__file__).parent / ".env"` (absolute) | — |
| SSL error on NDIS PDF download | `verify=False` + browser User-Agent in httpx client | 0001 |
| 422 from Swagger UI | Literal newlines in JSON string — use `\n` escape or single line | 0010 |
| Extra `.env` keys crash startup | `SettingsConfigDict(extra="ignore")` — shared `.env` has other module keys | 0011 |
| Cohere embed asymmetric input_type | `"search_document"` for ingest, `"search_query"` for RAG queries — must not mix | — |
| Embedding dim change | Gemini 3072 → Cohere 1024: must DROP table + re-ingest; HALFVEC(1024) in db.py | — |

---

## What To Do Next Session

1. **Verify DB audit rows** after live demo run:
```bash
docker exec -it sena-ai-db psql -U sena_ai -d sena_ai \
  -c "SELECT case_note_id, triage_flagged, authorisation_status, alert_required, processing_time_ms FROM rp_case_note_runs ORDER BY created_at DESC LIMIT 5;"
```

2. **Run server + test /draft endpoint** with a voice transcript via Swagger or curl

3. **Unit tests** — pytest + pytest-asyncio for each pipeline step

4. **Alembic migrations** — replace `create_tables()` for production DB management

5. **Auth middleware** — wire `X-User-Id` / JWT header into FastAPI routes

---

## Environment

- Python env: `conda activate sena_env`
- DB: Docker `sena-ai-db` on port 5433 (start with `docker-compose up -d` from `restrictive_practices/`)
- API: `uvicorn main:app --reload --port 8084` from `restrictive_practices/`
- AWS: credentials in `.env` as `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` (no SENA_AI_ prefix)
- Models: `global.anthropic.claude-haiku-4-5-20251001-v1:0` (triage), `global.anthropic.claude-sonnet-4-6` (eval/draft)
- Quick setup: `make demo-setup && make server`
