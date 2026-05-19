---
title: Persistent Task List
updated: 2026-05-14
---

> **Clean slate — 2026-05-14.** Voice assistance (feature A) shipped to EC2; Case Review
> (feature B) shelved at Phase C. Full history is in `.claude/tasks/ARCHIVE.md`. The next
> feature's tasks go below; do NOT carry voice/case-review context into a new feature's
> planning unless the work is directly building on shipped infrastructure.
>
> **New session: read `.claude/SESSION_START.md` FIRST.**

# SENA Task List

Session-persistent todos. Survives `/compact` and session resets. Claude reads this file at session start and updates it as work progresses.

**Status legend:** `pending` | `in_progress` | `completed` | `blocked`

---

## Active

*(none — awaiting next-feature direction from user)*

Add new feature tasks below. Each entry:
- Heading: `### #<id> — <one-line description> (<YYYY-MM-DD>)`
- Bullets: status, priority, scope, files touched, tests, blockers
- Move to `ARCHIVE.md` when the feature is shipped/closed

---

## Backlog (deferred / blocked / decisions pending)

### Demo / dev-only code (decision pending)
- `sena-ai/demo_live_server.py` + `sena-ai/demo_client.html` — standalone Gemini Live demo. Files retained per 2026-05-14 decision; no longer referenced from SESSION_START.md. Delete if and only if you have a replacement debugging path for Gemini Live regressions.
- `sena-ai/services/onboarding/src/onboarding/main.py:15` + `40-59` — harness routes (`/harness`, `/harness/fixtures/{step_id}`). `test_harness.html` was deleted 2026-05-14; routes now return 404. Listed in `CODE_FILES_TO_REVIEW.md` — remove if no longer used.

### Infrastructure-blocked
- **RAG over NDIS documents** — pgvector + structure-aware chunking. NDIS Commission PDFs already at `ndis_wiki/sources/` (markdown). Ready to plan when prioritised.
- **OCR service implementation** — BLOCKED on client document samples.
- **JWT auth + RLS policies** — BLOCKED on client JWT claims structure.
- **AU data residency sign-off for Gemini Live** — BLOCKED on legal/compliance review (production prerequisite).
- **Production voice service migration** — `gemini_live_service.py` in `services/voice/` still uses OLD API. Migration to `send_realtime_input` pattern (per `feedback_gemini_live_patterns.md`) deferred until Flow B work resumes.
- **Flow B (case note dictation) LiveKit Agent pattern** — deferred indefinitely; no active roadmap.
- **Context window compression for >15 min sessions** — deferred; current sessions are short enough not to hit limits.
- **Ephemeral token auth for browser-side** — deferred.

---

## Conventions

- Update this file whenever a task status changes or a new task is added.
- Lead each task with ID, status, and 1-line summary.
- Include file paths, constraints, and acceptance criteria for P0/P1 items.
- When a task ships, move the entry to `ARCHIVE.md` rather than deleting it. Keep `Active` clean for the next feature.
- When backlog grows stale, prune to a separate archive file.
