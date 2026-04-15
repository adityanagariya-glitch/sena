---
title: Row-Level Security
type: decision
tags: [multi-tenancy, postgres, security, decided]
sources: ["[[src-technical-decisions]]"]
created: 2026-04-15
updated: 2026-04-15
---

# Row-Level Security

**Status:** DECIDED

PostgreSQL Row-Level Security (RLS) is SENA's primary mechanism for [[multi-tenancy]] enforcement at the database layer.

## How it works

Every tenant-scoped table has an RLS policy:

```sql
CREATE POLICY tenant_isolation ON <table>
USING (tenant_id = current_setting('app.current_tenant')::uuid);
```

At session start, the application sets `SET app.current_tenant = <tenant_id>`. Every subsequent query is automatically filtered to that tenant. Unset variable → policy returns zero rows.

## Why RLS over alternatives

| Option | Verdict |
|--------|---------|
| Schema-per-tenant | Too much operational burden for a 2-person team |
| DB-per-tenant | Even higher ops burden; prohibitive at 1000+ tenants |
| App-level filtering only | One forgotten `WHERE` → cross-tenant leak |
| **RLS + app filter (chosen)** | Defence in depth; DB refuses the bad query even if app forgets |

## Known trade-offs

- Queries with `current_setting` can't be fully planner-cached the same way across tenants
- Connection pooling with async SQLAlchemy needs care to ensure `SET` is applied per-connection, not per-transaction
- Migrations touching RLS policies need review — an incorrect policy can silently block legitimate reads

## Related tables

All tables under `sena_common` and `voice` schemas with a `tenant_id` column. See `sena-ai/shared/sena_common/` for the middleware that sets `app.current_tenant` per request.

## Connections

- Hub: [[NDIS]], [[Architecture]]
- Related: [[multi-tenancy]], [[pgvector-decision]]
- Source: [[src-technical-decisions]]
