#!/usr/bin/env python3
"""Unit tests for lib/strike_dispatcher.py — N-strike research dispatch gate.

Per debate-1778161608-713bdc gen 4 byte-identical (snapshot 7add2646...):
  - F2 = 2 (RESEARCH_DISPATCH_THRESHOLD coincides with STRIKE_THRESHOLD)
  - F7 = atomic_counter_plus_timeout (per (sid, fingerprint) quota=3)
  - B5 cold-start: FileNotFoundError -> {} bootstrap, JSONDecodeError -> RuntimeError

Coverage:
  - should_dispatch: below threshold / at threshold / quota exhausted
  - record_dispatch: increments + persists atomically
  - load_counter: cold-start (no file) returns {}
  - load_counter: corrupt JSON raises RuntimeError (B5 fail-closed)
  - load_counter: non-dict JSON raises RuntimeError
  - reset_counter: removes sidecar file
  - remaining_quota: tracks correctly
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _redirect_state_dir(tmp: Path):
    from lib import paths as P
    P.STATE_DIR = tmp / "state"
    P.STATE_DIR.mkdir(parents=True, exist_ok=True)


def test_should_dispatch_below_threshold_returns_false():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.strike_dispatcher import should_dispatch

        assert should_dispatch("fp1", "orch-x", strike_count=1) is False


def test_should_dispatch_at_threshold_returns_true():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.strike_dispatcher import should_dispatch, RESEARCH_DISPATCH_THRESHOLD

        # F2 = 2 (matches lib.repeat_error_tracker.STRIKE_THRESHOLD)
        assert RESEARCH_DISPATCH_THRESHOLD == 2
        assert should_dispatch("fp1", "orch-x", strike_count=2) is True


def test_should_dispatch_quota_exhausted_returns_false():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.strike_dispatcher import (
            should_dispatch,
            record_dispatch,
            PER_FINGERPRINT_DISPATCH_LIMIT,
        )

        assert PER_FINGERPRINT_DISPATCH_LIMIT == 3

        # Use up the per-fingerprint quota
        for _ in range(PER_FINGERPRINT_DISPATCH_LIMIT):
            record_dispatch("fp_exhaust", "orch-x")

        # 4th attempt at same fingerprint blocked even with strike threshold met
        assert should_dispatch("fp_exhaust", "orch-x", strike_count=10) is False

        # New fingerprint in same sid still dispatches
        assert should_dispatch("fp_new", "orch-x", strike_count=2) is True


def test_should_dispatch_empty_inputs_return_false():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.strike_dispatcher import should_dispatch

        assert should_dispatch("", "orch-x", strike_count=5) is False
        assert should_dispatch("fp", "", strike_count=5) is False


def test_record_dispatch_increments_and_persists():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.strike_dispatcher import record_dispatch, load_counter

        assert record_dispatch("fp1", "orch-x") == 1
        assert record_dispatch("fp1", "orch-x") == 2
        assert record_dispatch("fp2", "orch-x") == 1

        counter = load_counter("orch-x")
        assert counter == {"fp1": 2, "fp2": 1}


def test_load_counter_cold_start_returns_empty():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.strike_dispatcher import load_counter

        # No file yet — B5 FileNotFoundError branch
        assert load_counter("orch-cold") == {}


def test_load_counter_corrupt_json_raises():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.strike_dispatcher import load_counter, _counter_path

        path = _counter_path("orch-corrupt")
        path.write_text("{not valid json", encoding="utf-8")

        try:
            load_counter("orch-corrupt")
        except RuntimeError as e:
            assert "counter corrupt" in str(e)
            return
        raise AssertionError("expected RuntimeError on corrupt counter file")


def test_load_counter_non_dict_json_raises():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.strike_dispatcher import load_counter, _counter_path

        path = _counter_path("orch-list")
        path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

        try:
            load_counter("orch-list")
        except RuntimeError as e:
            assert "JSON object" in str(e)
            return
        raise AssertionError("expected RuntimeError on non-dict counter")


def test_reset_counter_removes_sidecar():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.strike_dispatcher import (
            record_dispatch, load_counter, reset_counter, _counter_path,
        )

        record_dispatch("fp", "orch-x")
        assert _counter_path("orch-x").exists()

        reset_counter("orch-x")
        assert not _counter_path("orch-x").exists()
        assert load_counter("orch-x") == {}


def test_remaining_quota():
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.strike_dispatcher import (
            record_dispatch, remaining_quota, PER_FINGERPRINT_DISPATCH_LIMIT,
        )

        assert remaining_quota("fp", "orch-x") == PER_FINGERPRINT_DISPATCH_LIMIT
        record_dispatch("fp", "orch-x")
        assert remaining_quota("fp", "orch-x") == PER_FINGERPRINT_DISPATCH_LIMIT - 1


def test_severity_high_dispatches_on_first_occurrence():
    """D2 severity-branch: severity='HIGH' lowers the effective threshold to 1 so a
    validator advisory HIGH dispatches on first occurrence; 'strike' keeps F2=2."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.strike_dispatcher import should_dispatch
        # strike_count=1: default 'strike' lane stays below F2=2 -> False
        assert should_dispatch("fp", "orch-x", strike_count=1) is False
        # HIGH lane: effective threshold 1 -> first occurrence dispatches
        assert should_dispatch("fp", "orch-x", strike_count=1, severity="HIGH") is True
        # an unrecognized severity falls back to the LOCKED F2 threshold (not relaxed)
        assert should_dispatch("fp", "orch-x", strike_count=1, severity="MEDIUM") is False


def test_severity_default_preserves_strike_behavior():
    """Backward-compat: omitting severity reproduces the locked 2-strike gate."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        from lib.strike_dispatcher import should_dispatch
        assert should_dispatch("fp", "orch-x", strike_count=2) is True
        assert should_dispatch("fp", "orch-x", strike_count=1) is False


TESTS = [
    test_should_dispatch_below_threshold_returns_false,
    test_should_dispatch_at_threshold_returns_true,
    test_severity_high_dispatches_on_first_occurrence,
    test_severity_default_preserves_strike_behavior,
    test_should_dispatch_quota_exhausted_returns_false,
    test_should_dispatch_empty_inputs_return_false,
    test_record_dispatch_increments_and_persists,
    test_load_counter_cold_start_returns_empty,
    test_load_counter_corrupt_json_raises,
    test_load_counter_non_dict_json_raises,
    test_reset_counter_removes_sidecar,
    test_remaining_quota,
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
