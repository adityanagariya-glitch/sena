# SENA AI — Agent Pipeline

8-agent automated development pipeline for the SENA AI monorepo.
Each agent has strict role boundaries and a defined input/output contract.

## Pipeline Flow

```
User Requirement
      │
      ▼
01-planner        → Architecture + compliance analysis
      │
      ▼
02-task-breaker   → JSON task list (one task per coding session)
      │
      ▼ (loop per task)
03-implementer    → Production Python code
      │
      ▼
04-business-logic-reviewer  → NDIS domain + contract verification
      │
      ▼
05-security-reviewer        → Tenant isolation + OWASP audit
      │
      ▼
06-optimization-reviewer    → Async + Redis efficiency
      │
      ▼
07-cleaner        → Lint gate + artifact removal
      │
      ▼
08-git-committer  → Semantic git add + commit (no push)
```

## Agent Files

| File | Role | Key focus |
|------|------|-----------|
| 01-planner.md | Lead Architect | Which services, data flow, compliance |
| 02-task-breaker.md | Technical PM | Atomic sequential JSON tasks |
| 03-implementer.md | Senior Developer | Async Python, Gemini Live, Redis, Pydantic v2 |
| 04-business-logic-reviewer.md | NDIS QA | NDIS rules, FormState contracts, tool return shapes |
| 05-security-reviewer.md | AppSec | Multi-tenant isolation, secrets, OWASP |
| 06-optimization-reviewer.md | Perf Engineer | Redis pipelines, async patterns, Gemini latency |
| 07-cleaner.md | Repo Maintainer | Ruff, mypy, dead code, PII in tests |
| 08-git-committer.md | VCS Manager | Conventional commits, never push |

## Automation (Python example)

```python
import anthropic, json

client = anthropic.Anthropic()

def run_agent(system_md_path: str, user_input: str) -> str:
    system = open(system_md_path).read()
    # Strip the outer ```xml fences for the actual prompt
    prompt = system.split("```xml\n", 1)[1].rsplit("\n```", 1)[0]
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        system=prompt,
        messages=[{"role": "user", "content": user_input}],
    )
    return msg.content[0].text

# 1. Plan
plan = run_agent("01-planner.md", requirement)

# 2. Break into tasks
tasks_json = run_agent("02-task-breaker.md", plan)
tasks = json.loads(tasks_json)

# 3-7. Per-task loop
for task in tasks:
    code    = run_agent("03-implementer.md", json.dumps(task))
    biz     = run_agent("04-business-logic-reviewer.md", f"Requirement: {requirement}\nCode: {code}")
    sec     = run_agent("05-security-reviewer.md", biz if "FAIL" not in biz else code)
    opt     = run_agent("06-optimization-reviewer.md", sec)
    cleaned = run_agent("07-cleaner.md", opt)

# 8. Commit
commit_cmds = run_agent("08-git-committer.md", cleaned)
print(commit_cmds)  # human reviews and runs manually
```

## Notes

- Agents 4-6 run on the output of the previous agent (not the raw implementer output) so each layer's fixes are visible to the next.
- Agent 8 output is **printed for human review** — never executed programmatically.
- The Task Breaker (Agent 2) JSON output drives the loop: parse `task_id`, `service`, `target_files` to know which agent context to inject.
- For prompt-only changes (onboarding_system.md), skip Agents 5 and 6 — security and perf are irrelevant to Markdown.
