#!/usr/bin/env bash
#
# Build (and optionally run) the SENA AI docker stack with a clean cache.
#
# Workflow:
#   1. activate the ai-sena Python venv
#   2. clear caches BEFORE the build
#   3. docker compose build
#   4. clear cache + temp AFTER the build (reclaim disk)
#   5. start the stack (skip with --no-up)
#
# Usage (run from the repo root, where ai-sena/ and services/ live):
#   ./build.sh                 # full clean build + start detached
#   ./build.sh --no-up         # build only, don't start
#   ./build.sh --no-cache      # also pass --no-cache to the image build
#
# SAFETY: this only prunes regenerable build cache and *dangling* (untagged)
# images. It never touches tagged images, named volumes, or running containers.
# (No `docker system prune -a`, no `volume prune` — your DB/redis data is safe.)

set -euo pipefail

# Always run from the directory this script lives in (the repo root).
cd "$(dirname "$0")"

COMPOSE="docker compose -f services/docker-compose.deploy.yml"
BUILD_ARGS=""
DO_UP=1
for arg in "$@"; do
  case "$arg" in
    --no-up)    DO_UP=0 ;;
    --no-cache) BUILD_ARGS="--no-cache" ;;
  esac
done

clear_cache() {
  echo "› clearing docker build cache + dangling images…"
  docker builder prune -f   >/dev/null 2>&1 || true   # regenerable build-layer cache
  docker image   prune -f   >/dev/null 2>&1 || true   # dangling (untagged) images only
}

clear_temp() {
  echo "› clearing host pycache + pip/tmp leftovers…"
  find services -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
  find services -type f -name '*.pyc' -delete                      2>/dev/null || true
  rm -rf /tmp/pip-* /tmp/tmp* 2>/dev/null || true
}

# ── 1. Activate the Python venv ───────────────────────────────────────────
if [ -f ai-sena/bin/activate ]; then
  # shellcheck disable=SC1091
  source ai-sena/bin/activate
  echo "✓ venv active: $(command -v python)"
else
  echo "⚠ ai-sena/bin/activate not found — continuing without venv"
fi

# ── 2. Clear caches BEFORE build ──────────────────────────────────────────
clear_cache

# ── 3. Build ──────────────────────────────────────────────────────────────
echo "› building images${BUILD_ARGS:+ ($BUILD_ARGS)}…"
$COMPOSE build $BUILD_ARGS

# ── 4. Clear cache + temp AFTER build ─────────────────────────────────────
clear_cache
clear_temp

# ── 5. Start the stack (unless --no-up) ───────────────────────────────────
if [ "$DO_UP" -eq 1 ]; then
  echo "› starting stack…"
  $COMPOSE up -d
  $COMPOSE ps
fi

echo "✓ done."
