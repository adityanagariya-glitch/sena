# AGENTS.md

Guidelines for agentic coding agents operating in the SENA AI/ML backend repository.

## Project Overview

SENA is an AI-powered multi-tenant SaaS platform for Australian NDIS service providers. This repo contains the **AI/ML backend layer only** - a Python monorepo with microservices. The active service is `voice` (case note dictation); `ocr` is scaffolded but not implemented.

**Hard constraints:**
- Multi-tenant data isolation (legally mandated via Row-Level Security)
- Human-in-the-loop approval for all AI outputs
- Australian data residency (ap-southeast-2)
- NDIS compliance

## Build & Run Commands

```bash
# Setup (from sena-ai/)
pip install -e ".[dev]"
cp .env.example .env

# Infrastructure
docker-compose up -d

# Run voice service
cd services/voice
uvicorn src.voice.main:create_app --factory --reload --port 8082
```

## Test Commands

```bash
# Run all tests (from sena-ai/)
pytest

# Run tests for specific service
pytest services/voice/tests/

# Run single test file
pytest services/voice/tests/test_session_start.py

# Run single test by name
pytest -k "test_start_session_success"

# Run with coverage
pytest --cov=src/voice --cov-report=term-missing

# Run specific test with verbose output
pytest services/voice/tests/test_session_start.py::test_start_session_success -v
```

## Lint & Format Commands

```bash
# Lint check (from sena-ai/)
ruff check src/

# Auto-fix lint issues
ruff check --fix src/

# Format code
ruff format src/

# Type check (strict mode)
mypy src/voice/

# Run all checks
ruff check src/ && ruff format --check src/ && mypy src/voice/
```

## Code Style

### Python Version & Formatting
- Python 3.12+
- Line length: 100 characters
- Ruff for linting (E, F, I, N, UP, B, SIM, TCH rules) and formatting
- mypy strict mode with Pydantic plugin

### Imports

```python
from __future__ import annotations  # Always first

# Standard library
from datetime import datetime, timezone
from uuid import UUID

# Third-party
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

# First-party (known-first-party: sena_common, ocr, rag)
from voice.models.schemas import StartSessionRequest
from voice.services.bedrock_service import BedrockService
```

- Use absolute imports from package root: `from voice.models.schemas import ...`
- Group imports: stdlib, third-party, first-party (separated by blank lines)
- Use `from __future__ import annotations` for all files

### Naming Conventions

| Type | Convention | Example |
|------|------------|---------|
| Classes | PascalCase | `DictationService`, `VoiceRepository` |
| Functions/Methods | snake_case | `process_turn()`, `get_session_by_id()` |
| Variables | snake_case | `session_id`, `transcript_confidence` |
| Constants | UPPER_SNAKE | `DEFAULT_SECTIONS`, `MAX_RETRIES` |
| Private methods | _leading_underscore | `_build_prompt()` |
| Pydantic models | PascalCase + suffix | `StartSessionRequest`, `TurnResponse` |

### Type Annotations

```python
# Always use return type annotation
async def get_session_by_id(self, db: AsyncSession, session_id: UUID) -> VoiceSession | None:

# Use Literal for constrained strings
decision: Literal["APPROVED", "REJECTED"]

# Use Field for validation
transcript_confidence: float = Field(ge=0.0, le=1.0)

# Optional with default
review_notes: str = ""
shared_case_note_id: UUID | None = None
```

### Async Patterns

- All DB operations use `AsyncSession`
- All services are async classes
- Use `await` for all async operations
- Commit transactions explicitly: `await ai_db.commit()`

### Error Handling

```python
from fastapi import HTTPException, status

# Use HTTPException with appropriate status codes
if session is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

if session.status != "ACTIVE":
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session not active")

# Validation errors in Pydantic
@field_validator("review_notes")
@classmethod
def reject_requires_reason(cls, value: str, info):
    decision = info.data.get("decision")
    if decision == "REJECTED" and not value.strip():
        raise ValueError("review_notes is required when decision is REJECTED")
    return value
```

### Pydantic Models

```python
from pydantic import BaseModel, Field

class TurnRequest(BaseModel):
    session_id: UUID
    transcript: str = Field(min_length=1)
    transcript_confidence: float = Field(ge=0.0, le=1.0)
    audio_duration_ms: int = Field(gt=0)
    sequence_number: int = Field(gt=0)
    timestamp: datetime
```

### Settings Configuration

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class VoiceSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="SENA_AI_",
        case_sensitive=False
    )

    service_name: str = Field(default="sena-voice", alias="SERVICE_NAME")
    ai_db_url: str = Field(alias="AI_DB_URL")
```

- All env vars use `SENA_AI_` prefix
- Use Field with alias for env var mapping

## Architecture

```
sena-ai/
├── services/
│   ├── voice/           # Active service
│   │   ├── src/voice/
│   │   │   ├── api/         # FastAPI routes, dependencies
│   │   │   ├── services/    # Business logic
│   │   │   ├── repositories/# DB queries
│   │   │   ├── models/      # SQLAlchemy ORM + Pydantic schemas
│   │   │   ├── prompts/     # LLM prompt templates
│   │   │   ├── core/        # Settings, logging
│   │   │   └── utils/       # Helpers
│   │   └── tests/
│   └── ocr/             # Scaffolded, not implemented
├── shared/              # sena-common library (DB, middleware)
└── docker-compose.yml   # Redis + 2x PostgreSQL
```

## Key Files to Reference

- `CLAUDE.md` - Full project documentation
- `sena-ai/pyproject.toml` - Workspace config, ruff/mypy/pytest settings
- `sena-ai/.env.example` - All environment variables
- `sena-ai/services/voice/src/voice/core/settings.py` - Settings class

## Pre-commit

```bash
pre-commit install
pre-commit run --all-files
```

## Authentication

Two modes via `SENA_AI_AUTH_MODE`:
- `dev_header` (default): reads `X-User-Id`, `X-User-Roles`, `X-Tenant-ID` headers
- `jwt`: validates JWT bearer tokens
