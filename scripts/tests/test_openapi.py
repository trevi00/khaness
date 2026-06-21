#!/usr/bin/env python3
"""Tests for validators/openapi.py — empty/happy/negative paths."""
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

from validators import openapi  # noqa: E402


def _run_in(cwd: Path) -> str:
    saved = os.getcwd()
    buf = io.StringIO()
    try:
        os.chdir(cwd)
        with redirect_stdout(buf):
            openapi.main()
    finally:
        os.chdir(saved)
    return buf.getvalue()


def test_empty_cwd_skips_cleanly():
    with tempfile.TemporaryDirectory() as td:
        out = _run_in(Path(td))
        assert "[PASS]" in out, f"expected [PASS] on empty cwd, got: {out[:200]}"


def test_happy_path_valid_openapi_yaml():
    """openapi.yaml with paths section + endpoints → no [FAIL]."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        d = root / ".claude" / "design" / "api"
        d.mkdir(parents=True)
        (d / "openapi.yaml").write_text(
            "openapi: 3.0.0\n"
            "info:\n  title: x\n  version: 1.0.0\n"
            "paths:\n"
            "  /api/users:\n"
            "    get:\n"
            "      summary: List\n"
            "  /api/users/{id}:\n"
            "    get:\n"
            "      summary: Get\n",
            encoding="utf-8",
        )
        out = _run_in(root)
        assert "[PASS]" in out, f"expected [PASS], got: {out[:400]}"
        assert "[FAIL]" not in out, f"unexpected [FAIL], got: {out[:400]}"


def test_negative_path_yaml_without_paths():
    """openapi.yaml with no paths section → [FAIL]."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        d = root / ".claude" / "design" / "api"
        d.mkdir(parents=True)
        (d / "openapi.yaml").write_text(
            "openapi: 3.0.0\ninfo:\n  title: empty\n  version: 1.0.0\n",
            encoding="utf-8",
        )
        out = _run_in(root)
        assert "[FAIL]" in out, f"expected [FAIL] for missing paths, got: {out[:400]}"


def main() -> int:
    tests = [
        test_empty_cwd_skips_cleanly,
        test_happy_path_valid_openapi_yaml,
        test_negative_path_yaml_without_paths,
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
