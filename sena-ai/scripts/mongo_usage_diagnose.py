"""Diagnose a SENA_AI_MONGO_USAGE_URI connection — prints the REAL error.

Unlike `python -m sena_common.mongo_usage_logger` (which swallows errors to
protect the app), this surfaces the full failure + a tailored hint, after
masking the password. Run it with the env var set in your shell:

    $env:SENA_AI_MONGO_USAGE_URI = "mongodb+srv://user:pass@cluster0.../?appName=Cluster0"
    python sena-ai/scripts/mongo_usage_diagnose.py
"""
from __future__ import annotations

import contextlib
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_HINTS = {
    "OperationFailure": (
        "AUTH/permission. Password wrong or not URL-encoded, or the DB user "
        "lacks read/write. Atlas -> Database Access."
    ),
    "ServerSelectionTimeoutError": (
        "Atlas didn't answer the handshake. Most likely the cluster is PAUSED "
        "(Atlas -> Resume) OR your IP isn't allow-listed (Atlas -> Network "
        "Access -> add current IP, or 0.0.0.0/0 to test)."
    ),
    "ConfigurationError": "URI/SRV problem. Check the scheme; ensure dnspython is installed.",
}


def _mask(uri: str) -> str:
    # mongodb+srv://user:PASSWORD@host -> mongodb+srv://user:****@host
    return re.sub(r"(://[^:/]+:)[^@]+(@)", r"\1****\2", uri)


def _load_dotenv_fallback() -> None:
    """If the URI isn't in the shell env, read it from sena-ai/.env directly.

    Minimal KEY=VALUE parser (no python-dotenv dep). Only fills SENA_AI_MONGO_*
    keys that aren't already set, so a shell `$env:` override still wins. This
    makes the URI survive shell restarts — set it once in .env.
    """
    if os.environ.get("SENA_AI_MONGO_USAGE_URI"):
        return
    env_file = Path(__file__).resolve().parent.parent / ".env"
    with contextlib.suppress(OSError):
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key.startswith("SENA_AI_MONGO_") and key not in os.environ:
                os.environ[key] = value.strip().strip('"').strip("'")


def main() -> int:
    _load_dotenv_fallback()
    uri = os.environ.get("SENA_AI_MONGO_USAGE_URI")
    if not uri:
        print("FAIL: SENA_AI_MONGO_USAGE_URI is not set (checked shell env AND sena-ai/.env).")
        print("Fix (persistent): add this line to sena-ai/.env :")
        print(
            "  SENA_AI_MONGO_USAGE_URI=mongodb+srv://kevalshah_db_user:PASSWORD"
            "@cluster0.ufunsfb.mongodb.net/?appName=Cluster0"
        )
        print('Or (this shell only): $env:SENA_AI_MONGO_USAGE_URI = "mongodb+srv://..."')
        return 1

    print(f"URI (masked): {_mask(uri)}")
    if "<" in uri or ">" in uri:
        print("PROBLEM: URI still contains < > placeholder brackets — delete them.")
        return 2
    if not uri.startswith(("mongodb://", "mongodb+srv://")):
        print("PROBLEM: URI must start with mongodb:// or mongodb+srv://")
        return 2

    try:
        from pymongo import MongoClient
        from pymongo.server_api import ServerApi

        from sena_common.mongo_usage_logger import split_mongo_credentials
    except ImportError:
        print("FAIL: pymongo / sena_common not importable here.")
        print("Fix: pip install pymongo ; pip install -e shared")
        return 3

    try:
        stripped_uri, mongo_user, mongo_pwd = split_mongo_credentials(uri)
        kwargs: dict[str, Any] = {"server_api": ServerApi("1"), "serverSelectionTimeoutMS": 12000}
        if mongo_user is not None:
            kwargs["username"] = mongo_user
        if mongo_pwd is not None:
            kwargs["password"] = mongo_pwd
        client = MongoClient(stripped_uri, **kwargs)
        print(f"ping: {client.admin.command('ping')}")
        db = client[os.environ.get("SENA_AI_MONGO_USAGE_DB", "keval_app")]
        coll = db[os.environ.get("SENA_AI_MONGO_USAGE_COLL", "usage_logs")]
        now = datetime.now(UTC)
        coll.update_one(
            {"user": "diagnose"},
            {
                "$push": {
                    "screens": {
                        "screenname": "diagnose",
                        "input_token": 1,
                        "output_token": 1,
                        "total_tokens": 2,
                        "error": None,
                        "timestamp": now,
                    }
                },
                "$set": {"updated_at": now},
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
        print('OK: test entry upserted into the user="diagnose" document')
        print("SUCCESS — connection + write both work.")
        return 0
    except Exception as exc:
        name = type(exc).__name__
        print(f"CONNECT FAILED: {name}: {str(exc)[:300]}")
        print(f"HINT: {_HINTS.get(name, 'Read the message above — it states the cause.')}")
        if "auth" in str(exc).lower():
            print("HINT: AUTH signal — wrong user/password or password not URL-encoded.")
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
