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
