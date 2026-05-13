---
paths:
  - "sena-ai/services/case_review/migrations/**/*.py"
  - "sena-ai/services/*/src/*/repositories/**/*.py"
  - "sena-ai/services/*/src/*/models/db.py"
  - "sena-ai/migrations/**/*.py"
  - "sena-ai/migrations/**/*.sql"
---

# Database & State Rules (path-scoped)

Loads ONLY when an edit touches an Alembic migration, a repository, an ORM model, or raw SQL.

## Tenant isolation (LEGAL MANDATE — non-negotiable)

### Postgres (voice, case_review)
- Every table has a `tenant_id` column (uuid, NOT NULL).
- Every table has an RLS policy:
  ```sql
  CREATE POLICY tenant_isolation ON <table>
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
  ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;
  ALTER TABLE <table> FORCE ROW LEVEL SECURITY;
  ```
- Every transaction sets `app.current_tenant_id` via `SET LOCAL` before any SELECT/INSERT/UPDATE — handled by the per-request DB session dependency.
- Raw SQL bypasses RLS — use SQLAlchemy ORM with bound params only. Raw queries that bypass the ORM bypass RLS.

### Redis (onboarding — no Postgres there)
- Every key MUST include `tenant_id`. Pattern:
  ```python
  f"sena:onboarding:{tenant_id}:{session_id}:state"
  ```
- Always call `assert_session_owner(session_id, tenant_id)` BEFORE read or write. Missing `assert_session_owner` is a critical security finding.
- TTLs explicit on every key. Default session TTL: `settings.session_max_sec`.
- Key construction: never concatenate unvalidated input. Use a parameterised key builder.

## Migrations
- Every Alembic migration that creates a tenant-scoped table MUST also set up the RLS policy in the same migration. Never ship a tenant table without RLS — it cannot be patched later in production safely.
- Include `tenant_id` in every foreign-key composite where it strengthens isolation (`(tenant_id, participant_id)`, etc.).
- Migrations are forward-only by convention; `downgrade()` may be `pass` with a comment explaining why a rollback would destroy data.
- Test migrations against a real Postgres locally before merging — Alembic's autogenerate can miss RLS clauses.

## Connection management
- AsyncSession only. No sync sessions in async code.
- Acquire per-request, release on response. Never share a session across request boundaries.
- Use `async with session.begin():` for transactional blocks. Never raw `commit()` calls scattered through repo methods.

## Index hygiene
- Every foreign key gets an index.
- Every column used in a WHERE clause that scans > 10k rows in production gets an index.
- pgvector embedding columns: HNSW or IVFFlat, chosen by query pattern — not "the default".

## SENA Redis key inventory (onboarding service — Redis-only, no Postgres)

Authoritative key patterns. EVERY key includes `tenant_id`. EVERY read/write path calls `assert_session_owner` first.

| Purpose | Key pattern | TTL | Notes |
|---------|-------------|-----|-------|
| FormState | `sena:onboarding:{tenant_id}:{session_id}:state` | `session_max_sec` | Primary state — JSON-serialised FormState |
| Step schema (per session) | `sena:onboarding:{tenant_id}:{session_id}:schema` | `session_max_sec` | Inline schema sent by app at session create |
| WebSocket lock | `sena:onboarding:{tenant_id}:{session_id}:ws_lock` | bounded | PUT to state blocked while held |
| Resumption handle | `sena:onboarding:{tenant_id}:{handle_id}:resume` | `RESUMPTION_HANDLE_TTL_SEC` (default 600) | Single-use via atomic `GETDEL` — never `GET` + `DEL` separately |
| Transcript ring buffer | `sena:onboarding:{tenant_id}:{session_id}:transcript` | `session_max_sec` | Bounded — last N turns only |
| Cross-screen bucket (Hash) | `sena:onboarding:cs:{tenant_id}:{participant_id}` | 7 days, refreshed on every write | Step summaries Hash; isolation is structural (key prefix), not flag-dependent |
| Cross-screen session index (Set) | `sena:onboarding:cs:{tenant_id}:{participant_id}:sessions` | 7 days | Tracks which session IDs contributed to the bucket |

When adding a NEW key:
1. Prefix is `sena:<service>:` — never just `sena:`.
2. `tenant_id` is the FIRST segment after the service prefix. Never omit. Missing `tenant_id` is a Critical security finding (sena-security-reviewer, not a routine fix).
3. Add the row to this inventory table in the SAME PR.
4. Add a key-construction unit test that asserts the prefix and tenant scoping (e.g. `test_state_key_includes_tenant_id`).
5. Decide TTL explicitly. Never `SET` without `EX`.
