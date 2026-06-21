#!/usr/bin/env python3
"""Wire lib/meta_rules.py::_self_check() into the run_units regression.

meta_rules ships a 22-assertion inline _self_check() (mutation-token meta rules)
reachable only via `python -m lib.meta_rules --self-check` — no tests/test_*.py
with a main() existed, so run_units silently SKIPPED it. This thin wrapper makes
the suite a first-class regression (self-verifying-harness follow-up:
dead _self_check wiring, 2026-06-04).
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def main() -> int:
    from lib import meta_rules as _m
    rc = _m._self_check()
    return rc if isinstance(rc, int) else 0


if __name__ == "__main__":
    sys.exit(main())
