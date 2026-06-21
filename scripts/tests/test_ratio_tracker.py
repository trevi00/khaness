#!/usr/bin/env python3
"""Tests for lib/ratio_tracker.py — Read:Edit ratio counter."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _redirect_ratio_files(tmp: Path) -> None:
    from lib import ratio_tracker as R
    R._RATIO_FILE = str(tmp / "ratio.json")
    R._RATIO_COOLDOWN_FILE = str(tmp / "cooldown")


def test_load_counts_empty_returns_zeros():
    with tempfile.TemporaryDirectory() as td:
        _redirect_ratio_files(Path(td))
        from lib.ratio_tracker import load_counts
        assert load_counts() == {"research": 0, "modify": 0}


def test_save_and_load_roundtrip():
    with tempfile.TemporaryDirectory() as td:
        _redirect_ratio_files(Path(td))
        from lib.ratio_tracker import save_counts, load_counts
        save_counts({"research": 5, "modify": 2})
        assert load_counts() == {"research": 5, "modify": 2}


def test_reset_zeroes_counts():
    with tempfile.TemporaryDirectory() as td:
        _redirect_ratio_files(Path(td))
        from lib.ratio_tracker import save_counts, reset_counts, load_counts
        save_counts({"research": 9, "modify": 9})
        reset_counts()
        assert load_counts() == {"research": 0, "modify": 0}


def test_record_research_tool_increments_research():
    with tempfile.TemporaryDirectory() as td:
        _redirect_ratio_files(Path(td))
        from lib.ratio_tracker import record_tool_use
        snap = record_tool_use("Read")
        assert snap["research"] == 1
        snap = record_tool_use("Grep")
        assert snap["research"] == 2
        snap = record_tool_use("Glob")
        assert snap["research"] == 3


def test_record_modify_tool_increments_modify():
    with tempfile.TemporaryDirectory() as td:
        _redirect_ratio_files(Path(td))
        from lib.ratio_tracker import record_tool_use
        snap = record_tool_use("Edit")
        assert snap["modify"] == 1
        snap = record_tool_use("Write")
        assert snap["modify"] == 2
        snap = record_tool_use("MultiEdit")
        assert snap["modify"] == 3


def test_record_unknown_tool_does_not_increment():
    with tempfile.TemporaryDirectory() as td:
        _redirect_ratio_files(Path(td))
        from lib.ratio_tracker import record_tool_use
        snap = record_tool_use("Bash")
        assert snap == {"research": 0, "modify": 0}


def test_check_ratio_warning_below_min_edits_returns_none():
    from lib.ratio_tracker import check_ratio_warning, MIN_EDITS
    # MIN_EDITS gates the check (avoid noise on early turns)
    assert check_ratio_warning({"research": 0, "modify": MIN_EDITS - 1}) is None


def test_check_ratio_warning_below_threshold_returns_ratio():
    from lib.ratio_tracker import check_ratio_warning, WARN_THRESHOLD, MIN_EDITS
    # ratio = research/modify; below WARN_THRESHOLD → return the ratio
    data = {"research": MIN_EDITS, "modify": MIN_EDITS}  # ratio = 1.0
    result = check_ratio_warning(data)
    assert result is not None
    assert result == 1.0
    assert result < WARN_THRESHOLD


def test_check_ratio_warning_at_or_above_threshold_returns_none():
    from lib.ratio_tracker import check_ratio_warning, WARN_THRESHOLD
    # ratio = 9/3 = 3.0 ≥ WARN_THRESHOLD → no warning
    data = {"research": int(WARN_THRESHOLD * 3), "modify": 3}
    assert check_ratio_warning(data) is None


def test_constants_sanity():
    from lib.ratio_tracker import (
        WARN_THRESHOLD, MIN_EDITS, RESET_HOURS, COOLDOWN_SECONDS,
        RESEARCH_TOOLS, MODIFY_TOOLS,
    )
    assert WARN_THRESHOLD > 0
    assert MIN_EDITS >= 1
    assert RESET_HOURS > 0
    assert COOLDOWN_SECONDS > 0
    assert RESEARCH_TOOLS == frozenset({"Read", "Grep", "Glob"})
    assert MODIFY_TOOLS == frozenset({"Edit", "Write", "MultiEdit"})


TESTS = [
    test_load_counts_empty_returns_zeros,
    test_save_and_load_roundtrip,
    test_reset_zeroes_counts,
    test_record_research_tool_increments_research,
    test_record_modify_tool_increments_modify,
    test_record_unknown_tool_does_not_increment,
    test_check_ratio_warning_below_min_edits_returns_none,
    test_check_ratio_warning_below_threshold_returns_ratio,
    test_check_ratio_warning_at_or_above_threshold_returns_none,
    test_constants_sanity,
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
