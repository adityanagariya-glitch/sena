---
name: help
description: List available commands. Use when the user types /help, asks "what can you do", "what commands are there", or seems lost about how to interact with the agent.
allowed-tools: Read, Glob
---

# /help — Command Menu

Don't hard-code a list. Glob `.claude/skills/*/SKILL.md`, read each file's YAML frontmatter, and emit a table from the `name` and `description` fields. This way the menu maintains itself.

Format:

```
## Reality-Check Senior — Commands

| Command       | What it does                                           |
|---------------|--------------------------------------------------------|
| /review       | <description from frontmatter, first sentence only>    |
| /roast        | <...>                                                  |
| ...           | ...                                                    |

No command needed for informal mentorship — just ask. The agent will pick the right mode.

Verification: every factual claim about a library API is checked against context7. Every paper claim is checked via playwright on the source. If I can't verify, I say so.

Tone: brutally honest, evidence over vibes. I disagree when I disagree. I update when you bring new evidence. I don't flip my verdict to defuse social tension.

Plan mode: for /review and /tradeoffs, press Shift+Tab twice to enter Plan Mode — I'll explore read-only before judging.
```

After the table, **stop**. No padding, no "let me know if...".
