---
title: Restrictive Practices — Database Schema Reference
updated: 2026-04-28
---

## Database

**PostgreSQL + pgvector** (`ai-db`)

| Setting | Value |
|---------|-------|
| Host | `localhost:5433` |
| Credentials | `sena_ai:sena_ai` |
| DB name | `sena_ai` |
| Docker container | `sena-ai-db` |
| Extension | `pgvector` |
| Start command | `docker-compose up -d` from `sena-ai/` |

---

## Tables

### `rp_ndis_policy_chunks`
Stores embedded NDIS policy document chunks for RAG retrieval.

| Column | Type | Notes |
|--------|------|-------|
| `id` | integer PK | auto-increment |
| `chunk_id` | varchar(64) UNIQUE | SHA-256 of source+index — enables idempotent upserts |
| `text` | text | raw policy chunk text |
| `category` | varchar(100) | one of 5 practice categories (indexed) |
| `document_source` | varchar(200) | source document name |
| `risk_level` | varchar(50) | Low / Medium / High / Critical |
| `embedding` | `halfvec(3072)` | Gemini `gemini-embedding-2` vector, half-precision 16-bit |
| `created_at` | timestamp | server default |

**Index:** HNSW on `embedding` using `halfvec_cosine_ops` — fast cosine similarity search.

**Ingest:** `python scripts/ingest_docs.py --sample` or `--pdf <path>`

---

### `behaviour_support_plans`
Pre-authorised restrictive practices per client — source of truth for cross-check step.

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | |
| `client_id` | varchar(100) | links to client (indexed) |
| `practice_type` | varchar(100) | e.g. "Chemical Restraint" (case-insensitive match in pipeline) |
| `status` | varchar(20) | `Active` / `Inactive` |
| `approved_dosage` | varchar(200) | e.g. "Up to 5mg diazepam PRN" |
| `approved_conditions` | text | when the practice is permitted |
| `authorised_by` | varchar(200) | practitioner name |
| `valid_from` | timestamp | plan start (null = always valid from start) |
| `valid_until` | timestamp | plan expiry (null = no expiry) |
| `created_at` | timestamp | server default |

**Cross-check logic:** matches `client_id` + `LOWER(practice_type)` + `status=Active` + date range.
If no match → `Unauthorised Restrictive Practice`. If match → `Authorised Use (Review Required)`.

---

### `rp_case_note_runs`
Append-only audit log — every case note processed, regardless of outcome.

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID PK | |
| `case_note_id` | varchar(100) | ID from calling system (indexed) |
| `client_id` | varchar(100) | (indexed) |
| `worker_id` | varchar(100) | |
| `triage_flagged` | boolean | did triage flag this note? |
| `evaluator_output` | JSONB | full evaluator verdict — category, risk, action_summary, reasoning |
| `authorisation_status` | varchar(100) | Unauthorised / Authorised Use / No Incident |
| `alert_required` | boolean | was escalation triggered? |
| `processing_time_ms` | integer | end-to-end pipeline latency |
| `created_at` | timestamp | server default |

---

## Useful Queries

```sql
-- All tables
\dt

-- Recent pipeline runs
SELECT case_note_id, triage_flagged, authorisation_status, alert_required, processing_time_ms
FROM rp_case_note_runs
ORDER BY created_at DESC LIMIT 10;

-- All alerts raised
SELECT case_note_id, client_id, authorisation_status, created_at
FROM rp_case_note_runs
WHERE alert_required = true
ORDER BY created_at DESC;

-- Policy chunk count by category
SELECT category, COUNT(*) AS chunks
FROM rp_ndis_policy_chunks
GROUP BY category ORDER BY category;

-- Check embedding dimensions
SELECT category, ROUND(AVG(vector_dims(embedding::vector))::numeric, 0) AS dims
FROM rp_ndis_policy_chunks
GROUP BY category;

-- Active BSPs for a client
SELECT practice_type, status, authorised_by, valid_until
FROM behaviour_support_plans
WHERE client_id = 'your-client-id' AND status = 'Active';
```

```bash
# Connect to DB
docker exec -it sena-ai-db psql -U sena_ai -d sena_ai
```
