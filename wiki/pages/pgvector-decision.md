---
title: pgvector Decision
type: decision
tags: [vector-store, postgres, decided]
sources: ["[[src-technical-decisions]]"]
created: 2026-04-15
updated: 2026-04-15
---

# pgvector Decision

**Status:** DECIDED

[[pgvector]] (the PostgreSQL extension) is SENA's vector store. No separate vector database.

## Why pgvector over dedicated vector DBs

| Option | Verdict |
|--------|---------|
| **pgvector (chosen)** | Same DB as everything else; [[row-level-security]] applies uniformly; HNSW index fine to ~100M vectors |
| Pinecone / Weaviate / Qdrant (managed) | Extra service to pay for, monitor, back up; tenant isolation becomes a cross-system concern |
| Milvus / Chroma (self-hosted) | Extra ops for the 2-person team |
| OpenSearch k-NN | Heavier than needed; no strong advantage over pgvector for our scale |

## Key benefits

- **RLS carries through** — vector rows are tenant-scoped like any other row; the same policy prevents cross-tenant retrieval
- **Transactional consistency** — inserts into the parent table and vector index happen in the same transaction
- **Operational simplicity** — one DB to back up, migrate, monitor

## Trade-offs

- At very large scale (hundreds of millions of vectors per tenant) a dedicated vector DB may outperform — but that's well past SENA's current horizon
- Index build time with HNSW on very large tables can be slow; requires maintenance windows or concurrent build

## Companion decisions

- [[hybrid-search]] — vector similarity + BM25 keyword for better recall
- [[structure-aware-chunking]] — how documents are chunked before embedding

## Connections

- Hub: [[Architecture]]
- Source: [[src-technical-decisions]]
- Related: [[row-level-security]], [[hybrid-search]]
