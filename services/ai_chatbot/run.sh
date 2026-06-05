#!/usr/bin/env bash
# Launch the ai_chatbot gateway. It serves the shell UI and (by default) also
# spawns + health-checks the Staff Streamlit, Policy Streamlit, and Policy API.
#
# Override anything via env, e.g.:
#   GATEWAY_PORT=9100 MANAGE_CHILDREN=false ./run.sh
set -euo pipefail
cd "$(dirname "$0")"

exec uvicorn gateway:app \
  --host "${GATEWAY_HOST:-0.0.0.0}" \
  --port "${GATEWAY_PORT:-9000}"
