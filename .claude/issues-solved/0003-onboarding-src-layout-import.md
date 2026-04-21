---
id: 0003
symptom: "ModuleNotFoundError: No module named 'onboarding' when running uvicorn"
aliases:
  - "onboarding service won't start"
  - "uvicorn ModuleNotFoundError"
  - "src layout import fail"
  - "cannot import onboarding package"
  - "pip install -e needed"
root_cause: "Onboarding service uses src-layout (src/onboarding/); uvicorn can't resolve the import path without an editable install"
tags: [onboarding, python, setup, uvicorn, src-layout]
files: [sena-ai/services/onboarding/pyproject.toml]
fix_commit: "713037f"
date_solved: 2026-04-21
verified: "Service boots on port 8083; /harness loads; 48/48 tests pass"
---

# 0003 — Onboarding service import fails on uvicorn start

## Symptom

Running `uvicorn src.onboarding.main:create_app --factory --reload --port 8083` fails with:

```
ModuleNotFoundError: No module named 'onboarding'
```

Or Python finds `src/` but chokes on internal `from onboarding.services.X import Y` lines inside the package.

## Root cause

The service layout is:

```
sena-ai/services/onboarding/
├── pyproject.toml
└── src/
    └── onboarding/
        ├── main.py
        └── ...
```

`pyproject.toml` declares `onboarding` as the package, but Python doesn't know about `src/` as a root unless the package is installed. Running uvicorn from the service dir puts `cwd` on `sys.path`, which resolves `src.onboarding.main` for the entrypoint — but internal `from onboarding.X` imports expect `onboarding` to be directly importable.

## Fix

**Run `pip install -e .` once from `sena-ai/services/onboarding/` before starting uvicorn.**

```bash
cd sena-ai/services/onboarding
pip install -e .
uvicorn src.onboarding.main:create_app --factory --reload --port 8083
```

Editable install registers `src/onboarding/` as the importable `onboarding` package via the `pyproject.toml` `[tool.setuptools.packages.find]` config.

See commit `713037f` for the pyproject setup.

## Failed attempts (do NOT retry)

- **`PYTHONPATH=src uvicorn ...`** — works for entrypoint, breaks test discovery and IDE tooling
- **Flatten to non-src layout** — other services use src-layout; inconsistency cascades to tooling config
- **`python -m onboarding.main`** — factory pattern needs uvicorn's `--factory` flag, can't run as `-m`
- **Adding `sys.path.insert(0, 'src')` in main.py** — works for main but submodule imports still fail unpredictably
- **Running from repo root with full dotted path** — same ModuleNotFoundError, different flavor

## Why this fix (not alternatives)

Editable install is the setuptools-sanctioned way. One command, persists in the venv, integrates with pytest and ruff automatically. Every workaround breaks some adjacent tool.

## Related

- SESSION_START.md: "How to run onboarding service" block
- pyproject.toml: `[tool.setuptools.packages.find] where = ["src"]`
