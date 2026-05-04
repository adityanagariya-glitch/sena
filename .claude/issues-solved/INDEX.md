---
title: Issues-Solved Index
updated: 2026-04-21
purpose: Grep-first symptom lookup. Read this BEFORE debugging.
---

# Issues-Solved Index

**How to use:** `grep` this file for symptom keywords. If no hit, problem is new — solve it, then append a row. If hit, read linked file, apply fix.

| # | Symptoms | File |
|---|----------|------|
| 0004 | SpeechConfig language_code extra_forbidden, RealtimeInputConfig AttributeError, google-genai 1.4.0 missing types | [0004-google-genai-sdk-version-mismatch.md](0004-google-genai-sdk-version-mismatch.md) |

**Conventions:** newest at top. Symptom column uses user's language (what you'd type when debugging). Tags are single-word, lowercase.

---

## Table

| ID | Tags | Symptom | One-line fix | File |
|----|------|---------|--------------|------|
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
