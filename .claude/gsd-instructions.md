<!-- GSD:project-start source:PROJECT.md -->
## Project

**SENA Voice Assistant — LiveKit + Gemini Live Overhaul**

A real-time voice assistant for Australian NDIS disability support workers built on LiveKit Agents Framework with Gemini Live native audio (single model: STT + reasoning + TTS). Replaces the current HTTP turn-based voice service with a persistent bidirectional audio stream. Covers two flows: (1) voice-guided personal details collection (7-screen gated form), and (2) case note dictation (Flow B). All audio transits SENA servers for NDIS compliance and Australian data residency.

**Core Value:** A support worker — including those with no digital literacy or visual impairment — completes a full participant onboarding or shift case note entirely by speaking, with sub-500ms response latency, without touching a screen.

### Constraints

- **Compliance:** Australian Privacy Act APP 8 + APP 11 — all audio and PII must transit and be logged on SENA servers
- **Compliance:** NDIS — human-in-the-loop approval required before case note submission
- **Multi-tenancy:** Zero cross-tenant data leakage — legally mandated, not optional
- **Latency:** Target <500ms end-to-end (Level 0 normal path). Level 2 fallback up to ~900ms acceptable
- **Tech stack:** Python 3.12+, FastAPI, SQLAlchemy async, LiveKit Agents v1.4+, Gemini Live (`google.realtime.RealtimeModel`), Redis, PostgreSQL
- **AWS Bedrock:** Current LLM (Claude Sonnet) stays for case note text post-processing and approval; Gemini Live handles the conversational voice layer
- **Team:** 2 effective engineers (senior + team lead); intern on guided tasks
<!-- GSD:project-end -->

<!-- GSD:stack-start source:STACK.md -->
## Technology Stack

Technology stack not yet documented. Will populate after codebase mapping or first phase.
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, or `.github/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
