---
title: Monorepo Structure
type: topic
tags: [monorepo, repo-layout, python]
sources: ["[[src-architecture-audit]]", "CLAUDE.md"]
created: 2026-04-15
updated: 2026-04-15
---

# Monorepo Structure

The SENA AI/ML backend is a **Python workspace monorepo** at `sena-ai/`.

```
sena-ai/
├── services/
│   ├── voice/          # Active — Flow B case note dictation
│   └── ocr/            # Scaffolded, not yet implemented
├── shared/             # sena-common shared library
├── docker-compose.yml  # Redis + 2x PostgreSQL (ai-db with pgvector, shared-db)
├── .env.example        # All env vars with SENA_AI_ prefix
└── pyproject.toml      # Workspace root — ruff, mypy, pytest config
```

## Why workspace-style

- Single `pip install -e ".[dev]"` from `sena-ai/` installs everything editable
- Tooling config (ruff, mypy, pytest) defined once at root
- Shared lib (`sena-common`) imported directly without publishing to a package registry

## Databases

- **ai-db** (port 5433) — PostgreSQL with [[pgvector]]; voice session data, case notes, embeddings
- **shared-db** (port 5434) — PostgreSQL for cross-service data (planned)

## Env vars

All `SENA_AI_` prefixed, loaded via `pydantic-settings` from `.env`. See `.env.example`.

## Connections

- Hub: [[Architecture]]
- Related: [[fastapi-decision]], [[voice-service]], [[ocr-service]], [[sena-common]]
