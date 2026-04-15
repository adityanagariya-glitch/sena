---
title: FastAPI
type: entity
tags: [python, framework, entity]
sources: ["[[src-technical-decisions]]"]
created: 2026-04-15
updated: 2026-04-15
---

# FastAPI

Python async web framework. See [[fastapi-decision]] for rationale.

## How it's used

- HTTP API surface of the voice service (`sena-ai/services/voice/src/voice/api/`)
- Request/response models via Pydantic (`models/schemas.py`)
- Dependency injection for DB session + Redis client (`api/deps.py`)
- Settings via `pydantic-settings` (`core/settings.py`, `SENA_AI_` env prefix)

## Key routes

See CLAUDE.md for the full list. Auth modes: `dev_header` (default) and `jwt`.

## Connections

- Hub: [[Architecture]]
- Related: [[fastapi-decision]], [[voice-service]]
