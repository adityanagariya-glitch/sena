---
paths:
  - "sena-ai/services/voice/**/*.py"
  - "sena-ai/services/voice/pyproject.toml"
  - "sena-ai/services/voice/Dockerfile"
---

# Voice Service (Flow B) — case note dictation (port 8082)

Layered architecture at `sena-ai/services/voice/src/voice/`. Primary active service for Flow B case note dictation via AWS Bedrock + LiveKit.

## Layer map

| Layer | Path | Purpose |
|-------|------|---------|
| API | `api/routes.py` | FastAPI endpoints, request orchestration |
| API | `api/deps.py` | DI (DB sessions, Redis client) |
| Services | `services/` | Business logic — dictation, approval, personal details, auth, transcription, Bedrock LLM, LiveKit, Redis state, SNS events |
| Repositories | `repositories/voice_repo.py` | DB queries via SQLAlchemy async |
| Models | `models/db.py` | SQLAlchemy ORM entities |
| Models | `models/schemas.py` | Pydantic request/response models |
| Prompts | `prompts/` | LLM prompt templates for dictation + personal details |
| Config | `core/settings.py` | Pydantic-settings with `SENA_AI_` env prefix |

## Key API routes (all require auth)
- `POST /v1/voice/session` — start dictation session (creates LiveKit token)
- `POST /v1/voice/session/turn` — process voice turn (transcript → Bedrock → draft update)
- `POST /v1/voice/session/end` — compile case note, create approval item, publish SNS event
- `GET /v1/voice/session/{id}` — session status
- `POST /v1/voice/personal-details/session[/turn|/end]` — parallel personal details flow (uses Gemini Live, NOT Bedrock)
- `POST /v1/approval/decision` — approve/reject case note (manager/admin only)
- `GET /health/live`, `GET /health/ready`

## External dependencies
- **AWS Bedrock** (Claude 3.5 Sonnet) — LLM for case note generation
- **AWS SNS** — case note lifecycle events
- **LiveKit** — real-time voice conferencing
- **Redis** — session state, rate limiting, locks
- **PostgreSQL + pgvector** (ai-db, port 5433) — voice session + case note data
- **PostgreSQL** (shared-db, port 5434) — cross-service platform data

## Run
```bash
cd sena-ai/services/voice
uvicorn src.voice.main:create_app --factory --reload --port 8082
```

## Env vars (`SENA_AI_` prefix)
`BEDROCK_MODEL_ID` (Claude 3.5 Sonnet), `LIVEKIT_*`, `SNS_TOPIC_ARN`, `AUTH_MODE` (`dev_header` or `jwt`)

## LLM split awareness
| Flow | Provider | Model | Env var |
|------|----------|-------|---------|
| Flow B case note dictation | AWS Bedrock | Claude 3.5 Sonnet | `SENA_AI_BEDROCK_MODEL_ID` |
| Personal details voice (Live API) | Google Gemini Live | `gemini-3.1-flash-live-preview` | `SENA_AI_GEMINI_API_KEY` + `SENA_AI_GEMINI_LIVE_MODEL_ID` |

Personal-details flow uses Gemini Live — `rules/gemini.md` applies when editing those files.
