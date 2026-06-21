#!/usr/bin/env python3
"""Wire lib/phase_events.py::_self_check() into the run_units regression.

phase_events ships a 29-assertion inline _self_check() (phase-tree event
handling) reachable only via `python -m lib.phase_events --self-check` — no
tests/test_*.py with a main() existed, so run_units silently SKIPPED it. This
thin wrapper makes the suite a first-class regression (self-verifying-harness
follow-up: dead _self_check wiring, 2026-06-04).
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def main() -> int:
    from lib import phase_events as _m
    rc = _m._self_check()
    return rc if isinstance(rc, int) else 0


if __name__ == "__main__":
    sys.exit(main())
