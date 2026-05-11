# `.claude/plugins/` — Plugins Directory

## Status: empty by design

This directory exists for symmetry with the canonical Claude Code 2026 layout but contains no SENA-authored plugins. The reasons:

### 1. SENA's "agent pipeline" lives in `.claude/agents/`, not as a plugin

The 9-agent SENA pipeline (`sena-planner` → `sena-task-breaker` → `sena-implementer` → `sena-business-reviewer` → `sena-security-reviewer` → `sena-bug-fixer` → `sena-optimization-reviewer` → `sena-cleaner` → `sena-git-committer`) is exposed via standard subagents with YAML frontmatter. They are loaded by the Task tool directly. Packaging them as a plugin would add an indirection without changing functionality.

### 2. External plugins are already installed

SENA's session uses these third-party plugins (loaded from `~/.claude/plugins/` or the plugin marketplace, NOT from this directory):

| Plugin | Provides |
|--------|----------|
| `aws-serverless` | SAM/CDK guidance, Lambda Durable Functions, API Gateway skills |
| `deploy-on-aws` | AWS pricing tools, IaC validation, architecture diagrams |
| `context-mode` | Sandboxed command execution, knowledge-base indexing |
| `firecrawl` | Web scraping + Skill generation from docs URLs |
| `codex` | Codex CLI rescue + result handling |
| `obsidian` | Markdown/Canvas/Bases skills |
| `caveman` | Ultra-compressed communication mode |
| `taskmaster` | Task orchestration subagents |
| `code-review` | Generic PR review skill |

These are loaded from the user's global plugin directory, not from this project. The project-local `.mcp.json` lists MCP server entries separately.

## When to add a SENA plugin here

Create a SENA-authored plugin in this directory if and only if:

1. Multiple SENA-internal projects need the same agent/skill/command bundle, AND
2. The bundle is too project-specific for the global plugin marketplace, AND
3. The team agrees to maintain the plugin separately from the SENA monorepo's agent tree.

If any of those fails, keep the agent/skill/command as a flat file in `.claude/agents/`, `.claude/skills/`, or `.claude/commands/` respectively.

## Naming convention (if/when one is added)

```
.claude/plugins/<plugin-name>/
├── plugin.json       # plugin manifest
├── agents/           # agents this plugin contributes
├── skills/           # skills this plugin contributes
├── commands/         # slash commands this plugin contributes
└── README.md         # human-facing docs
```

Invocation is then `/plugin-name:command-name`.

## See also

- `.claude/agents/` — the actual SENA agent pipeline
- `.claude/skills/` — `commit-push-pr`, `review-pr`
- `.mcp.json` (project root) — MCP server registry
- `~/.claude/plugins/` — globally-installed plugins (out of scope for this repo)
