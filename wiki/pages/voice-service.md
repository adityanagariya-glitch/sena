---
title: Voice Service
type: topic
tags: [voice, service, flow-b, core]
sources: ["[[src-flow-b]]", "[[src-architecture-audit]]", "[[src-new-plan]]"]
created: 2026-04-15
updated: 2026-04-15
---

# Voice Service

The primary active service at `sena-ai/services/voice/`. Handles [[flow-b-voice-dictation]] (case note dictation) and a parallel personal-details flow.

## Layered architecture

Under `sena-ai/services/voice/src/voice/`:

| Layer | Path | Purpose |
|-------|------|---------|
| API | `api/routes.py` | FastAPI endpoints, request orchestration |
| API | `api/deps.py` | DI for DB session + Redis client |
| Services | `services/` | Business logic (dictation, approval, personal-details, auth, transcription, Bedrock, LiveKit, Redis state, SNS) |
| Repositories | `repositories/voice_repo.py` | All DB queries via async SQLAlchemy |
| Models | `models/db.py` | SQLAlchemy ORM entities |
| Models | `models/schemas.py` | Pydantic request/response models |
| Prompts | `prompts/` | LLM prompt templates |
| Config | `core/settings.py` | pydantic-settings, `SENA_AI_` env prefix |

`voice_repo.py` is a god node (26 edges per graphify) — this is by design: repository pattern concentrates all persistence in one place, behind a tenant-aware interface.

## Routes

- `POST /v1/voice/session` — start session, returns LiveKit token
- `POST /v1/voice/session/turn` — process a voice turn (transcript → Bedrock → draft update)
- `POST /v1/voice/session/end` — compile case note, create approval item, publish SNS
- `GET /v1/voice/session/{id}` — session status
- `POST /v1/voice/personal-details/session[/turn|/end]` — parallel personal details flow
- `POST /v1/approval/decision` — manager/admin approve or reject
- `GET /health/live`, `GET /health/ready`

## Current state vs planned

**Current:** HTTP turn-based (Approach A). Works end-to-end but has latency and UX shortcomings.

**Planned:** Migrate to [[approach-d-architecture]] with [[livekit]] Agents + [[gemini-live-decision]]. Introduce [[session-state-machine]], [[context-preloading]], [[degradation-ladder]].

## Connections

- Hub: [[Architecture]]
- Related: [[flow-b-voice-dictation]], [[approach-d-architecture]], [[session-state-machine]]
- Code graph: [graphify-out/GRAPH_REPORT.md](../../graphify-out/GRAPH_REPORT.md)
