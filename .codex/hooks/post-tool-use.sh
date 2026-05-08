#!/usr/bin/env bash
# post-tool-use.sh — PostToolUse hook
# Triggered after Write, Edit, NotebookEdit, Bash tool calls
# Maintains per-service requirements.txt using pipreqs

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SERVICES_DIR="$REPO_ROOT/sena-ai/services"

# Read hook event JSON from stdin (required — Claude Code sends it)
EVENT=$(cat 2>/dev/null || true)

# Only run pipreqs if the event touched a Python file
if ! echo "$EVENT" | grep -q '\.py'; then
    exit 0
fi

# Activate .venv if present — check service-level then repo root
# This ensures pipreqs reports versions from the venv, not system Python
VENV_ACTIVATED=0
for venv_candidate in "$REPO_ROOT/sena-ai/.venv" "$REPO_ROOT/.venv"; do
    activate="$venv_candidate/Scripts/activate"          # Windows
    [[ -f "$activate" ]] || activate="$venv_candidate/bin/activate"  # Unix
    if [[ -f "$activate" ]]; then
        # shellcheck disable=SC1090
        source "$activate"
        VENV_ACTIVATED=1
        break
    fi
done

# Resolve pipreqs — venv first, then PATH, then Python user scripts dir (Windows)
if command -v pipreqs &>/dev/null; then
    PIPREQS="pipreqs"
else
    PIPREQS=$(python -c "
import sysconfig, os
for scheme in ('nt_user', 'posix_user', ''):
    try:
        p = sysconfig.get_path('scripts', scheme) if scheme else sysconfig.get_path('scripts')
        exe = os.path.join(p, 'pipreqs.exe' if os.name == 'nt' else 'pipreqs')
        if os.path.exists(exe):
            print(exe)
            break
    except Exception:
        pass
" 2>/dev/null)
    [[ -z "$PIPREQS" ]] && exit 0
fi

# Run pipreqs for each service subdirectory
for service_dir in "$SERVICES_DIR"/*/; do
    [[ -d "$service_dir" ]] || continue

    src_dir="${service_dir}src"
    [[ -d "$src_dir" ]] || continue

    # Only run if the service has at least one Python file
    if find "$src_dir" -name "*.py" -print -quit 2>/dev/null | grep -q .; then
        $PIPREQS --force --savepath "${service_dir}requirements.txt" "$src_dir" 2>/dev/null || true
    fi
done

exit 0
