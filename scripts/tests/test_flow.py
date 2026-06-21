#!/usr/bin/env python3
"""Tests for validators/flow.py — empty/happy/negative paths."""
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

from validators import flow  # noqa: E402


def _run_in(cwd: Path) -> str:
    saved = os.getcwd()
    buf = io.StringIO()
    try:
        os.chdir(cwd)
        with redirect_stdout(buf):
            flow.main()
    finally:
        os.chdir(saved)
    return buf.getvalue()


def test_empty_cwd_skips_cleanly():
    with tempfile.TemporaryDirectory() as td:
        out = _run_in(Path(td))
        assert "[PASS]" in out, f"expected [PASS] on empty cwd, got: {out[:200]}"


def test_happy_path_flow_with_mermaid():
    """flows/*.md with mermaid block → no [FAIL]."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        flows_dir = root / ".claude" / "design" / "flows"
        flows_dir.mkdir(parents=True)
        (flows_dir / "login.md").write_text(
            "# Login Flow\n\n"
            "```mermaid\n"
            "flowchart TD\n"
            "  A[Start] --> B[Login]\n"
            "```\n",
            encoding="utf-8",
        )
        out = _run_in(root)
        assert "[PASS]" in out, f"expected [PASS], got: {out[:400]}"
        assert "[FAIL]" not in out, f"unexpected [FAIL], got: {out[:400]}"


def test_negative_path_flow_without_mermaid():
    """flows/*.md missing mermaid block → [FAIL]."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        flows_dir = root / ".claude" / "design" / "flows"
        flows_dir.mkdir(parents=True)
        (flows_dir / "login.md").write_text(
            "# Login Flow\n\nThis is a flow document without diagrams.\n",
            encoding="utf-8",
        )
        out = _run_in(root)
        assert "[FAIL]" in out, f"expected [FAIL] for missing mermaid, got: {out[:400]}"


def main() -> int:
    tests = [
        test_empty_cwd_skips_cleanly,
        test_happy_path_flow_with_mermaid,
        test_negative_path_flow_without_mermaid,
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
