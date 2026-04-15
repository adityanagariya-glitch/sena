---
title: Technical Decisions (Source)
type: source
raw_path: "archive/Extras/TECHNICAL_DECISIONS.md"
ingested: 2026-04-15
tags: [architecture, decisions, source]
---

# Technical Decisions (Source Summary)

## Key Takeaways

- A/B/C decision log organised by status: DECIDED, LEANING, OPEN
- 5 decisions DECIDED: Python+FastAPI, Row-Level Security, pgvector, hybrid search, structure-aware chunking
- Cloud provider decision BLOCKED on client answer (GCP vs AWS vs Azure)
- Deployment model OPEN (Cloud Run, Kubernetes, serverless)
- 2-person team capacity drives simplicity bias

## Detailed Summary

Trade-off analysis document. Sections grouped as:
- **A. Foundational** — language/framework, multi-tenancy model
- **B. Module-specific** — vector store, embedding model, search strategy, chunking, OCR service
- **C. Operational** — cloud provider, deployment model, observability

For each open item: options listed, trade-offs scored, recommendation + rationale.

Decisions became DECIDED when enough evidence accumulated and no client blocker remained.

## Pages Updated

- [[fastapi-decision]]
- [[row-level-security]]
- [[pgvector-decision]]
- [[hybrid-search]]
- [[structure-aware-chunking]]
- [[cloud-provider-decision]]
- [[deployment-environment]]
- [[llm-provider-decision]]

## Connections

- Hub: [[Architecture]]
- Related sources: [[src-architecture-audit]]
