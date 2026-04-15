---
title: Form Filling (Personal Details)
type: concept
tags: [form, voice, accessibility, personal-details]
sources: ["[[src-new-plan]]", ".planning/REQUIREMENTS.md"]
created: 2026-04-15
updated: 2026-04-15
---

# Form Filling (Personal Details)

7-screen gated voice form flow for participant onboarding / personal details capture. Parallel to [[flow-b-voice-dictation]] but structured instead of free-form.

## Why gated

- Forms have required fields that must be validated (NDIS number format, DOB, contact details)
- Voice is error-prone for specific strings — readback-confirm ([[voice-validation]]) each gate
- Worker can't advance without completing the current gate; prevents half-filled forms

## Flow (indicative 7 screens)

1. Participant identification (NDIS number)
2. Contact info
3. Emergency contacts
4. Medical/health basics
5. Support goals
6. Consent recording
7. Review + submit

Exact screens load from tenant-specific form schema (see CTX-05).

## Voice UX patterns

- **Navigation** — "next", "back", "skip" voice commands
- **Validation** — readback before accepting a value ("I heard '12345678'; is that correct?")
- **Partial save** — state persists in Redis; disconnect + resume allowed

## Requirements

`.planning/REQUIREMENTS.md` Phase 5 (FORM-*).

## Connections

- Hub: [[Architecture]]
- Related: [[voice-validation]], [[voice-service]], [[context-preloading]]
