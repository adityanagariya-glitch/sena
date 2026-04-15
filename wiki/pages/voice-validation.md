---
title: Voice Validation (Readback-Confirm)
type: concept
tags: [voice, validation, accessibility, ux]
sources: ["[[src-new-plan]]", ".planning/REQUIREMENTS.md"]
created: 2026-04-15
updated: 2026-04-15
---

# Voice Validation (Readback-Confirm)

Data-accuracy pattern for voice-captured fields. The agent reads back the captured value; the user must confirm before it's stored.

## Why

- STT errors on specific strings (numbers, names) are costly in NDIS (wrong NDIS number = wrong participant)
- Low-literacy / vision-impaired users can't verify by reading a screen
- Creates a clear consent point per-field

## Pattern

1. Agent captures value from utterance
2. Agent: "I heard X. Is that correct?"
3. User: "yes" / "no, it's Y"
4. On "no", re-prompt. On "yes", commit.
5. Log both the captured value and the confirmation (audit trail)

## Where it's used

- [[form-filling]] — every field in the 7-screen flow
- Critical fields in [[flow-b-voice-dictation]] (participant ID, medication names, incident codes)

## Accessibility

Part of the broader accessibility layer (`.planning/REQUIREMENTS.md` Phase 6):
- pause/resume
- camera trigger for barcode scan where voice fails
- incident escalation ("help" keyword wakes a supervisor)

## Connections

- Hub: [[Architecture]], [[NDIS]]
- Related: [[form-filling]], [[flow-b-voice-dictation]]
