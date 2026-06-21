#!/usr/bin/env python3
"""Tests for validators/convention.py — empty/happy/negative paths."""
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

from validators import convention  # noqa: E402


def _run_in(cwd: Path) -> str:
    saved = os.getcwd()
    buf = io.StringIO()
    try:
        os.chdir(cwd)
        with redirect_stdout(buf):
            convention.main()
    finally:
        os.chdir(saved)
    return buf.getvalue()


def test_empty_cwd_skips_cleanly():
    with tempfile.TemporaryDirectory() as td:
        out = _run_in(Path(td))
        assert "[PASS]" in out, f"expected [PASS] on empty cwd, got: {out[:200]}"


def test_happy_path_complete_convention():
    """convention.md with package table + DTO/Request + ErrorCode → no [FAIL]."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        cdir = root / ".claude"
        cdir.mkdir()
        (cdir / "convention.md").write_text(
            "# Convention\n\n"
            "## Package Structure\n\n"
            "| 패키지 | 설명 |\n"
            "|--------|------|\n"
            "| controller | REST 엔드포인트 |\n"
            "| service | 비즈니스 로직 |\n"
            "| dto | DTO Request Response 객체 |\n\n"
            "## ErrorCode\n에러 코드 체계는 ErrorCode enum으로 정의.\n",
            encoding="utf-8",
        )
        out = _run_in(root)
        assert "[PASS]" in out, f"expected [PASS], got: {out[:400]}"
        assert "[FAIL]" not in out, f"unexpected [FAIL], got: {out[:400]}"


def test_negative_path_missing_table_and_keywords():
    """convention.md exists but lacks table, DTO, error → [FAIL]."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        cdir = root / ".claude"
        cdir.mkdir()
        (cdir / "convention.md").write_text(
            "# Convention\n\nThis is a placeholder convention document.\n",
            encoding="utf-8",
        )
        out = _run_in(root)
        assert "[FAIL]" in out, f"expected [FAIL] for incomplete convention, got: {out[:400]}"


def main() -> int:
    tests = [
        test_empty_cwd_skips_cleanly,
        test_happy_path_complete_convention,
        test_negative_path_missing_table_and_keywords,
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
