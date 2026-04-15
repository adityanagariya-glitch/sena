---
title: Structure-Aware Chunking
type: decision
tags: [chunking, rag, decided]
sources: ["[[src-technical-decisions]]"]
created: 2026-04-15
updated: 2026-04-15
---

# Structure-Aware Chunking

**Status:** DECIDED

Documents are chunked **respecting structure** (headings, sections, tables) rather than blindly split on character count.

## Why

NDIS policy documents and provider manuals are heavily structured: numbered clauses, tables of allowable line items, definition blocks. Character-count splitting mid-clause destroys meaning and retrieval quality.

## Approach

- Use heading-aware splitters (e.g., markdown or HTML structure) to preserve section context
- Keep tables intact where possible; split only if a single table exceeds token limits
- Prepend section context (parent heading trail) to each chunk so it's self-describing
- Target chunk size ~500-1500 tokens with ~15% overlap

## Where applied

- v2: NDIS policy document ingestion
- Future: provider-specific template libraries

## Trade-offs

- More complex ingestion pipeline than fixed-size splitting
- Some structural parsers can fail on malformed inputs — need robust fallback

## Connections

- Hub: [[Architecture]]
- Source: [[src-technical-decisions]]
- Related: [[hybrid-search]], [[pgvector-decision]]
