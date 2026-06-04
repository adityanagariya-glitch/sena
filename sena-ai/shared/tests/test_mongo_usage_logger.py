"""Tests for the per-user MongoDB usage logger — no real DB, no pymongo needed."""
from __future__ import annotations

import sena_common.mongo_usage_logger as mod


class _Result:
    def __init__(self, matched: int) -> None:
        self.matched_count = matched


def test_log_usage_noop_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(mod, "_get_collection", lambda: None)
    assert mod.log_usage("screen_1", 100, 50, user="p-1") is None


def test_first_event_pushes_screen_entry_into_user_doc(monkeypatch) -> None:
    calls: list = []

    class _Fake:
        def update_one(self, flt: dict, update: dict, upsert: bool = False) -> _Result:
            calls.append((flt, update, upsert))
            return _Result(0)  # no existing screen entry → push path fires

    monkeypatch.setattr(mod, "_get_collection", lambda: _Fake())
    assert mod.log_usage("screen_1", 450, 320, user="p-1") == "p-1"

    flt, update, upsert = calls[1]  # second call is the $push upsert
    assert flt == {"user": "p-1"}
    assert upsert is True
    entry = update["$push"]["screens"]
    assert entry["screenname"] == "screen_1"
    assert entry["input_token"] == 450
    assert entry["output_token"] == 320
    assert entry["total_tokens"] == 770  # computed server-side, not trusted
    assert entry["error"] is None


def test_same_screen_increments_instead_of_duplicating(monkeypatch) -> None:
    calls: list = []

    class _Fake:
        def update_one(self, flt: dict, update: dict, upsert: bool = False) -> _Result:
            calls.append((flt, update, upsert))
            return _Result(1)  # screen entry exists → $inc only, no push

    monkeypatch.setattr(mod, "_get_collection", lambda: _Fake())
    assert mod.log_usage("screen_1", 10, 5, user="p-1") == "p-1"

    assert len(calls) == 1  # no second (push) call
    flt, update, _ = calls[0]
    assert flt == {"user": "p-1", "screens.screenname": "screen_1"}
    assert update["$inc"]["screens.$.input_token"] == 10
    assert update["$inc"]["screens.$.total_tokens"] == 15


def test_log_usage_never_raises_on_failure(monkeypatch) -> None:
    class _Boom:
        def update_one(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("mongo down")

    monkeypatch.setattr(mod, "_get_collection", lambda: _Boom())
    assert mod.log_usage("s", 1, 1, user="p") is None


# ── _get_collection resilience (cold-Atlas regression) ─────────────────────────
# Observed 2026-06-04: a transient OperationFailure on the first create_index
# (cold M0 cluster) aborted init AND latched _init_attempted, silencing every
# later turn for the whole process. Index is best-effort; transient connect
# failures must not latch.


class _FakeColl:
    def __init__(self, *, index_error: bool = False) -> None:
        self._index_error = index_error
        self.created = False

    def create_index(self, *a: object, **k: object) -> None:
        if self._index_error:
            raise RuntimeError("OperationFailure: cluster waking up")
        self.created = True


class _FakeDB:
    def __init__(self, coll: _FakeColl) -> None:
        self._coll = coll

    def __getitem__(self, _name: str) -> _FakeColl:
        return self._coll


class _FakeClient:
    def __init__(self, coll: _FakeColl) -> None:
        self._db = _FakeDB(coll)

    def __getitem__(self, _name: str) -> _FakeDB:
        return self._db


def _reset(monkeypatch) -> None:
    monkeypatch.setattr(mod, "_collection", None)
    monkeypatch.setattr(mod, "_init_attempted", False)
    monkeypatch.setattr(mod, "_PYMONGO_AVAILABLE", True)
    monkeypatch.setattr(mod, "_load_env_file_fallback", lambda: None)


def test_get_collection_survives_index_error(monkeypatch) -> None:
    _reset(monkeypatch)
    monkeypatch.setenv("SENA_AI_MONGO_USAGE_URI", "mongodb://fake/")
    coll = _FakeColl(index_error=True)
    monkeypatch.setattr(mod, "MongoClient", lambda *a, **k: _FakeClient(coll))
    # create_index raises → suppressed; collection is still returned + usable.
    assert mod._get_collection() is coll


def test_transient_connect_failure_not_latched_and_self_heals(monkeypatch) -> None:
    _reset(monkeypatch)
    monkeypatch.setenv("SENA_AI_MONGO_USAGE_URI", "mongodb://fake/")
    coll = _FakeColl()
    state = {"n": 0}

    def flaky(*a: object, **k: object) -> _FakeClient:
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("cold cluster")
        return _FakeClient(coll)

    monkeypatch.setattr(mod, "MongoClient", flaky)
    assert mod._get_collection() is None  # transient fail
    assert mod._init_attempted is False  # NOT latched — must retry
    assert mod._get_collection() is coll  # next call self-heals


def test_uri_unset_is_latched(monkeypatch) -> None:
    _reset(monkeypatch)
    monkeypatch.delenv("SENA_AI_MONGO_USAGE_URI", raising=False)
    assert mod._get_collection() is None
    assert mod._init_attempted is True  # deterministic disable → stays latched
