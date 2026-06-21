#!/usr/bin/env python3
"""Tests for validators/skeleton.py — empty/happy/negative paths."""
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

from validators import skeleton  # noqa: E402


def _run_in(cwd: Path) -> str:
    saved = os.getcwd()
    buf = io.StringIO()
    try:
        os.chdir(cwd)
        with redirect_stdout(buf):
            skeleton.main()
    finally:
        os.chdir(saved)
    return buf.getvalue()


def test_empty_cwd_skips_cleanly():
    with tempfile.TemporaryDirectory() as td:
        out = _run_in(Path(td))
        assert "[PASS]" in out, f"expected [PASS] on empty cwd, got: {out[:200]}"


def test_happy_path_full_skeleton():
    """src/main/java + build.gradle (spring-boot+test) + application.yml → no [FAIL]."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "src" / "main" / "java" / "com" / "ex").mkdir(parents=True)
        (root / "build.gradle").write_text(
            "plugins { id 'org.springframework.boot' version '3.2.0' }\n"
            "dependencies {\n"
            "  implementation 'org.springframework.boot:spring-boot-starter-web'\n"
            "  testImplementation 'org.springframework.boot:spring-boot-starter-test'\n"
            "}\n",
            encoding="utf-8",
        )
        res = root / "src" / "main" / "resources"
        res.mkdir(parents=True)
        (res / "application.yml").write_text("server:\n  port: 8080\n", encoding="utf-8")
        out = _run_in(root)
        assert "[PASS]" in out, f"expected [PASS], got: {out[:500]}"
        assert "[FAIL]" not in out, f"unexpected [FAIL], got: {out[:500]}"


def test_negative_path_no_build_file():
    """src/main/java exists but no build.gradle / pom.xml / application.yml → [FAIL]."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "src" / "main" / "java").mkdir(parents=True)
        out = _run_in(root)
        assert "[FAIL]" in out, f"expected [FAIL] for missing build file, got: {out[:400]}"


def main() -> int:
    tests = [
        test_empty_cwd_skips_cleanly,
        test_happy_path_full_skeleton,
        test_negative_path_no_build_file,
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
