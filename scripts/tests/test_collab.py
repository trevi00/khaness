#!/usr/bin/env python3
"""Tests for validators/collab.py — empty/happy/negative paths."""
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

from validators import collab  # noqa: E402


def _run_in(cwd: Path) -> str:
    saved = os.getcwd()
    buf = io.StringIO()
    try:
        os.chdir(cwd)
        with redirect_stdout(buf):
            collab.main()
    finally:
        os.chdir(saved)
    return buf.getvalue()


def test_empty_cwd_skips_cleanly():
    with tempfile.TemporaryDirectory() as td:
        out = _run_in(Path(td))
        assert "[PASS]" in out, f"expected [PASS] on empty cwd, got: {out[:200]}"


def test_happy_path_full_collab_setup():
    """Full .github/ + workflows + PR template + CODEOWNERS + CONTRIBUTING → [PASS] no [FAIL]."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        gh = root / ".github"
        (gh / "workflows").mkdir(parents=True)
        (gh / "workflows" / "ci.yml").write_text("name: ci\n", encoding="utf-8")
        (gh / "PULL_REQUEST_TEMPLATE.md").write_text("# PR\n", encoding="utf-8")
        (gh / "CODEOWNERS").write_text("* @owner\n", encoding="utf-8")
        (root / "CONTRIBUTING.md").write_text("# Contrib\n", encoding="utf-8")
        out = _run_in(root)
        assert "[PASS]" in out, f"expected [PASS], got: {out[:300]}"
        assert "[FAIL]" not in out, f"unexpected [FAIL], got: {out[:300]}"


def test_negative_path_workflows_dir_missing():
    """.github/ exists but no workflows/ subdir → [FAIL]."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".github").mkdir()
        out = _run_in(root)
        assert "[FAIL]" in out, f"expected [FAIL] for missing workflows, got: {out[:300]}"


def main() -> int:
    tests = [
        test_empty_cwd_skips_cleanly,
        test_happy_path_full_collab_setup,
        test_negative_path_workflows_dir_missing,
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
