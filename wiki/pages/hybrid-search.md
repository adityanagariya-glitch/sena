---
title: Hybrid Search
type: decision
tags: [search, vector, bm25, decided]
sources: ["[[src-technical-decisions]]"]
created: 2026-04-15
updated: 2026-04-15
---

# Hybrid Search

**Status:** DECIDED

SENA uses **hybrid search**: vector similarity + BM25 keyword, combined via Reciprocal Rank Fusion (RRF).

## Why hybrid

- **Vector search** is strong on semantic similarity but weak on exact terms (medication names, NDIS line-item codes, participant names)
- **Keyword (BM25)** is strong on exact terms but blind to paraphrase
- Hybrid captures both. RRF is a simple, parameter-light fusion method that doesn't require score normalisation

## Stack

- Vector side: [[pgvector]] with HNSW index
- Keyword side: PostgreSQL full-text search (`tsvector`/`tsquery`) — same DB, no extra service
- Fusion: RRF applied in application layer after both searches return

## Trade-offs

- Two index types per corpus — more storage, more write cost on insert
- Fusion is pluggable; if RRF proves inadequate, we can swap in a learned reranker later

## Where it applies

- v2 feature: RAG over NDIS policy documents (replacing rule-based policy lookup)
- Case note retrieval for the manager review UI (planned)

## Related

- [[structure-aware-chunking]] — determines what the chunks being searched look like
- [[pgvector-decision]] — enables the vector half

## Connections

- Hub: [[Architecture]]
- Source: [[src-technical-decisions]]
