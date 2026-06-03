# 0008 — Token usage never reaches MongoDB (real sessions); only manual test docs appear

**Tags:** usage-logging, mongodb, sena-common, editable-install, stub
**Date:** 2026-06-03
**Iterations to solve:** 3 parallel diagnostic agents (import / env / call-path)

## Symptom

After wiring `emit_usage` → MongoDB, manual smoke-test docs (`diagnose`, `screen_1`, `autonomy_check`) landed fine, but **no document from a real voice onboarding session ever appeared** in the `usage_logs` collection. Sessions ran end-to-end (e.g. `80569225`, `5a18d0be`) yet produced zero usage rows.

## Root cause

`sena-common` (the `shared/` package) was **never `pip install -e`'d** into the venv:

- `pip show sena-common` → not found; no `__editable__.sena_common-*.pth` in the venv.
- No service declares `sena-common` as a dependency in its `pyproject.toml` (`onboarding/pyproject.toml` lists fastapi/uvicorn/pydantic/… but not `sena-common`).

So when the onboarding service starts, `from sena_common.usage_logger import emit_usage` raises `ModuleNotFoundError`, and `gemini_live.py` falls into its defensive `ImportError` branch:

```python
try:
    from sena_common.usage_logger import UsageFeature, emit_usage
except ImportError:           # <-- this fired on every real run
    def emit_usage(**_):      # 89-char no-op stub
        return None
```

Every real-session `emit_usage(...)` call returned `None` silently. The manual tests "worked" only because they were run with an explicit `PYTHONPATH=sena-ai/shared/src`, which the uvicorn service launch does **not** set.

All downstream plumbing was fine: URI present in `sena-ai/.env`, kill-switch unset, `.env`-fallback path (`parents[3]`) geometrically correct, `pymongo` installed, `participant_id`/`tenant_id`/`step_id` populated at the call site.

## Fix

```bash
pip install -e sena-ai/shared          # from SENA_AI root, into the active venv
```

Verify the stub flipped to the real function (run from the service dir, NO PYTHONPATH):

```bash
cd sena-ai/services/onboarding
python -c "from onboarding.services.gemini_live import emit_usage; import inspect; \
print(inspect.getsourcefile(emit_usage), len(inspect.getsource(emit_usage)))"
# Expect: ...shared/src/sena_common/usage_logger.py  3593   (NOT gemini_live.py / ~89)
```

End-to-end confirmed: a real `emit_usage(... participant_id=..., step_id=..., prompt_tokens=111, response_tokens=222)` call from the onboarding import context produced a Mongo doc with per-user/per-screen `input=111 output=222 total=333`.

## Prevention

- Added `pip install -e shared` (bash + PowerShell) to `.claude/rules/build-and-run.md` Setup, with a note that it is **not optional** — skipping it silently reverts `emit_usage` to the no-op stub.
- General rule: a `try/except ImportError` that swaps in a no-op stub will hide a missing editable install forever. When a logger/sink "does nothing" but raises no error, check whether its module actually imported (`inspect.getsourcefile`) before debugging the sink itself.

## Secondary leak — RESOLVED 2026-06-03

Even with the import fixed, the **final** turn's tokens were dropped: `emit_usage` only fired inside the `turn_complete` handler in `gemini_live.py`, and a `client_stop` cancels the Gemini reader task before that handler runs — losing one turn per session.

Fixed: added `GeminiLiveSession._flush_pending_usage(*, reason)` (sync) that recomputes the delta `_usage_cum_* - _usage_emitted_*` and emits it, then advances the watermark. Called from `run()`'s `finally` with `reason="session_end"` (wrapped in try/except so telemetry can't break teardown). Idempotent by construction: the existing `turn_complete` block already advances the watermark, so if the last turn was emitted normally the flush computes all-zero deltas and no-ops — no double-count. Regression test: `tests/test_gemini_live_usage_flush.py` (3 tests: flush-once+idempotent, no-double-count, finally invokes flush).

