#!/usr/bin/env python3
"""test_depth — surface≠real test-depth advisory (M26).

Codifies feedback_surface_vs_real_validation for the harness's OWN suite: a test that
exercises code but makes NO assertion only verifies "did not crash" — a SURFACE signal, not
REAL behavior. Such a test passes even when the function under test returns the wrong value.

This validator flags every `test_*` function whose body contains NO depth signal — no
`assert`, no `self.assert*()`/`*.assert*()`, no `pytest.raises`/`*.raises(...)`, and no
`raise` (a hand-rolled failure). It is ADVISORY ([WARN], does not trip run_all's failure
regex), graduating to blocking only via the `graduate-validator` token once the suite is
clean for a streak (roadmap M26: advisory→graduate). Conservative (counts ANY assert-shaped
or raise signal) to keep false positives low — it fires only on genuinely empty tests.

Caller contract (validators/__init__.py): main() -> None, reads the harness tests/ dir,
prints [PASS]/[WARN], never raises.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

for _s in (sys.stdin, sys.stdout):
    _r = getattr(_s, "reconfigure", None)
    if _r:
        try:
            _r(encoding="utf-8")
        except Exception:
            pass

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

_TESTS_DIR = _SCRIPTS / "tests"


def _has_depth_signal(fn: ast.FunctionDef) -> bool:
    """True iff the function body carries a real failure signal — it can FAIL on wrong
    behavior, not just on a crash. Recognizes both conventions used in this harness:
      - `assert` / `self.assert*()` / `*.raises(...)` / `*.fail()` / `raise`
      - the print-based pass/fail convention: a `[FAIL]` string literal (the autodiscover
        runners scan stdout for `[FAIL]`, so `print("[FAIL] ...")` IS the assertion).
    Counting both keeps false positives low — it fires only on genuinely empty tests."""
    for n in ast.walk(fn):
        if isinstance(n, (ast.Assert, ast.Raise)):
            return True
        if isinstance(n, ast.Call):
            fname = ""
            if isinstance(n.func, ast.Attribute):
                fname = n.func.attr
            elif isinstance(n.func, ast.Name):
                fname = n.func.id
            low = fname.lower()
            # `*.raises(...)` / `*.fail()` / assert* methods, OR a module-local assertion
            # helper named check/expect/verify/require/ensure/assert (e.g. `_check(cond, msg)`).
            if (low.startswith("assert") or "check" in low or "expect" in low
                    or "verify" in low or fname in ("raises", "fail")
                    or low.startswith(("require_", "ensure_"))):
                return True
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and "[FAIL]" in n.value:
            return True
    return False


def find_surface_only(tests_dir: Path) -> list[tuple[str, str]]:
    """Return [(file, test_func)] for assertion-free `test_*` functions. Pure (testable)."""
    out: list[tuple[str, str]] = []
    if not tests_dir.is_dir():
        return out
    for f in sorted(tests_dir.glob("test_*.py")):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                if not _has_depth_signal(node):
                    out.append((f.name, node.name))
    return out


def main() -> None:
    surface = find_surface_only(_TESTS_DIR)
    if not surface:
        print("[PASS] test_depth: no surface-only (assertion-free) test functions")
        return
    for fn_file, fn in surface:
        print(
            f"[WARN] test_depth: {fn_file}::{fn} has no assertion/raise — verifies only "
            f"'did not crash' (surface, not real behavior). Add a behavioral assertion."
        )
    try:
        from lib.logging import log_telemetry
        log_telemetry("test-depth-surface-only", {
            "count": len(surface),
            "samples": [f"{a}::{b}" for a, b in surface[:10]],
        })
    except Exception:
        pass


if __name__ == "__main__":
    main()
