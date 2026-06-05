# Reality-Check Senior — Claude Code Agent

A brutally honest Principal ML Engineer mentor, built as a complete Claude Code configuration (skills + output style + hooks + MCP servers).

This is the upgrade of the original `Reality-Check Senior` system prompt. Instead of stuffing everything into one giant prompt, the agent is split across Claude Code's native primitives — which costs ~5k tokens fixed overhead vs. the ~15–20k of monolithic-prompt designs, while being more maintainable and version-controlled.

---

## What you get

- **The persona** as an output style → loads automatically every turn, but stays small (~400 tokens).
- **Ten slash commands** as skills → only the metadata loads in context (~100 tokens each); the body loads only when the command fires.
- **A shared AI/ML lint checklist** → defined once, used by `/review` and `/roast` — no duplication.
- **Five MCPs** → Context7 for live library docs, Playwright for real web/arxiv browsing, GitHub for real PRs, HuggingFace for models/datasets/papers, Sequential Thinking for structured deliberation.
- **Hooks** → ruff/mypy auto-run after every file edit, destructive commands blocked on `data/` and `checkpoints/`.
- **Progressive-disclosure docs** → CLAUDE.md is lean (<200 lines); depth lives in `docs/*.md` and is loaded only when relevant.

---

## Structure

```
.
├── CLAUDE.md                          # Lean project map; persona is NOT here
├── .mcp.json                          # The five MCPs
├── .claude/
│   ├── settings.json                  # Hooks + output-style activation
│   ├── output-styles/
│   │   └── reality-check.md           # The persona (loads every turn, small)
│   ├── skills/
│   │   ├── _shared/lints.md           # AI/ML checklist — single source of truth
│   │   ├── review/SKILL.md            # /review
│   │   ├── roast/SKILL.md             # /roast (same lints, harsher tone)
│   │   ├── brainstorm/SKILL.md        # /brainstorm
│   │   ├── approve/SKILL.md           # /approve
│   │   ├── explain/SKILL.md           # /explain
│   │   ├── debug/SKILL.md             # /debug
│   │   ├── tradeoffs/SKILL.md         # /tradeoffs
│   │   ├── postmortem/SKILL.md        # /postmortem
│   │   ├── career/SKILL.md            # /career
│   │   └── help/SKILL.md              # /help
│   └── hooks/
│       └── block-destructive.sh       # Pre-bash hook
└── docs/                              # Progressive disclosure (loaded on demand)
    ├── data.md
    ├── training.md
    ├── llm-stack.md
    └── evals.md
```

---

## Installation

### 1. Drop the config into a project

```bash
# From this directory, into your ML project root:
cp -r CLAUDE.md .mcp.json .claude/ docs/ /path/to/your/ml-project/
cd /path/to/your/ml-project/
```

### 2. Set environment variables

```bash
export CONTEXT7_API_KEY="..."      # https://context7.com — free tier exists
export GITHUB_PAT="ghp_..."         # GitHub fine-grained PAT with repo + PR scope
export HF_TOKEN="hf_..."            # huggingface.co/settings/tokens
```

### 3. Make sure hooks are executable

```bash
chmod +x .claude/hooks/*.sh
```

### 4. Open Claude Code in the project

```bash
claude  # or `claude --dangerously-skip-permissions` if you trust the setup
```

Claude Code will:
- Detect `.mcp.json` and prompt to enable the MCP servers (approve them once per project).
- Detect `.claude/settings.json` and apply the output style + hooks.
- Detect `.claude/skills/` and register the slash commands.

### 5. Verify

In the Claude Code session:

```
/output-style                      # confirm "Reality-Check Senior" is active
/help                              # should list all 10 commands
```

Try: *"Use context7 to show me the current transformers.Trainer signature."*

If that works, the agent is wired up.

---

## How to use it

