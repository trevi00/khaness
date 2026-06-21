#!/usr/bin/env python3
"""Unit-test wrapper: drives the Node `quick-merge-back` test harness.

run_units.py discovers tests/test_*.py exposing main()->int. This wraps the
real multi-scenario harness at
  get-shit-done/bin/lib/__tests__/merge-back.test.cjs
which builds real temp git repos + worktrees and asserts on the final main tree
(the HARD PREREQUISITE from worktree-merge-back-REDESIGN-SPEC.md).

node is a hard dependency of gsd-tools itself, so its absence is a genuine
[SKIP] (not a failure) — the harness is only meaningful where gsd-tools runs.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_SCRIPTS = _HERE.parent.parent           # <home>/scripts
_HOME = _SCRIPTS.parent                  # <home>
_NODE_TEST = _HOME / "get-shit-done" / "bin" / "lib" / "__tests__" / "merge-back.test.cjs"


def main() -> int:
    node = shutil.which("node")
    if not node:
        print("[SKIP-SUITE] node unavailable — quick-merge-back scenarios NOT exercised (run_units tallies this as skipped, not passed)")
        return 0
    if not _NODE_TEST.is_file():
        print(f"[FAIL] merge-back.test.cjs not found at {_NODE_TEST}")
        return 1
    try:
        # Keep this UNDER run_units._run_subprocess's 60s SIGKILL so a genuinely
        # slow run self-reports a clean [FAIL] (with diagnostics) instead of being
        # hard-killed with no output. Actual runtime is ~15s — 50s is ample margin.
        proc = subprocess.run(
            [node, "--test", str(_NODE_TEST)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=50,
        )
    except subprocess.TimeoutExpired:
        print("[FAIL] quick-merge-back node:test timed out after 180s")
        return 1
    if proc.returncode == 0:
        # surface the node TAP summary line(s) for visibility
        for line in proc.stdout.splitlines():
            if line.startswith("# ") and ("tests" in line or "pass" in line or "fail" in line):
                print(f"  node: {line}")
        print("[OK] quick-merge-back: all scenarios passed")
        return 0
    print("[FAIL] quick-merge-back node:test failed")
    tail = (proc.stdout + "\n" + proc.stderr).strip().splitlines()
    for line in tail[-40:]:
        print(f"  {line}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
