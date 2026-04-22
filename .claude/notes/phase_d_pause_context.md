---
title: Phase D Pause Context
updated: 2026-04-22
---

# Env State At Pause
- Branch: `dev` (clean, matches origin)
- HEAD: `4f4250b`
- Services running: none
- Docker: unknown (check `docker-compose ps`)
- Last test run: 2026-04-21, 48/48 passing (Phase C)
- `pip install -e .` previously done in `services/onboarding/`

# Architectural Context Held
- Onboarding service src-layout requires editable install
- WS = one session per onboarding step (clean resume)
- Voice holds write lock; app PUTs blocked during WS
- Gemini model: `gemini-3.1-flash-live-preview` (only supported)
- `START_SENSITIVITY_LOW` mandatory — HIGH dies on ambient noise
- Never gate mic on `_agent_speaking` — kills VAD after 2-4 turns

# Known Traps
- Proactive audio unsupported — user must speak first
- `session.receive()` returns per-turn → must wrap `while True: ... continue`
- Old API `LiveClientRealtimeInput` forbidden
