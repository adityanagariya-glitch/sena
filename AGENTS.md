# AGENTS.md

Guidance for agentic coding agents working in `C:\Users\Admin\Downloads\SENA`.

## Scope

- This repository root contains planning/docs plus one Python monorepo in `sena-ai/`.
- Treat `sena-ai/services/voice/` as the primary active service.
- Treat `sena-ai/services/ocr/` as scaffolded unless the task explicitly targets it.
- Prefer repository-local facts over generic FastAPI or Python defaults.

## Planning Source Of Truth

- Read `.planning/PROJECT.md`, `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`, and `.planning/STATE.md` before making architectural decisions.
- These `.planning/` files describe the intended future state more accurately than the current legacy implementation.
- Current planning status:
  - Project: `SENA Voice Assistant - LiveKit + Gemini Live Overhaul`
  - Current focus: Phase 1, `LiveKit Agents + Gemini Live Foundation`
  - Overall roadmap status: 0/9 phases complete, no phase plan started yet

## Strategic Direction From `.planning/`

- Treat this as a brownfield migration, not a greenfield rewrite.
- The current HTTP turn-based voice flow is legacy and is planned to be replaced by a persistent LiveKit Agent conversation model.
- FastAPI remains for session lifecycle and approval endpoints, but conversation handling is intended to move to agent processes.
- Server-mediated audio is non-negotiable: audio must transit SENA infrastructure, never client-direct to Gemini.
- The roadmap assumes dual voice experiences:
  - onboarding/personal-details agent
  - dictation/case-note agent
- A Level 2 fallback stack is part of the intended production design: Deepgram + Claude Sonnet + ElevenLabs.

## Preserve And Extend

- Prefer extending these files over replacing them:
  - `sena-ai/services/voice/src/voice/repositories/voice_repo.py`
  - `sena-ai/services/voice/src/voice/models/db.py`
  - `sena-ai/services/voice/src/voice/services/redis_service.py`
  - `sena-ai/services/voice/src/voice/services/approval_service.py`
  - `sena-ai/services/voice/src/voice/services/event_service.py`
  - `sena-ai/services/voice/src/voice/services/auth_service.py`
- If a task touches architecture, check that it still fits the `.planning/ROADMAP.md` phase goals and success criteria.

## Product Context

- SENA is an AI/ML backend for Australian NDIS service providers.
- This repo covers the AI backend layer, not the full product platform.
- Critical constraints:
  - Multi-tenant isolation is mandatory.
  - Human approval is required before AI output becomes final.
  - Data residency is Australian (`ap-southeast-2`).
  - NDIS compliance matters more than speed or convenience.

## Repo Layout

