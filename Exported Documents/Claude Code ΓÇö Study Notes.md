# Claude Code — Study Notes

> **Claude Code** is an agentic coding tool that reads your codebase, edits files, runs commands, and connects to external tools — all from your terminal, VS Code, JetBrains, or the Claude Desktop app.

---

## 1. Core Concepts

### What makes Claude Code different from [Claude.ai](http://Claude.ai)?

- Has **direct access** to your files, terminal, and codebase
- No copy-pasting — it does the work itself
- Operates as an **AI Agent**: software that interacts with its environment in a loop to complete goals

### The Agentic Loop

1. You enter a prompt
2. Claude gathers context (reads files, calls tools)
3. It takes action (edits a file, runs a command)
4. It verifies results
5. If done → waits for next prompt. If not → loops back and retries

### Context Window

- Claude's **working memory** — holds your conversation, file contents, command outputs
- When full, Claude **auto-compacts** (summarizes + removes unnecessary content)
- Manual commands: `/compact` (summarize and continue) · `/clear` (full reset) · `/context` (inspect usage)

---

## 2. Permissions & Modes

| **Mode**               | **Behavior**                                              |
| ---------------------- | --------------------------------------------------------- |
| **Approval** (default) | Asks before every file edit or command                    |
| **Auto-accept**        | File edits are automatic; commands still need approval    |
| **Plan Mode**          | Read-only — Claude builds a plan before touching any code |

## Toggle modes with `Shift + Tab`.

## 3. The Core Workflow: Explore → Plan → Code → Commit

> This is the single most important habit to build. Skipping straight to "write code" causes the most course-correcting.

### Explore

Use **Plan Mode** (`Shift + Tab`) — Claude reads files and researches without making changes.

### Plan

Claude produces a detailed plan of action. Review it. Course-correct *here* — before any code is written.

### Code

- Approve the plan → Claude executes
- Define a **success criteria** so Claude knows when it's done
- Attach a **test suite** Claude can validate against
- Use tools (e.g. Claude in Chrome) to reduce back-and-forth
- Save recurring fixes to `CLAUDE.md`

### Commit

1. Run a **subagent code review** (fresh eyes, no session bias)
2. Let Claude generate a commit message
3. Use `/commit-push-pr` to commit, push, and open a PR in one step
4. Resume PR work later with `claude --from-pr <PR_NUMBER>`

---

## 4. [CLAUDE.md](http://CLAUDE.md) — Persistent Project Memory

> Without a `CLAUDE.md`, Claude starts from scratch every session.
**What to put in it:**

```other
# Project
Next.js 15, App Router, Tailwind, Drizzle ORM

# Commands
- Dev: `pnpm dev`
- Tests: `pnpm test`
- Lint: `pnpm lint`

# Code Style
- 2-space indentation
- Named exports
- Server actions over API routes
```

**Key tips:**

- Commit it to version control — your whole team benefits
- Ask Claude to save corrections: *"Save this rule to [CLAUDE.md](http://CLAUDE.md)"*
- Reference docs with `@README.md` inside the file
- Start *without* one, then run `/init` once you know what Claude keeps getting wrong
- A **user-level** `CLAUDE.md` stores personal preferences across all projects

---

## 5. Context Management

**Why it matters:** Every file read, tool call, and message consumes context space.

| **Command** | **When to use**                                            |
| ----------- | ---------------------------------------------------------- |
| `/compact`  | Mid-feature, running low on space — keeps relevant history |
| `/clear`    | Starting a new feature — removes all session bias          |
| `/context`  | Check what's eating your context budget                    |

**Tips to save context:**

- Be **specific** with prompts — vague prompts force Claude to explore more
- Disable unused **MCP servers** (each loads tool definitions into context)
- Use **subagents** for research tasks — they run in a separate context window and return only a summary

---

## 6. Subagents

> Subagents run in parallel with their own isolated context window, then return a summary to your main agent.
**Use them for:**

- Codebase exploration ("where are the auth endpoints?")
- Unbiased code review before a PR
- Heavy research tasks you only need the result of

**Create one:** Run `/agents` → "Create new agent" → define purpose, tools, and scope.

**Best practices:**

- Code reviewers → restrict to **read-only tools**
- Check subagent configs into the repo so the whole team uses them
- Enable **persistent memory** for subagents you use repeatedly on the same project

---

## 7. MCP (Model Context Protocol)

> MCP connects Claude Code to external tools and data sources — databases, project management apps, documentation, etc.

```other
claude mcp add   # add a server
/mcp             # manage servers inside a session
```

**Server scopes:**

| **Scope** | **Where**                                                     |
| --------- | ------------------------------------------------------------- |
| Local     | Current project, just for you                                 |
| User      | All projects, just for you                                    |
| Project   | `.mcp.json` checked into version control — whole team gets it |

## **Watch out:** MCP servers load all tool definitions into context even when unused. If tools exceed **10% of your context window**, Claude switches to on-demand tool search (less reliable). Disable unused servers with `/mcp`.

## 8. Hooks

> Hooks are **deterministic** — unlike [CLAUDE.md](http://CLAUDE.md) instructions, they always run.
**Events:**
| Event | Fires when... |
| --- | --- |
| `PreToolUse` | Before a tool call — can **block** it |
| `PostToolUse` | After a tool call completes |
| `UserPromptSubmit` | When you submit a prompt |
| `Stop` | When Claude finishes responding |
**Exit codes for `PreToolUse` blocks:**

- `0` → proceed normally
- `2` → block + send stderr as feedback to Claude
- Other → non-blocking error shown to you

**Common uses:**

- Auto-format files after edits (PostToolUse)
- Block dangerous commands like `rm -rf` (PreToolUse)
- Block commits to `main`
- Send Slack notifications when Claude finishes (Stop)

## **Setup:** Run `/hooks` inside a session, or edit `.claude/settings.json` directly. Check into version control to share with your team.

## Key Takeaways

- **Always follow Explore → Plan → Code → Commit** — planning before coding saves the most time
- **[CLAUDE.md](http://CLAUDE.md) is your project's onboarding doc** — it eliminates repeated corrections
- **Context is finite** — use `/compact`, subagents, and specific prompts to protect it
- **Hooks enforce rules deterministically** — if it must always happen, use a hook, not a prompt
- **MCP connects Claude to the rest of your stack** — scope servers to `.mcp.json` for team sharing
- **Subagents keep your main context clean** — delegate exploration and review to them