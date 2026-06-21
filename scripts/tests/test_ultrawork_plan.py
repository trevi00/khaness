#!/usr/bin/env python3
"""Tests for lib/ultrawork_plan.py — slice/wave plan persistence + resume."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _state(td: Path):
    import lib.paths as P
    return mock.patch.object(P, "STATE_DIR", td / "state")


def test_save_and_pending_all_initially():
    from lib.ultrawork_plan import save_plan, pending_slices
    with tempfile.TemporaryDirectory() as td, _state(Path(td)):
        assert save_plan("s1", [["a", "b"], ["c"]]) is True
        assert pending_slices("s1") == ["a", "b", "c"]


def test_mark_done_excluded_from_pending():
    from lib.ultrawork_plan import save_plan, mark_slice, pending_slices
    with tempfile.TemporaryDirectory() as td, _state(Path(td)):
        save_plan("s1", [["a", "b"], ["c"]])
        assert mark_slice("s1", "a", "done") is True
        assert mark_slice("s1", "b", "skipped") is True
        # done + skipped excluded; only c remains to (re)run
        assert pending_slices("s1") == ["c"]


def test_failed_slice_is_pending_for_resume():
    from lib.ultrawork_plan import save_plan, mark_slice, pending_slices
    with tempfile.TemporaryDirectory() as td, _state(Path(td)):
        save_plan("s1", [["a"]])
        mark_slice("s1", "a", "failed")
        assert pending_slices("s1") == ["a"]   # failed -> resume re-runs it


def test_resave_preserves_prior_status():
    """A re-run that re-saves the SAME plan must NOT reset completed slices to pending."""
    from lib.ultrawork_plan import save_plan, mark_slice, progress
    with tempfile.TemporaryDirectory() as td, _state(Path(td)):
        save_plan("s1", [["a", "b"]])
        mark_slice("s1", "a", "done")
        save_plan("s1", [["a", "b"]])           # resume re-saves
        p = progress("s1")
        assert p["done"] == 1 and p["pending"] == 1


def test_progress_and_complete():
    from lib.ultrawork_plan import save_plan, mark_slice, progress
    with tempfile.TemporaryDirectory() as td, _state(Path(td)):
        save_plan("s1", [["a", "b"]])
        assert progress("s1")["complete"] is False
        mark_slice("s1", "a", "done"); mark_slice("s1", "b", "done")
        p = progress("s1")
        assert p["complete"] is True and p["done"] == 2


def test_mark_unknown_slice_or_status_failsoft():
    from lib.ultrawork_plan import save_plan, mark_slice
    with tempfile.TemporaryDirectory() as td, _state(Path(td)):
        save_plan("s1", [["a"]])
        assert mark_slice("s1", "ghost", "done") is False
        assert mark_slice("s1", "a", "bogus") is False


def main() -> int:
    tests = [
        test_save_and_pending_all_initially,
        test_mark_done_excluded_from_pending,
        test_failed_slice_is_pending_for_resume,
        test_resave_preserves_prior_status,
        test_progress_and_complete,
        test_mark_unknown_slice_or_status_failsoft,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK] {t.__name__}")
        except Exception as e:
            import traceback
            print(f"  [FAIL] {t.__name__}: {type(e).__name__}: {e}")
            traceback.print_exc()
            failed += 1
    if failed == 0:
        print(f"[OK] {len(tests)} tests passed")
        return 0
    print(f"[FAIL] {failed}/{len(tests)} tests failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
