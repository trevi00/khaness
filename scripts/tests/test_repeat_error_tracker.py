#!/usr/bin/env python3
"""Unit tests for lib/repeat_error_tracker.py — fingerprint stability,
2-Strike threshold, atomic save (W17+W24).
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib import repeat_error_tracker as RT  # noqa: E402


def _isolate_storage(tmpdir: str) -> None:
    """Point the tracker's storage at a temp file so tests don't pollute live state."""
    RT.REPEAT_ERRORS_FILE = os.path.join(tmpdir, ".claude_repeat_errors.json")


def test_extract_fingerprint_normalizes_paths():
    fp1 = RT.extract_error_fingerprint("Bash", {}, "Permission denied: /tmp/abc/123.log")
    fp2 = RT.extract_error_fingerprint("Bash", {}, "Permission denied: /var/log/xyz/999.log")
    assert fp1 is not None and fp2 is not None
    # Same fingerprint (paths normalized to <X>)
    assert fp1[0] == fp2[0], f"expected matching digests, got {fp1[0]} vs {fp2[0]}"


def test_fingerprint_none_for_empty_input():
    """Fingerprint requires non-empty content; clean tool output still gets a
    fingerprint (it's a stable hash of the last line) — only empty/None skip.
    Use has_error_indicator() to filter clean output BEFORE calling tracker.
    """
    assert RT.extract_error_fingerprint("Bash", {}, "") is None
    assert RT.extract_error_fingerprint("Bash", {}, "   \n  \n") is None
    assert RT.extract_error_fingerprint("Bash", {}, None) is None


def test_strike_threshold_first_no_warn():
    with tempfile.TemporaryDirectory() as td:
        _isolate_storage(td)
        result = RT.track_repeat_error("Bash", {}, "fatal: error connecting to db")
        assert result is None, "1st occurrence must not emit strike"


def test_strike_threshold_second_warns():
    with tempfile.TemporaryDirectory() as td:
        _isolate_storage(td)
        RT.track_repeat_error("Bash", {}, "fatal: error connecting to db")
        result = RT.track_repeat_error("Bash", {}, "fatal: error connecting to db")
        assert result is not None
        assert "2-Strike" in result or "에스컬레이션" in result


def test_strike_escalation_at_4th():
    with tempfile.TemporaryDirectory() as td:
        _isolate_storage(td)
        for _ in range(4):
            r = RT.track_repeat_error("Bash", {}, "fatal: error y")
        assert r is not None and "에스컬레이션" in r


def test_has_error_indicator_positive():
    assert RT.has_error_indicator("error: something broke")
    assert RT.has_error_indicator("FAILED to compile")
    assert RT.has_error_indicator("Permission denied")
    assert RT.has_error_indicator("Traceback (most recent call last):")


def test_has_error_indicator_negative():
    assert not RT.has_error_indicator("Build succeeded")
    assert not RT.has_error_indicator("")
    assert not RT.has_error_indicator(None)


def test_atomic_save_no_temp_leftover_on_success():
    """W24 atomic save: temp file cleaned up after os.replace."""
    with tempfile.TemporaryDirectory() as td:
        _isolate_storage(td)
        RT.track_repeat_error("Bash", {}, "error x")
        files = os.listdir(td)
        # Only the final file should remain — no stray .tmp
        assert all(not f.endswith(".tmp") for f in files), f"temp leftover: {files}"


TESTS = [
    test_extract_fingerprint_normalizes_paths,
    test_fingerprint_none_for_empty_input,
    test_strike_threshold_first_no_warn,
    test_strike_threshold_second_warns,
    test_strike_escalation_at_4th,
    test_has_error_indicator_positive,
    test_has_error_indicator_negative,
    test_atomic_save_no_temp_leftover_on_success,
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
    total = len(TESTS)
    if failed:
        print(f"\n[FAIL] {failed}/{total} tests failed")
        return 1
    print(f"\n[OK] {total} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
