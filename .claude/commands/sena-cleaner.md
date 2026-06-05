---
description: Direct invocation of @agent-sena-cleaner — final lint + artifact gate before commit (ruff/mypy, dead code, debug prints). FIXES inline.
allowed-tools: Agent
---

Route the staged changeset to `sena-cleaner` (Agent tool, subagent_type: sena-cleaner). Runs ruff check + format, mypy on touched modules, greps for `print(`/`breakpoint()`/`pdb`/`TODO without ticket`. **Fixes inline** for low-risk findings. STATUS: CLEAN required before `@agent-sena-git-committer` runs.

User's args (path or "all staged"): $ARGUMENTS
