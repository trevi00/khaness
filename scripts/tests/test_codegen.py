#!/usr/bin/env python3
"""Tests for validators/codegen.py — empty/happy/negative paths."""
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

from validators import codegen  # noqa: E402


def _run_in(cwd: Path) -> str:
    saved = os.getcwd()
    buf = io.StringIO()
    try:
        os.chdir(cwd)
        with redirect_stdout(buf):
            codegen.main()
    finally:
        os.chdir(saved)
    return buf.getvalue()


def test_empty_cwd_skips_cleanly():
    with tempfile.TemporaryDirectory() as td:
        out = _run_in(Path(td))
        assert "[PASS]" in out, f"expected [PASS] on empty cwd, got: {out[:200]}"


def test_happy_path_with_controller_service_mapper():
    """Java project with Controller/Service/Mapper — no [FAIL]."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        pkg = root / "src" / "main" / "java" / "com" / "ex"
        pkg.mkdir(parents=True)
        (pkg / "FooController.java").write_text(
            "package com.ex;\n"
            "public class FooController {\n"
            "    private final FooService fooService;\n"
            "    public FooController(FooService s) { this.fooService = s; }\n"
            "}\n",
            encoding="utf-8",
        )
        (pkg / "FooService.java").write_text(
            "package com.ex;\npublic class FooService {}\n",
            encoding="utf-8",
        )
        (pkg / "FooMapper.java").write_text(
            "package com.ex;\npublic interface FooMapper {}\n",
            encoding="utf-8",
        )
        out = _run_in(root)
        assert "[PASS]" in out, f"expected [PASS], got: {out[:400]}"
        assert "[FAIL]" not in out, f"unexpected [FAIL] for full stack, got: {out[:400]}"


def test_negative_path_controller_only():
    """Only Controller, no Service/Mapper → [FAIL]."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        pkg = root / "src" / "main" / "java" / "com" / "ex"
        pkg.mkdir(parents=True)
        (pkg / "FooController.java").write_text(
            "package com.ex;\npublic class FooController {}\n",
            encoding="utf-8",
        )
        out = _run_in(root)
        assert "[FAIL]" in out, f"expected [FAIL] for missing Service, got: {out[:400]}"


def main() -> int:
    tests = [
        test_empty_cwd_skips_cleanly,
        test_happy_path_with_controller_service_mapper,
        test_negative_path_controller_only,
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
