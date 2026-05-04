---
id: 0005
tags: [python, pytest, editable-install]
symptom: Live edits invisible to pytest — AttributeError on a model field that clearly exists in source
fixed: 2026-05-02
---

# 0005 — Editable install points to wrong clone

## Symptom

Tests fail with `AttributeError: 'X' object has no attribute 'y'` even though `y` is plainly defined on the Pydantic model in source. `python -c "from X import M; print(list(M.model_fields))"` from the same shell ALSO omits the field. Re-running with `PYTHONPATH=src` makes everything work.

## Root cause

Two clones of the repo exist on disk:

```
C:\Users\Admin\Downloads\SENA\sena-ai\...                       ← old clone, pip-installed here
C:\Users\Admin\Downloads\sena-mobile\sena-mobile\SENA_AI\...    ← active clone where edits land
```

A prior session ran `pip install -e .` from the OLD clone. Editable installs write a `.pth` entry pointing at one specific source path; subsequent clones don't get auto-picked-up. Pytest imports `onboarding.X` and Python resolves it via `site-packages` → the OLD clone → no recent edits.

## Diagnostic command

```bash
python -c "import onboarding.services.screen_context as m; print(m.__file__)"
```

If the printed path is NOT the directory you're editing, you've found this bug.

## Fix

Two options:

1. **Reinstall against the active clone** (correct long-term fix):
   ```bash
   cd <active-clone>/sena-ai/services/onboarding
   pip uninstall onboarding -y
   pip install -e .
   ```

2. **Workaround for one shell** (faster when you can't disturb the install):
   ```bash
   cd <active-clone>/sena-ai/services/onboarding
   PYTHONPATH=src python -m pytest tests/
   ```

`PYTHONPATH=src` prepends the active source to `sys.path`, beating `site-packages` resolution.

## Why this bites in this repo

`pip install -e .` is documented in `0003-onboarding-src-layout-import.md` as the fix for src-layout imports. That instruction doesn't say "from THIS clone" — operators with multiple clones land here. Always verify `m.__file__` after a confusing test failure.
