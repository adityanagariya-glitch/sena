---
title: Issues-Solved Index
updated: 2026-05-12
purpose: Grep-first symptom lookup. Read this BEFORE debugging.
---

# Issues-Solved Index

**How to use:** `grep` this file for symptom keywords. If no hit, problem is new — solve it, then append a row. If hit, read linked file, apply fix.

| # | Symptoms | File |
|---|----------|------|
| 0006 | Voice writes bypass frontend validators; validation_rejection events silently dropped; no input_method tracking | [0006-voice-typed-validation-parity.md](0006-voice-typed-validation-parity.md) |

> **Numbering note:** 0004 was reserved historically for a google-genai SDK version-mismatch
> issue but the detail file was never written (the work shipped without a post-mortem entry).
> The slot is intentionally left vacant — do NOT reuse 0004 for new entries. Next free number
> is **0007**.

**Conventions:** newest at top. Symptom column uses user's language (what you'd type when debugging). Tags are single-word, lowercase.

---

## Table

| ID | Tags | Symptom | One-line fix | File |
|----|------|---------|--------------|------|
| 0006 | onboarding, voice, validation, flutter, contract | Voice writes bypass frontend validators; `validation_rejection` WS events silently dropped; no `input_method` tracking; cross-field invariants only enforced at advance gate | 6-agent orchestration produced `SENA_AI/flutterhandoffdev.md` as the canonical Flutter contract; backend added POST `/v1/onboarding/session/{sid}/errors`, `FieldValue.input_method`, per-write cross-field hook, and reconciled `reason_human` strings to match Flutter `AppStrings`. | [0006-voice-typed-validation-parity.md](0006-voice-typed-validation-parity.md) |
| 0005 | python, pytest, editable-install | Pytest sees stale code — `AttributeError` on a model field that exists in source; live edits not reflected | A second clone of the repo was registered via `pip install -e`; `python -c "import X; print(X.__file__)"` reveals it. Either re-install from current clone or run pytest with `PYTHONPATH=src` to override. | [0005-editable-install-wrong-clone.md](0005-editable-install-wrong-clone.md) |
| 0003 | onboarding, python, setup | `ModuleNotFoundError: No module named 'onboarding'` when running uvicorn | Run `pip install -e .` from `sena-ai/services/onboarding/` — src-layout needs editable install | [0003-onboarding-src-layout-import.md](0003-onboarding-src-layout-import.md) |
| 0002 | gemini-live, audio, firefox | Firefox plays no audio from Gemini Live (Chrome works) | Use single AudioContext shared by mic+playback; manual 24kHz→native upsample before `createBuffer` | [0002-firefox-no-audio-playback.md](0002-firefox-no-audio-playback.md) |
| 0001 | gemini-live, vad, multi-turn | VAD stops detecting user voice after 2-4 turns; model goes silent | Do NOT gate mic on `_agent_speaking` flag — stream audio unconditionally, use `START_SENSITIVITY_LOW` + `START_OF_ACTIVITY_INTERRUPTS` | [0001-vad-dies-after-few-turns.md](0001-vad-dies-after-few-turns.md) |

---

## How to add a new row

1. Copy `TEMPLATE.md` to `NNNN-kebab-symptom.md` (next number)
2. Fill fields
3. Prepend row to table above (newest first)
4. Commit with message: `docs(issues-solved): NNNN <symptom>`
