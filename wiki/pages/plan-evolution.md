---
title: Plan Evolution
type: topic
tags: [planning, historical, timeline]
sources: ["[[src-plan]]", "[[src-plan-v1]]", "[[src-plan-v2]]", "[[src-revised-plan]]", "[[src-new-plan]]"]
created: 2026-04-15
updated: 2026-04-15
---

# Plan Evolution

Tracks how SENA's plan changed across the five archived plan documents.

## Timeline (archived versions)

| Version | Source | Key addition |
|---------|--------|--------------|
| v0 | [[src-plan]] | Initial stake in the ground — voice first, OCR later, multi-tenant |
| v1 | [[src-plan-v1]] | Milestone structure + rough timeline |
| v2 | [[src-plan-v2]] | LiveKit locked in; Flow B named as first user flow |
| Revised | [[src-revised-plan]] | Four-approach (A/B/C/D) framing for voice architecture |
| New | [[src-new-plan]] | Approach D + Gemini Live committed; 64 requirements across 9 phases |

## Current authoritative plan

`.planning/ROADMAP.md` + `.planning/REQUIREMENTS.md` (v1 requirements).

The archived plans are **historical context**, not active specs.

## Lessons the evolution shows

- Early plans underweighted data residency → triggered revised-plan rethink
- Single-model voice (Gemini Live) emerged late; initial plans assumed STT+LLM+TTS chain
- Client blockers remained remarkably stable — most [[open-questions]] are still open

## Connections

- Hub: [[Architecture]]
- Sources: 5 archived plan documents (see frontmatter)
