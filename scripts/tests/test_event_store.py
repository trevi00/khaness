#!/usr/bin/env python3
"""Tests for lib/event_store.py — append-only JSONL event store for debate engine."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _redirect_state_dir(tmp: Path) -> None:
    from lib import paths as P
    from lib import event_store as E
    P.STATE_DIR = tmp / "state"
    P.STATE_DIR.mkdir(parents=True, exist_ok=True)
    E.DEBATES_DIR = P.STATE_DIR / "debates"


def test_new_store_creates_session_dir():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.event_store import EventStore
        store = EventStore("debate-test-123")
        assert store.dir.exists()
        assert store.path == store.dir / "events.jsonl"


def test_append_writes_record():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.event_store import EventStore
        store = EventStore("debate-test-456")
        rec = store.append(
            event_type="proposal", gen=1, actor="planner",
            payload={"decision": "use approach A"},
        )
        assert rec["type"] == "proposal"
        assert rec["gen"] == 1
        assert rec["actor"] == "planner"
        assert rec["payload"] == {"decision": "use approach A"}
        assert "ts" in rec
        assert "hash" in rec
        assert len(rec["hash"]) == 12  # truncated sha1


def test_replay_returns_records_in_order():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.event_store import EventStore
        store = EventStore("debate-test-789")
        store.append("proposal", 1, "planner", {"x": 1})
        store.append("critique", 1, "critic", {"y": 2})
        store.append("verdict", 1, "architect", {"z": 3})
        events = store.replay()
        assert len(events) == 3
        assert events[0]["type"] == "proposal"
        assert events[1]["type"] == "critique"
        assert events[2]["type"] == "verdict"


def test_replay_missing_file_returns_empty():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.event_store import EventStore
        store = EventStore("debate-empty-001")
        # Don't append anything; replay should return []
        store.path.unlink(missing_ok=True)
        assert store.replay() == []


def test_replay_skips_corrupt_lines():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.event_store import EventStore
        store = EventStore("debate-corrupt-001")
        store.append("proposal", 1, "planner", {"a": 1})
        # Inject a corrupt line manually
        with store.path.open("a", encoding="utf-8") as f:
            f.write("not-json-at-all\n")
        store.append("verdict", 1, "architect", {"b": 2})
        events = store.replay()
        assert len(events) == 2  # corrupt skipped
        assert events[0]["type"] == "proposal"
        assert events[1]["type"] == "verdict"


def test_last_by_type_returns_latest():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.event_store import EventStore
        store = EventStore("debate-last-001")
        store.append("proposal", 1, "planner", {"v": 1})
        store.append("proposal", 2, "planner", {"v": 2})
        store.append("verdict", 2, "architect", {"v": 3})
        last = store.last_by_type("proposal")
        assert last is not None
        assert last["gen"] == 2
        assert last["payload"]["v"] == 2


def test_last_by_type_returns_none_when_absent():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.event_store import EventStore
        store = EventStore("debate-absent-001")
        store.append("proposal", 1, "planner", {})
        assert store.last_by_type("verdict") is None


def test_iter_by_type_filters():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.event_store import EventStore
        store = EventStore("debate-iter-001")
        store.append("proposal", 1, "planner", {})
        store.append("critique", 1, "critic", {})
        store.append("proposal", 2, "planner", {})
        proposals = list(store.iter_by_type("proposal"))
        assert len(proposals) == 2
        assert all(e["type"] == "proposal" for e in proposals)


def test_last_gen_zero_when_empty():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.event_store import EventStore
        store = EventStore("debate-gen-001")
        store.path.unlink(missing_ok=True)
        assert store.last_gen() == 0


def test_last_gen_returns_max():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.event_store import EventStore
        store = EventStore("debate-gen-002")
        store.append("proposal", 1, "planner", {})
        store.append("verdict", 3, "architect", {})
        store.append("proposal", 2, "planner", {})
        assert store.last_gen() == 3


def test_payload_hash_deterministic():
    """Same payload → same hash (replayability invariant)."""
    from lib.event_store import _hash_payload
    h1 = _hash_payload({"a": 1, "b": [2, 3]})
    h2 = _hash_payload({"b": [2, 3], "a": 1})  # same content, different key order
    assert h1 == h2  # sort_keys=True


def test_payload_hash_differs_on_value_change():
    from lib.event_store import _hash_payload
    h1 = _hash_payload({"a": 1})
    h2 = _hash_payload({"a": 2})
    assert h1 != h2


def test_appended_lines_are_valid_jsonl():
    """Each appended line must be valid JSON terminated by \\n."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.event_store import EventStore
        store = EventStore("debate-jsonl-001")
        store.append("proposal", 1, "planner", {"x": "한글"})  # non-ASCII payload
        lines = store.path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["payload"]["x"] == "한글"


def test_replay_signals_mid_log_corruption():
    # deep-audit pass-2: a malformed line WITH a good line after it is mid-log
    # corruption (not a torn tail) and must be SURFACED via telemetry, not dropped
    # silently — replay() drives last_gen()/convergence.
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        import lib.event_store as es
        store = es.EventStore("debate-corrupt-mid")
        store.append("proposal", 1, "planner", {"a": 1})
        with store.path.open("a", encoding="utf-8") as f:
            f.write("not-json-mid-log\n")
        store.append("verdict", 1, "architect", {"b": 2})
        calls = []
        orig = es.log_telemetry
        es.log_telemetry = lambda cat, rec: calls.append((cat, rec))
        try:
            events = store.replay()
        finally:
            es.log_telemetry = orig
        assert len(events) == 2  # good events still returned (fail-soft)
        assert any(c[0] == "event-store-corruption" for c in calls), \
            "mid-log corruption must be signaled via telemetry"


def test_replay_torn_final_line_not_signaled():
    # A torn FINAL line (concurrent appender mid-write) is benign — skipped
    # silently with NO telemetry noise.
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        import lib.event_store as es
        store = es.EventStore("debate-torn-tail")
        store.append("proposal", 1, "planner", {"a": 1})
        with store.path.open("a", encoding="utf-8") as f:
            f.write("torn-final-no-newline-mid-write")
        calls = []
        orig = es.log_telemetry
        es.log_telemetry = lambda cat, rec: calls.append((cat, rec))
        try:
            events = store.replay()
        finally:
            es.log_telemetry = orig
        assert len(events) == 1
        assert not calls, "torn final line is benign; must NOT be signaled"


TESTS = [
    test_new_store_creates_session_dir,
    test_append_writes_record,
    test_replay_returns_records_in_order,
    test_replay_missing_file_returns_empty,
    test_replay_skips_corrupt_lines,
    test_last_by_type_returns_latest,
    test_last_by_type_returns_none_when_absent,
    test_iter_by_type_filters,
    test_last_gen_zero_when_empty,
    test_last_gen_returns_max,
    test_payload_hash_deterministic,
    test_payload_hash_differs_on_value_change,
    test_appended_lines_are_valid_jsonl,
    test_replay_signals_mid_log_corruption,
    test_replay_torn_final_line_not_signaled,
]


def main() -> int:
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"  [OK] {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {fn.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"  [ERROR] {fn.__name__}: {type(e).__name__}: {e}")
    if failed:
        print(f"\n[FAIL] {failed}/{len(TESTS)} tests failed")
        return 1
    print(f"\n[OK] {len(TESTS)} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
