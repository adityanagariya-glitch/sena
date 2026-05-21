---
paths:
  - "sena-ai/demo_live_server.py"
  - "sena-ai/demo_client.html"
---

# Demo Stack — standalone Gemini Live testbed

Separate from the production voice service. Used for Gemini Live regression debugging.

## Files
- `sena-ai/demo_live_server.py` — FastAPI server bridging browser WebSocket ↔ Gemini Live
- `sena-ai/demo_client.html` — browser UI with mic capture + audio playback + file upload mode

## Run
```bash
cd sena-ai
uvicorn demo_live_server:app --reload --port 8082
```

## Env required
- `SENA_AI_GEMINI_API_KEY`
- `SENA_AI_GEMINI_LIVE_MODEL_ID`

## Hook gating

Edits to `demo_live*` files are blocked by `pre-tool-use.sh` until both `skills-gemini.flag` and `ctx7-gemini.flag` are set (same gate as production Gemini code). See `rules/gemini.md` for the pre-coding prerequisites.
