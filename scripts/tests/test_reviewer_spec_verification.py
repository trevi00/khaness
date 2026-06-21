#!/usr/bin/env python3
"""Coverage for handlers/post_tool/reviewer.py::run_spec_verification —
the subprocess-spawning core of the live PostToolUse spec-verify hook
(harness-full-review rank 3: was previously ZERO-coverage despite firing on
every real Edit/Write).

Exercises run_spec_verification end-to-end via the project-level resolution
(<cwd>/.claude/scripts/<name>) with fake verify scripts, plus the timeout
branch via a monkeypatched subprocess.run (no real 30s wait).
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from handlers.post_tool import reviewer as R


def _project_with_script(td: str, name: str, body: str) -> Path:
    proj = Path(td)
    sdir = proj / ".claude" / "scripts"
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / name).write_text(body, encoding="utf-8")
    return proj


def test_pass_script_wraps_spec_verify_pass():
    with tempfile.TemporaryDirectory() as td:
        proj = _project_with_script(td, "verify-x.py", "print('[PASS] all good')\n")
        out = R.run_spec_verification(str(proj), "verify-x.py", "TestLabel")
    assert out is not None
    assert "spec-verify-pass" in out
    assert "TestLabel" in out and "[PASS] all good" in out
    assert "spec-verify-fail" not in out


def test_fail_script_wraps_spec_verify_fail():
    with tempfile.TemporaryDirectory() as td:
        proj = _project_with_script(td, "verify-x.py", "print('[FAIL] something broke')\n")
        out = R.run_spec_verification(str(proj), "verify-x.py", "TestLabel")
    assert out is not None
    assert "spec-verify-fail" in out
    assert "[FAIL] something broke" in out


def test_empty_output_returns_none():
    with tempfile.TemporaryDirectory() as td:
        proj = _project_with_script(td, "verify-x.py", "pass\n")  # prints nothing
        out = R.run_spec_verification(str(proj), "verify-x.py", "TestLabel")
    assert out is None


def test_missing_script_returns_none():
    # Not in project/.claude/scripts/ AND not in SCRIPTS_DIR (handlers/post_tool/)
    with tempfile.TemporaryDirectory() as td:
        out = R.run_spec_verification(td, "verify-does-not-exist.py", "TestLabel")
    assert out is None


def test_timeout_branch_wraps_fail(monkeypatch_run=None):
    # Monkeypatch subprocess.run to raise TimeoutExpired so we exercise the
    # timeout handling WITHOUT a real 30s wait.
    saved = R.subprocess.run

    def _raise_timeout(*a, **k):
        raise subprocess.TimeoutExpired(cmd="fake", timeout=30)

    with tempfile.TemporaryDirectory() as td:
        proj = _project_with_script(td, "verify-x.py", "print('[PASS] never reached')\n")
        R.subprocess.run = _raise_timeout
        try:
            out = R.run_spec_verification(str(proj), "verify-x.py", "TestLabel")
        finally:
            R.subprocess.run = saved
    assert out is not None
    assert "spec-verify-fail" in out
    # the timeout message (Korean '타임아웃') distinguishes it from a content FAIL
    assert "타임아웃" in out or "timeout" in out.lower()


TESTS = [
    test_pass_script_wraps_spec_verify_pass,
    test_fail_script_wraps_spec_verify_fail,
    test_empty_output_returns_none,
    test_missing_script_returns_none,
    test_timeout_branch_wraps_fail,
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
