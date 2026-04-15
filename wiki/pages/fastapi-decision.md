---
title: FastAPI Decision
type: decision
tags: [framework, python, decided]
sources: ["[[src-technical-decisions]]"]
created: 2026-04-15
updated: 2026-04-15
---

# FastAPI Decision

**Status:** DECIDED

Python + FastAPI is the framework for all SENA AI/ML backend services.

## Why Python

- The AI/ML ecosystem is Python-first (tokenizers, model SDKs, vector libraries, evaluation tools)
- Team is comfortable with Python
- No compelling Go/Rust/Node reason when the hot path is LLM inference (not CPU-bound)

## Why FastAPI

- **Async-first** — matches SENA's async-first code style (AsyncSession, async services)
- **Pydantic integration** — request/response models + settings (`pydantic-settings` with `SENA_AI_` env prefix)
- **OpenAPI out of the box** — helpful when client-team contracts eventually get defined
- **Minimal boilerplate** — ship fast with a 2-person team

## Rejected alternatives

- Flask / Django — sync-first, doesn't fit LLM workload
- Starlette raw — FastAPI already gives us the Pydantic-flavoured Starlette on top
- Node/Express — loses the AI ecosystem

## Pinned conventions

- Python 3.12+
- Line length 100
- Ruff linting (E, F, I, N, UP, B, SIM, TCH)
- mypy strict with Pydantic plugin
- Settings via `pydantic-settings`, env prefix `SENA_AI_`

## Connections

- Hub: [[Architecture]]
- Source: [[src-technical-decisions]]
- Related: [[monorepo-structure]]
