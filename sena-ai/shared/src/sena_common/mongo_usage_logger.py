"""MongoDB usage logger — SENA's single token-usage sink.

`sena_common.usage_logger.emit_usage` (the chokepoint every AI call already
hits) forwards each event here on a worker thread; `log_usage` can also be
called directly.

Schema — ONE document per user, ONE entry per screen:

    {
      "user": "<participant_id / user_id / session id>",
      "screens": [
        {"screenname": "screen_1", "input_token": 450, "output_token": 320,
         "total_tokens": 770, "error": null, "timestamp": ...},
        {"screenname": "screen_2", ...}
      ],
      "created_at": ..., "updated_at": ...
    }

Repeat calls for the same (user, screen) INCREMENT that screen's counters —
never duplicate documents, never duplicate screen entries.

Hardening:
  * NO hardcoded credentials — connection string comes from
    SENA_AI_MONGO_USAGE_URI (process env, falling back to sena-ai/.env for
    bare local runs). Never commit a URI containing a password.
  * Lazy, pooled connection — created once on first use; nothing connects at
    import time.
  * Never raises. A logging failure returns None; it never breaks the caller.

pymongo is SYNC/blocking. In async service code call it off the event loop —
the autolog forward in `usage_logger` already does this on a worker thread.

Config (env):
  SENA_AI_MONGO_USAGE_URI    required to enable — full mongodb+srv://... string
  SENA_AI_MONGO_USAGE_DB     optional, default "keval_app"
  SENA_AI_MONGO_USAGE_COLL   optional, default "usage_logs"

Install: `pip install pymongo` (optional dep — module no-ops if absent).
"""
from __future__ import annotations

import contextlib
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

try:
    from pymongo import MongoClient
    from pymongo.server_api import ServerApi

    _PYMONGO_AVAILABLE = True
except ImportError:  # pymongo not installed — degrade to a silent no-op.
    _PYMONGO_AVAILABLE = False

_log = structlog.get_logger("mongo_usage")

_collection: Any = None
_init_attempted = False


def _load_env_file_fallback() -> None:
    """Fill SENA_AI_MONGO_* env vars from sena-ai/.env when not already set.

    Lets the standalone smoke test and bare local runs work without exporting
    the URI in every shell. Real process env always wins. No-ops outside the
    repo src layout (e.g. site-packages installs) or when .env is absent.
    """
    if os.environ.get("SENA_AI_MONGO_USAGE_URI"):
        return
    # __file__ = sena-ai/shared/src/sena_common/mongo_usage_logger.py
    # parents[3] = sena-ai/ — where the local .env lives.
    env_file = Path(__file__).resolve().parents[3] / ".env"
    with contextlib.suppress(OSError):
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key.startswith("SENA_AI_MONGO_") and key not in os.environ:
                os.environ[key] = value.strip().strip('"').strip("'")


def _get_collection() -> Any:
    """Lazily create the pooled client + collection.

    Returns None if disabled (pymongo missing / URI unset) or if the connection
    fails. The first failure is remembered so we don't retry on every call.
    Never raises.
    """
    global _collection, _init_attempted
    if _collection is not None:
        return _collection
    if _init_attempted:
        return None
    _init_attempted = True

    if not _PYMONGO_AVAILABLE:
        _log.warning("mongo_usage_disabled", reason="pymongo_not_installed")
        return None
    _load_env_file_fallback()
    uri = os.environ.get("SENA_AI_MONGO_USAGE_URI")
    if not uri:
        _log.warning("mongo_usage_disabled", reason="SENA_AI_MONGO_USAGE_URI_unset")
        return None

    try:
        db_name = os.environ.get("SENA_AI_MONGO_USAGE_DB", "keval_app")
        coll_name = os.environ.get("SENA_AI_MONGO_USAGE_COLL", "usage_logs")
        client = MongoClient(uri, server_api=ServerApi("1"))
        coll = client[db_name][coll_name]
        coll.create_index("user")
        _collection = coll
        return _collection
    except Exception as exc:
        _log.warning("mongo_usage_connect_failed", error=type(exc).__name__)
        return None


def log_usage(
    screenname: str,
    input_token: int,
    output_token: int,
    error: str | None = None,
    *,
    user: str = "unknown",
) -> str | None:
    """Record token usage into the per-user document.

    One MongoDB document per `user`; each screen is ONE entry in its `screens`
    array. Repeat calls for the same (user, screen) INCREMENT that entry's
    counters instead of appending duplicates.

    Returns the user key on success, None when disabled or failed. Never raises.
    """
    collection = _get_collection()
    if collection is None:
        return None
    try:
        in_tok = int(input_token or 0)
        out_tok = int(output_token or 0)
        now = datetime.now(UTC)

        # 1. Screen entry already exists for this user → increment its counters.
        update_existing: dict[str, Any] = {
            "$inc": {
                "screens.$.input_token": in_tok,
                "screens.$.output_token": out_tok,
                "screens.$.total_tokens": in_tok + out_tok,
            },
            "$set": {"screens.$.timestamp": now, "updated_at": now},
        }
        if error is not None:
            update_existing["$set"]["screens.$.error"] = error
        result = collection.update_one(
            {"user": user, "screens.screenname": screenname}, update_existing
        )
        if result.matched_count == 0:
            # 2. First event for this (user, screen) → push a fresh entry and
            # create the user document if needed. Writes are serialized through
            # usage_logger's single worker thread, so the two-step
            # check-then-push cannot race against itself.
            collection.update_one(
                {"user": user},
                {
                    "$push": {
                        "screens": {
                            "screenname": screenname,
                            "input_token": in_tok,
                            "output_token": out_tok,
                            "total_tokens": in_tok + out_tok,
                            "error": error,
                            "timestamp": now,
                        }
                    },
                    "$set": {"updated_at": now},
                    "$setOnInsert": {"created_at": now},
                },
                upsert=True,
            )
        return user
    except Exception as exc:
        _log.warning("mongo_usage_insert_failed", error=type(exc).__name__)
        return None


if __name__ == "__main__":
    # Manual smoke test:
    #   python -m sena_common.mongo_usage_logger   (URI from env or sena-ai/.env)
    _user = log_usage("screen_1", 450, 320, user="smoke_test_user")
    _log.info("mongo_usage_smoke", user=_user)