```text
SENA/
|- AGENTS.md
|- CLAUDE.md
|- sena-ai/
|  |- .env.example
|  |- docker-compose.yml
|  |- pyproject.toml
|  |- shared/
|  `- services/
|     |- voice/
|     |  |- src/voice/
|     |  `- tests/
|     `- ocr/
```

Key voice directories:

- `sena-ai/services/voice/src/voice/api/`: FastAPI routes and dependencies.
- `sena-ai/services/voice/src/voice/services/`: business logic and provider integrations.
- `sena-ai/services/voice/src/voice/repositories/`: SQLAlchemy query layer.
- `sena-ai/services/voice/src/voice/models/`: ORM models and Pydantic schemas.
- `sena-ai/services/voice/src/voice/core/`: settings and logging.
- `sena-ai/services/voice/tests/`: API-oriented tests using `TestClient`.

## Rule Files

- No Cursor rules were found in `.cursor/rules/` or `.cursorrules`.
- No Copilot instruction file was found at `.github/copilot-instructions.md`.
- Do not claim extra editor-specific rules exist unless they are added later.

## Environment And Setup

Run commands from `sena-ai/` unless noted otherwise.

```powershell
cd sena-ai
python -m pip install -U pip
pip install -e "services/voice[dev]"
Copy-Item .env.example .env
docker-compose up -d
```

Notes:

- The old root command `pip install -e ".[dev]"` is stale. The workspace root has no `dev` extra.
- CI installs `services/voice[dev]` directly; prefer matching CI.
- If you need shared package work, inspect `sena-ai/shared/pyproject.toml` and install `-e shared` explicitly.

## Run Commands

Start the active service from `sena-ai/services/voice/`:

```powershell
cd sena-ai/services/voice
uvicorn src.voice.main:create_app --factory --reload --port 8082
```

Useful local files:

- `sena-ai/.env.example`: canonical environment variable list.
- `sena-ai/services/voice/src/voice/core/settings.py`: runtime settings.
- `sena-ai/.github/workflows/voice-service-ci-cd.yml`: CI source of truth for lint and test commands.
- `.planning/ROADMAP.md`: target architecture and phase-by-phase success criteria.
- `.planning/STATE.md`: current project position and locked decisions.

## Test Commands

Prefer explicit path-based commands for `voice`.

```powershell
cd sena-ai
pytest -q services/voice/tests
pytest -q services/voice/tests/test_session_start.py
pytest -q services/voice/tests/test_session_start.py::test_start_session_success
pytest -q services/voice/tests -k "start_session_success"
pytest -vv services/voice/tests/test_session_start.py::test_start_session_success
pytest --cov=services/voice/src/voice --cov-report=term-missing services/voice/tests
```

Important test gotcha:

- Root `pyproject.toml` sets `testpaths` to `shared/tests`, `services/ocr/tests`, and `services/rag/tests`.
- Because `services/voice/tests` is not in `testpaths`, plain `pytest` from `sena-ai/` is not a reliable way to run voice tests.
- For single-test work, always pass the file path, and use `::test_name` when you want one test only.

## Lint, Format, And Type Check

Use the same paths CI uses:

```powershell
cd sena-ai
ruff check services/voice/src services/voice/tests
ruff check --fix services/voice/src services/voice/tests
ruff format services/voice/src services/voice/tests
ruff format --check services/voice/src services/voice/tests
mypy services/voice/src/voice
```

CI currently runs:

- `ruff check services/voice/src services/voice/tests`
- `pytest -q services/voice/tests`

## Code Style

### Python, Formatting, And Imports

- Target Python is 3.12.
- Ruff line length is 100.
- Enabled Ruff rule families: `E`, `F`, `I`, `N`, `UP`, `B`, `SIM`, `TCH`.
- Use `from __future__ import annotations` at the top of new source files.
- Group imports as stdlib, third-party, first-party, separated by blank lines.
- Prefer absolute imports from the package root:
  - `from voice.services.dictation_service import DictationService`
  - `from voice.models.schemas import StartSessionRequest`
- Within shared code, use `from sena_common...`.

### Naming And Types

- Classes: `PascalCase`.
- Functions, methods, variables: `snake_case`.
- Constants: `UPPER_SNAKE`.
- Use return annotations on functions and methods.
- Prefer `UUID`, `datetime`, `Literal[...]`, and concrete container types like `list[str]`.
- Use `Field(...)` for validation constraints and defaults in Pydantic models.
- Use `field_validator` for cross-field or conditional validation.

### FastAPI And Async Patterns

- API handlers use dependency injection with `Depends(...)`.
- Database access uses `AsyncSession`.
- Session factories are created with `async_sessionmaker(..., expire_on_commit=False)`.
- Repositories perform queries and mutations; they do not commit transactions.
- Route handlers or orchestration layers commit explicitly with `await ai_db.commit()` or `await shared_db.commit()`.
- Use timezone-aware timestamps, typically `datetime.now(timezone.utc)`.

### SQLAlchemy Patterns

- ORM models use SQLAlchemy 2 style annotations with `Mapped[...]` and `mapped_column(...)`.
- UUID primary keys are standard across voice models.
- JSON columns are used for draft state, section coverage, and event payloads.
- Favor explicit status fields such as `ACTIVE`, `COMPLETED`, `PENDING_APPROVAL`, `DELIVERED`.

### Error Handling

- Use `HTTPException` with explicit `status_code` and concise `detail`.
- Raise `401` for missing or invalid auth material.
- Raise `403` for role violations.
- Raise `404` for missing entities.
- Raise `409` for invalid lifecycle state, duplicate activity, or already-completed flows.
- Use `ValueError` inside Pydantic validators, not inside route logic.

## Testing Conventions

- Voice tests are in `sena-ai/services/voice/tests/`.
- Tests use `fastapi.testclient.TestClient` via fixtures in `conftest.py`.
- `conftest.py` seeds default env vars with `os.environ.setdefault(...)`.
- Dev-mode auth headers used by tests are:
  - `X-Tenant-ID`
  - `X-User-ID`
  - `X-User-Role`
  - `X-Staff-ID`
- When adding endpoint tests, mirror existing request shapes and auth fixtures.

## Configuration Conventions

- Settings use `pydantic-settings` with `env_prefix="SENA_AI_"`.
- Environment variables are mapped with `Field(..., alias="...")`.
- Auth mode is controlled by `SENA_AI_AUTH_MODE` and supports:
  - `dev_header`
  - `jwt`

## Agent Guidance

- Default to the `voice` service unless the task clearly targets another area.
- Check whether a file is real executable code or only a comment stub before building on it.
- Keep tenant isolation, approval gates, and auditability intact when changing flows.
- Match local commands to CI when possible.
- For architecture work, align with `.planning/` before aligning with the current HTTP implementation.
- If you change tests or tooling instructions, update this file if the guidance becomes stale.

## Ignored Folders

**NEVER** try to read or analyze anything inside the `/archive`, `.venv`, or `.vscode` folders. They are a massive token consumption disaster and are likely useless for your analysis. Pretend they do not exist unless explicitly instructed by the user to restore something.
