#!/usr/bin/env python3
"""Tests for validators/prd.py — empty/happy/negative paths."""
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

from validators import prd  # noqa: E402


def _run_in(cwd: Path) -> str:
    saved = os.getcwd()
    buf = io.StringIO()
    try:
        os.chdir(cwd)
        with redirect_stdout(buf):
            prd.main()
    finally:
        os.chdir(saved)
    return buf.getvalue()


def test_empty_cwd_skips_cleanly():
    with tempfile.TemporaryDirectory() as td:
        out = _run_in(Path(td))
        assert "[PASS]" in out, f"expected [PASS] on empty cwd, got: {out[:200]}"


def test_happy_path_valid_prd():
    """requirements/index.md + domain/*.md with user story → no [FAIL]."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        req = root / ".claude" / "requirements"
        domain = req / "domain"
        domain.mkdir(parents=True)
        # index.md links to user.md
        (req / "index.md").write_text(
            "# Requirements\n\n- [user](domain/user.md)\n",
            encoding="utf-8",
        )
        (domain / "user.md").write_text(
            "# User Domain\n\n"
            "AS a customer I WANT to log in SO THAT I can place orders.\n",
            encoding="utf-8",
        )
        out = _run_in(root)
        assert "[PASS]" in out, f"expected [PASS], got: {out[:400]}"
        assert "[FAIL]" not in out, f"unexpected [FAIL], got: {out[:400]}"


def test_negative_path_no_index_no_domain():
    """requirements/ exists but no index.md and no domain/ → [FAIL]."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        req = root / ".claude" / "requirements"
        req.mkdir(parents=True)
        # empty requirements dir
        out = _run_in(root)
        assert "[FAIL]" in out, f"expected [FAIL] for empty requirements/, got: {out[:400]}"


def main() -> int:
    tests = [
        test_empty_cwd_skips_cleanly,
        test_happy_path_valid_prd,
        test_negative_path_no_index_no_domain,
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
