#!/usr/bin/env python3
"""Tests for validators/test.py — empty/happy/negative paths."""
from __future__ import annotations

import io
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from validators import test as test_validator  # noqa: E402


def _run_in(cwd: Path) -> str:
    saved = os.getcwd()
    buf = io.StringIO()
    try:
        os.chdir(cwd)
        with redirect_stdout(buf):
            test_validator.main()
    finally:
        os.chdir(saved)
    return buf.getvalue()


def test_empty_cwd_skips_cleanly():
    with tempfile.TemporaryDirectory() as td:
        out = _run_in(Path(td))
        assert "[PASS]" in out, f"expected [PASS] on empty cwd, got: {out[:200]}"


def test_happy_path_test_class_exists():
    """src/test with *Test.java → no [FAIL]."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        tdir = root / "src" / "test" / "java" / "com" / "ex"
        tdir.mkdir(parents=True)
        (tdir / "FooTest.java").write_text(
            "package com.ex;\npublic class FooTest {}\n",
            encoding="utf-8",
        )
        out = _run_in(root)
        assert "[PASS]" in out, f"expected [PASS], got: {out[:400]}"
        assert "[FAIL]" not in out, f"unexpected [FAIL], got: {out[:400]}"


def test_negative_path_src_test_empty():
    """src/test/ exists but no Test/Tests/Spec.java → [FAIL]."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # Create src/test with non-test java files
        tdir = root / "src" / "test" / "java"
        tdir.mkdir(parents=True)
        (tdir / "Helper.java").write_text(
            "public class Helper {}\n", encoding="utf-8",
        )
        out = _run_in(root)
        assert "[FAIL]" in out, f"expected [FAIL] for empty src/test, got: {out[:400]}"


def main() -> int:
    tests = [
        test_empty_cwd_skips_cleanly,
        test_happy_path_test_class_exists,
        test_negative_path_src_test_empty,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK] {t.__name__}")
        except Exception as e:
            print(f"  [FAIL] {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    if failed == 0:
        print(f"[OK] {len(tests)} tests passed")
        return 0
    print(f"[FAIL] {failed}/{len(tests)} tests failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
