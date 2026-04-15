---
title: pgvector
type: entity
tags: [postgres, vector-store, entity]
sources: ["[[src-technical-decisions]]"]
created: 2026-04-15
updated: 2026-04-15
---

# pgvector

PostgreSQL extension providing vector similarity search. Runs inside the `ai-db` Postgres instance on port 5433.

## Why it's here

See [[pgvector-decision]] for the rationale over Pinecone/Weaviate/etc.

## Index type

HNSW (Hierarchical Navigable Small World). Good recall/latency balance, fine at SENA's scale.

## Operational notes

- Index build can be slow on large tables → use `CREATE INDEX CONCURRENTLY` in production migrations
- RLS applies to vector queries like any other — tenant isolation carried end-to-end
- Metadata filtering (`tenant_id`, document type) done via standard `WHERE` clauses; HNSW handles the ANN part

## Connections

- Hub: [[Architecture]]
- Related: [[pgvector-decision]], [[row-level-security]], [[hybrid-search]]
