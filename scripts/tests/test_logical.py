#!/usr/bin/env python3
"""Tests for validators/logical.py — empty/happy/negative paths."""
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

from validators import logical  # noqa: E402


def _run_in(cwd: Path) -> str:
    saved = os.getcwd()
    buf = io.StringIO()
    try:
        os.chdir(cwd)
        with redirect_stdout(buf):
            logical.main()
    finally:
        os.chdir(saved)
    return buf.getvalue()


def test_empty_cwd_skips_cleanly():
    with tempfile.TemporaryDirectory() as td:
        out = _run_in(Path(td))
        assert "[PASS]" in out, f"expected [PASS] on empty cwd, got: {out[:200]}"


def test_happy_path_complete_logical():
    """logical-design.md with table + PK + FK + INDEX → no [FAIL]."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        d = root / ".claude" / "design" / "er"
        d.mkdir(parents=True)
        (d / "logical-design.md").write_text(
            "# Logical Design\n\n"
            "## users\n\n"
            "| 컬럼 | 타입 | 키 |\n"
            "| ---- | ---- | -- |\n"
            "| id   | BIGINT | PK |\n"
            "| name | VARCHAR | |\n\n"
            "## orders\n\n"
            "| 컬럼 | 타입 | 키 |\n"
            "| ---- | ---- | -- |\n"
            "| id      | BIGINT | PK |\n"
            "| user_id | BIGINT | FK references users.id |\n\n"
            "## 인덱스\n- INDEX idx_user_id ON orders(user_id)\n",
            encoding="utf-8",
        )
        out = _run_in(root)
        assert "[PASS]" in out, f"expected [PASS], got: {out[:500]}"
        assert "[FAIL]" not in out, f"unexpected [FAIL], got: {out[:500]}"


def test_negative_path_no_keys_or_index():
    """logical-design.md without PK/FK/INDEX → [FAIL]."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        d = root / ".claude" / "design" / "er"
        d.mkdir(parents=True)
        (d / "logical-design.md").write_text(
            "# Logical Design\n\nDocument is empty.\n",
            encoding="utf-8",
        )
        out = _run_in(root)
        assert "[FAIL]" in out, f"expected [FAIL] for missing PK/FK/INDEX, got: {out[:400]}"


def main() -> int:
    tests = [
        test_empty_cwd_skips_cleanly,
        test_happy_path_complete_logical,
        test_negative_path_no_keys_or_index,
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
