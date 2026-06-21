#!/usr/bin/env python3
"""Wire lib/evaluator_dispatcher.py::_self_check() into the run_units regression.

evaluator_dispatcher ships an inline _self_check() (89 assertions covering the
v15.35.1 ensemble wiring + D7 ledger + S6 emit-helper surface) reachable only via
`python -m lib.evaluator_dispatcher --self-check` — no tests/test_*.py with a
main() invoked it (test_evaluator_dispatcher.py has its own TESTS list that does
NOT call _self_check), so run_units silently SKIPPED 840 LOC of assertions. This
thin wrapper makes the suite a first-class regression.

Decided by debate-1782018481-b85aa8 (converged gen-2, snapshot sha 755f465b):
the package SPLIT was DEFERRED; the de-bulk = wiring this dead self-check is the
sole accepted action (D2). Mirrors the tests/test_ensemble_evaluator.py sibling
precedent (M4: dead _self_check wiring).
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def main() -> int:
    from lib import evaluator_dispatcher as _m
    rc = _m._self_check()
    return rc if isinstance(rc, int) else 0


if __name__ == "__main__":
    sys.exit(main())
