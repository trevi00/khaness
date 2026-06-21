#!/usr/bin/env python3
"""Tests for validators/ci.py — empty/happy/negative paths."""
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

from validators import ci  # noqa: E402


def _run_in(cwd: Path) -> str:
    saved = os.getcwd()
    buf = io.StringIO()
    try:
        os.chdir(cwd)
        with redirect_stdout(buf):
            ci.main()
    finally:
        os.chdir(saved)
    return buf.getvalue()


def test_empty_cwd_skips_cleanly():
    with tempfile.TemporaryDirectory() as td:
        out = _run_in(Path(td))
        assert "[PASS]" in out, f"expected [PASS] on empty cwd, got: {out[:200]}"


def test_happy_path_node_project_with_test_workflow():
    """Node project with CI workflow that includes npm test → [PASS]."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # Mark as Node project
        (root / "package.json").write_text('{"name":"x"}', encoding="utf-8")
        # Workflow with push trigger + npm test
        wf_dir = root / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text(
            "name: ci\n"
            "on:\n  push:\n    branches: [main]\n"
            "jobs:\n  build:\n    runs-on: ubuntu-latest\n"
            "    steps:\n      - run: npm install\n      - run: npm test\n",
            encoding="utf-8",
        )
        out = _run_in(root)
        assert "[PASS]" in out, f"expected [PASS] for valid Node CI, got: {out[:300]}"
        assert "[FAIL]" not in out, f"unexpected [FAIL] in valid CI, got: {out[:300]}"


def test_negative_path_workflows_dir_empty():
    """workflows/ dir exists but has no yml files → [FAIL]."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".github" / "workflows").mkdir(parents=True)
        out = _run_in(root)
        assert "[FAIL]" in out, f"expected [FAIL] for empty workflows dir, got: {out[:300]}"


def main() -> int:
    tests = [
        test_empty_cwd_skips_cleanly,
        test_happy_path_node_project_with_test_workflow,
        test_negative_path_workflows_dir_empty,
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
