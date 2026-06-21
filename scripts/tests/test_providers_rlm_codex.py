#!/usr/bin/env python3
"""Wire lib/providers/rlm_codex.py::_self_check() into the run_units regression.

The rlm_codex provider ships an inline _self_check() reachable only via
`python -m lib.providers.rlm_codex --self-check` — no tests/test_*.py with a
main() existed, so run_units silently SKIPPED it. This thin wrapper makes the
suite a first-class regression (M4: dead _self_check wiring, follows
tests/test_meta_rules.py pattern).
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def main() -> int:
    from lib.providers import rlm_codex as _m
    rc = _m._self_check()
    return rc if isinstance(rc, int) else 0


if __name__ == "__main__":
    sys.exit(main())
