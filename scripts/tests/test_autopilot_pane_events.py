#!/usr/bin/env python3
"""Unit tests for lib/autopilot_pane_events.py — D6 from debate-1778302432-1ce6ea.

Coverage:
  - emit_pane_started writes type=pane_started + auto-stamps ts via lib.logging
  - emit_pane_status writes type=pane_status with status + exit_code
  - per-pane file at sid_dir/panes/<pane_id>.jsonl (NEVER canonical events.jsonl)
  - distinct pane_ids → distinct files (no concurrent write contention)
  - read_pane_events round-trip
  - list_pane_ids enumerates only existing shards
  - Invalid pane_id rejected (path traversal guard)
  - Malformed jsonl line skipped (fail-soft)
  - kwargs passthrough
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def test_emit_pane_started_writes_per_pane_file():
    from lib.autopilot_pane_events import emit_pane_started
    with tempfile.TemporaryDirectory() as td:
        sid_dir = Path(td)
        emit_pane_started(sid_dir, "D1", decision_id="D1", worktree_path="/tmp/wt")
        target = sid_dir / "panes" / "D1.jsonl"
        assert target.exists(), f"expected {target} to exist"


def test_emit_pane_started_does_not_touch_canonical_events_jsonl():
    from lib.autopilot_pane_events import emit_pane_started
    with tempfile.TemporaryDirectory() as td:
        sid_dir = Path(td)
        canonical = sid_dir / "events.jsonl"
        emit_pane_started(sid_dir, "D1", decision_id="D1")
        assert not canonical.exists(), \
            "pane events MUST NOT write to canonical events.jsonl"


def test_emit_pane_started_record_shape():
    from lib.autopilot_pane_events import emit_pane_started
    with tempfile.TemporaryDirectory() as td:
        sid_dir = Path(td)
        emit_pane_started(sid_dir, "D1", decision_id="D1", worktree_path="/wt")
        line = (sid_dir / "panes" / "D1.jsonl").read_text(encoding="utf-8").strip()
        rec = json.loads(line)
        assert rec["type"] == "pane_started"
        assert rec["pane_id"] == "D1"
        assert rec["decision_id"] == "D1"
        assert rec["worktree_path"] == "/wt"
        assert "ts" in rec  # auto-stamped by lib.logging.jsonl_append


def test_emit_pane_status_record_shape():
    from lib.autopilot_pane_events import emit_pane_status
    with tempfile.TemporaryDirectory() as td:
        sid_dir = Path(td)
        emit_pane_status(sid_dir, "D3", status="exited", exit_code=0)
        line = (sid_dir / "panes" / "D3.jsonl").read_text(encoding="utf-8").strip()
        rec = json.loads(line)
        assert rec["type"] == "pane_status"
        assert rec["pane_id"] == "D3"
        assert rec["status"] == "exited"
        assert rec["exit_code"] == 0
        assert "ts" in rec


def test_emit_pane_status_exit_code_none_for_running():
    from lib.autopilot_pane_events import emit_pane_status
    with tempfile.TemporaryDirectory() as td:
        sid_dir = Path(td)
        emit_pane_status(sid_dir, "D6", status="running")
        line = (sid_dir / "panes" / "D6.jsonl").read_text(encoding="utf-8").strip()
        rec = json.loads(line)
        assert rec["status"] == "running"
        assert rec["exit_code"] is None


def test_distinct_pane_ids_get_distinct_files():
    from lib.autopilot_pane_events import emit_pane_started
    with tempfile.TemporaryDirectory() as td:
        sid_dir = Path(td)
        emit_pane_started(sid_dir, "D1")
        emit_pane_started(sid_dir, "D3")
        assert (sid_dir / "panes" / "D1.jsonl").exists()
        assert (sid_dir / "panes" / "D3.jsonl").exists()


def test_emit_appends_not_overwrites():
    from lib.autopilot_pane_events import emit_pane_started, emit_pane_status
    with tempfile.TemporaryDirectory() as td:
        sid_dir = Path(td)
        emit_pane_started(sid_dir, "D1", decision_id="D1")
        emit_pane_status(sid_dir, "D1", status="exited", exit_code=0)
        lines = (sid_dir / "panes" / "D1.jsonl").read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["type"] == "pane_started"
        assert json.loads(lines[1])["type"] == "pane_status"


def test_read_pane_events_round_trip():
    from lib.autopilot_pane_events import (
        emit_pane_started, emit_pane_status, read_pane_events,
    )
    with tempfile.TemporaryDirectory() as td:
        sid_dir = Path(td)
        emit_pane_started(sid_dir, "D1", decision_id="D1")
        emit_pane_status(sid_dir, "D1", status="exited", exit_code=0)
        events = read_pane_events(sid_dir, "D1")
        assert len(events) == 2
        assert events[0]["type"] == "pane_started"
        assert events[1]["type"] == "pane_status"


def test_read_pane_events_returns_empty_for_missing_file():
    from lib.autopilot_pane_events import read_pane_events
    with tempfile.TemporaryDirectory() as td:
        events = read_pane_events(Path(td), "nonexistent")
        assert events == []


def test_read_pane_events_skips_malformed_lines():
    from lib.autopilot_pane_events import read_pane_events
    with tempfile.TemporaryDirectory() as td:
        sid_dir = Path(td)
        panes_dir = sid_dir / "panes"
        panes_dir.mkdir()
        target = panes_dir / "D1.jsonl"
        target.write_text(
            '{"type":"pane_started","pane_id":"D1"}\n'
            'not-json\n'
            '{"type":"pane_status","pane_id":"D1"}\n',
            encoding="utf-8",
        )
        events = read_pane_events(sid_dir, "D1")
        assert len(events) == 2
        assert events[0]["type"] == "pane_started"
        assert events[1]["type"] == "pane_status"


def test_list_pane_ids_returns_sorted():
    from lib.autopilot_pane_events import emit_pane_started, list_pane_ids
    with tempfile.TemporaryDirectory() as td:
        sid_dir = Path(td)
        emit_pane_started(sid_dir, "D6")
        emit_pane_started(sid_dir, "D1")
        emit_pane_started(sid_dir, "D3")
        ids = list_pane_ids(sid_dir)
        assert ids == ["D1", "D3", "D6"]


def test_list_pane_ids_empty_when_no_panes_dir():
    from lib.autopilot_pane_events import list_pane_ids
    with tempfile.TemporaryDirectory() as td:
        assert list_pane_ids(Path(td)) == []


def test_invalid_pane_id_with_slash_rejected():
    from lib.autopilot_pane_events import emit_pane_started
    with tempfile.TemporaryDirectory() as td:
        try:
            emit_pane_started(Path(td), "../escape")
        except ValueError:
            return
        raise AssertionError("expected ValueError on path-traversal pane_id")


def test_invalid_pane_id_with_backslash_rejected():
    from lib.autopilot_pane_events import emit_pane_started
    with tempfile.TemporaryDirectory() as td:
        try:
            emit_pane_started(Path(td), "bad\\name")
        except ValueError:
            return
        raise AssertionError("expected ValueError on backslash pane_id")


def test_empty_pane_id_rejected():
    from lib.autopilot_pane_events import emit_pane_started
    with tempfile.TemporaryDirectory() as td:
        try:
            emit_pane_started(Path(td), "")
        except ValueError:
            return
        raise AssertionError("expected ValueError on empty pane_id")


def test_extra_kwargs_passed_through_to_record():
    from lib.autopilot_pane_events import emit_pane_started
    with tempfile.TemporaryDirectory() as td:
        sid_dir = Path(td)
        emit_pane_started(sid_dir, "D1", branch="auto/x/D1", custom_field=42)
        rec = json.loads((sid_dir / "panes" / "D1.jsonl").read_text(encoding="utf-8").strip())
        assert rec["branch"] == "auto/x/D1"
        assert rec["custom_field"] == 42


TESTS = [
    test_emit_pane_started_writes_per_pane_file,
    test_emit_pane_started_does_not_touch_canonical_events_jsonl,
    test_emit_pane_started_record_shape,
    test_emit_pane_status_record_shape,
    test_emit_pane_status_exit_code_none_for_running,
    test_distinct_pane_ids_get_distinct_files,
    test_emit_appends_not_overwrites,
    test_read_pane_events_round_trip,
    test_read_pane_events_returns_empty_for_missing_file,
    test_read_pane_events_skips_malformed_lines,
    test_list_pane_ids_returns_sorted,
    test_list_pane_ids_empty_when_no_panes_dir,
    test_invalid_pane_id_with_slash_rejected,
    test_invalid_pane_id_with_backslash_rejected,
    test_empty_pane_id_rejected,
    test_extra_kwargs_passed_through_to_record,
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