| You're doing this | Run this |
|---|---|
| Reviewing a PR or diff | `/review <PR url>` or `/review` for current diff |
| Want a no-mercy teardown | `/roast <target>` |
| Designing something, stuck | `/brainstorm <problem>` — agent will ask 3 questions first |
| Asking for sign-off before merge | `/approve` — agent defaults to deny |
| Need to learn a concept/library | `/explain <thing>` |
| Bug, error, training failure | `/debug <symptom>` |
| Comparing options | `/tradeoffs A vs B for <use case>` |
| Something broke in prod | `/postmortem <incident>` |
| Career question | `/career <question>` |
| Lost | `/help` |

**Pro tip:** for `/review` and `/tradeoffs`, press `Shift+Tab` twice to enter **Plan Mode** first. The agent will explore read-only via the Haiku-powered Explore subagent, then come back with a plan. Type `proceed` to act on it.

---

## Customizing for your project

1. **Edit `CLAUDE.md`** — fill in the placeholders (`<YOUR PROJECT NAME>`, stack, conventions). This is the single most impactful customization.
2. **Edit `_shared/lints.md`** — add project-specific lints (e.g., "all training scripts must call `wandb.init(project='your-project')`"). The agent will enforce them.
3. **Edit `docs/*.md`** — replace the placeholder content with your actual conventions. Or delete files you don't need.
4. **Edit `block-destructive.sh`** — add patterns specific to your project.

---

## Design rationale (why this shape, not a giant prompt)

- **Persona in output style:** the official Claude Code docs explicitly recommend output styles for "when you keep re-prompting for the same voice." That's exactly this use case.
- **Skills over slash commands:** Anthropic merged commands into skills in Jan 2026; skills load only metadata until invoked (Anthropic cookbook: ~98% context savings vs. inlining everything).
- **Hooks for non-negotiables:** CLAUDE.md compliance studies (Jaroslawicz 2026) show ~76-80% adherence for short rule sets, dropping to 52% beyond 14 rules. Hooks run every time. Quality gates belong in hooks.
- **MCPs for ground truth:** library APIs and paper claims change. Training data goes stale. Context7 + Playwright + GitHub + HuggingFace eliminate the bulk of hallucinated API recommendations.
- **Shared lints file:** `/review` and `/roast` apply the same checks with different tone. Duplicating them across SKILL.md files is the kind of thing the agent would `/roast` you for.

---

## What this deliberately does NOT include

- **Persona backstory.** Adds tokens, zero quality lift.
- **Memory/knowledge-graph MCPs.** The ecosystem isn't stable; CLAUDE.md + skills cover stable memory.
- **Brave/web-search MCP.** Playwright + Context7 + HuggingFace cover the relevant search needs.
- **"Constitutional self-check" recited every turn.** Token-expensive; verification is baked into specific skill bodies instead.
- **Long lists of "do not" rules in the prompt.** Negative prompting can backfire — moved to hooks where possible.

---

## Caveats (from the research)

- **Sycophancy is partially a model property.** Even with strong prompting, expect ~10–20% residual sycophancy on adversarial prompts. The output style + verification gates are necessary; neither alone is sufficient.
- **Playwright MCP first-run gotcha:** the first time, you may need to explicitly say "use playwright mcp" or Claude tries Bash. Baked into the relevant SKILL.md files.
- **Context7 quality varies by library.** Authoritative for popular libraries (PyTorch, transformers, LangChain, scikit-learn). For long-tail libraries, verify via Playwright.
- **CLAUDE.md is advisory, hooks are mandatory.** Use hooks for invariants ("never push to main"), CLAUDE.md for rules of thumb.

---

## Updating the agent

Treat this like any other code:
- Add a new lint? Edit `_shared/lints.md`, commit.
- Add a new command? Create `.claude/skills/<name>/SKILL.md`, commit.
- Find the agent missing things? Add to the eval set in `evals/` and tune the relevant skill.

This is eval-driven prompt development. The agent should be measurably better over time — and you should be able to see why in the git log.
