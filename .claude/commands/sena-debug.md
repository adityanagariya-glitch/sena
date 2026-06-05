---
description: Direct invocation of @agent-sena-debug — Socratic root-cause analyst. Asks 5 diagnostic questions, triages by SENA symptom signature, walks user to root cause via top-2 hypotheses each with a diagnostic command. Complements @agent-sena-log-analyzer (which isolates root frame FROM a stack trace — sena-debug starts BEFORE you even have a trace).
allowed-tools: Agent
---

Route the symptom to `sena-debug` (Agent tool, subagent_type: sena-debug).

The agent will:
1. Ask 5 questions: symptom, reproduction, what changed, what tried, current hypothesis. Wait for answers.
2. Triage against SENA signature table (Gemini VAD death / WS lock / `assert_session_owner` / Case Review 501 / webhook / test-CI drift / etc.).
3. Walk user to root via top-2 hypotheses + diagnostic commands.
4. Always end with: *"What would have caught this earlier?"* (test, validator, hook).
5. Escalate to `@agent-sena-log-analyzer` if a trace appears, or `@agent-sena-engineering-collaborator` after 3 iterations without convergence.

User's args (the symptom): $ARGUMENTS
