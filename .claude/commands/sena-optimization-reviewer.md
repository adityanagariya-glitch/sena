---
description: Direct invocation of @agent-sena-optimization-reviewer — async correctness + Redis pipelining + memory efficiency. FIXES inline (scoped, low-risk only).
allowed-tools: Agent
---

Route hot-path code (audio bridge, Redis loops, large JSON serialisation) to `sena-optimization-reviewer` (Agent tool, subagent_type: sena-optimization-reviewer). Refactors for `asyncio.gather`, `redis.asyncio.pipeline`, set/dict for O(1) lookups, generator expressions over list comprehensions where memory matters. **Fixes inline** because changes are scoped and behaviour-preserving.

Auto-flags: N+1 Redis calls, sequential `await` in loops, `list.__contains__` in hot paths, `json.dumps` on large structures without streaming.

User's args (code path or diff): $ARGUMENTS
