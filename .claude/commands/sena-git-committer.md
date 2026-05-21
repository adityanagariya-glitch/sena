---
description: Direct invocation of @agent-sena-git-committer — generates Conventional Commit + git add command. NEVER pushes.
allowed-tools: Agent
---

Route the staged changeset to `sena-git-committer` (Agent tool, subagent_type: sena-git-committer). Returns: `git add <specific paths>` + `git commit -m "<conventional commit message>"`. **NEVER pushes.** User runs the commands manually.

Prerequisite: `@agent-sena-cleaner` must have returned STATUS: CLEAN before this fires. Commit format: `type(scope): subject` (feat/fix/refactor/test/docs/chore).

User's args: $ARGUMENTS
