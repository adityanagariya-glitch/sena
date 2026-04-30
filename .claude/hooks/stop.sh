#!/usr/bin/env bash
# stop.sh — Stop hook
# Fires when Claude stops (including /clear, /compact, resume boundaries).
# Rebuilds graphify knowledge graph at every graphify-out it finds, then emits
# session-boundary reminder.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

# Candidate graph roots: this repo, and the parent dir (SENA outer copy).
# A root counts if it contains a graphify-out/ directory.
rebuild_graph() {
    local root="$1"
    [[ -d "$root/graphify-out" ]] || return 0
    command -v python >/dev/null 2>&1 || return 0
    (
        cd "$root" && \
        python -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))" \
            >/dev/null 2>&1
    ) || true
}

rebuild_graph "$REPO_ROOT"
rebuild_graph "$(dirname "$REPO_ROOT")"

cat <<'JSON'
{"systemMessage":"Session boundary. Verify .claude/tasks/TASKS.md reflects task status changes from this session. Stop hook rebuilt graphify knowledge graph(s)."}
JSON

exit 0
