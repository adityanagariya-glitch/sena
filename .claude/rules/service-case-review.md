---
paths:
  - "sena-ai/services/case_review/**/*.py"
  - "sena-ai/services/case_review/pyproject.toml"
  - "sena-ai/services/case_review/migrations/**/*.py"
---

# Case Review Service — AI intelligence layer (port 8084)

At `sena-ai/services/case_review/src/case_review/`. ai-db with pgvector. **Shelved at Phase C** as of 2026-05-14.

## Layer map

| Layer | Path | Purpose |
|-------|------|---------|
| API | `api/routes.py` | 6 REST endpoints (context, classify, review, incident/*, submit) + health |
| API | `api/deps.py` | DI: AsyncSession, ReviewRepo, CaseNoteClient, AuthContext (dev_header) |
| Models | `models/db.py` | 4 ORM tables: RollingSummary, ReviewSession, IncidentDraft, ReviewAuditLog |
| Models | `models/schemas.py` | Pydantic DTOs for all endpoints |
| Repositories | `repositories/review_repo.py` | CRUD + upsert (rolling summary) + audit append |
| Clients | `clients/case_note_client.py` | Stub (fixtures) + real HTTP client (future) |
| Fixtures | `fixtures/sample_notes.json` | 3 fake case notes for stub client |
| Migrations | `migrations/versions/0001_*.py` | 4 tables + RLS policies on tenant_id |

## Routes (501 in Phase A — implemented progressively)
- `POST /v1/case-review/context` — fetch + rolling summary (Phase B)
- `POST /v1/case-review/classify` — paragraph → fields + reask prompts (Phase C)
- `POST /v1/case-review/review` — risk/restrictive-practice/anomaly flags (Phase D)
- `POST /v1/case-review/incident/detect` + `/draft` + `PATCH .../confirm` (Phase E)
- `POST /v1/case-review/submit` — final gate (Phase F, BLOCKED)

## Non-negotiables (MANDATORY — legal compliance)
- `tenant_id` on every DB row + RLS enforced (legal mandate)
- Staff must acknowledge every AI flag — no auto-submit
- Audit log entry for every AI action + staff decision
- `GEMINI_REGION=australia-southeast1` (data residency)

## Run
```bash
cd sena-ai/services/case_review
uvicorn src.case_review.main:create_app --factory --reload --port 8084
# Alembic: alembic upgrade head  (requires ai-db running)
```

## Env vars (`SENA_AI_` prefix)
`CASE_REVIEW_PORT`, `AI_DB_URL`, `GEMINI_API_KEY`, `GEMINI_MODEL_ID` (=`gemini-3-flash-preview`), `GEMINI_REGION` (=`australia-southeast1`), `DRAFTING_SERVICE_URL`, `DRAFTING_SERVICE_API_KEY`, `CASE_NOTE_FETCH_LIMIT`
