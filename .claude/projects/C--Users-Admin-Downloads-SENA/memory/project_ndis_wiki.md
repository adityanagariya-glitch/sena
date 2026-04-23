---
name: project_ndis_wiki
description: ndis_wiki/ directory — NDIS regulatory source documents wiki, separate from wiki/ synthesis layer
type: project
---

`ndis_wiki/` added 2026-04-23. Official NDIS Quality and Safeguards Commission PDFs converted to markdown.

**Why:** Provides grounding source material for RAG pipeline, compliance queries, and onboarding voice flow grounding answers.

**How to apply:** When answering NDIS compliance/regulatory questions, check `ndis_wiki/index.md` → follow to `pages/summaries/`, `pages/entities/`, `pages/concepts/`. For RAG implementation, `ndis_wiki/sources/` is the document corpus.

## Structure
- `sources/` — raw markdown from official NDIS PDFs. **Immutable.**
- `pages/summaries/` — one summary per source doc
- `pages/entities/` — organizations/roles (NDIS Commission, Provider, Worker, Participant, Behaviour Support Practitioner…)
- `pages/concepts/` — policies/frameworks (Code of Conduct, Compliance, Restrictive Practices, Incident Management, Quality and Safeguarding Framework…)
- `index.md` — master catalog (sources + summaries + entities + concepts)
- `GEMINI.md` — wiki schema + ingest/query/lint workflows
- `log.md` — append-only operation log

## Key distinction from wiki/
| | `wiki/` | `ndis_wiki/` |
|--|---------|--------------|
| Layer | LLM synthesis | Regulatory source |
| Written by | Claude | Converted from PDFs |
| Source material | Architecture, client reqs, domain knowledge | NDIS Commission official documents |
| Mutability | Mutable (Claude updates) | Sources immutable; pages updated on ingest |
