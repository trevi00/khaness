#!/usr/bin/env python3
"""Wire cli/sensor_anomaly.py::_self_check() into the run_units regression.

sensor_anomaly ships an inline _self_check() reachable only via its __main__
--self-check; no tests/test_*.py invoked it, so run_units silently skipped it.
Thin wrapper (harness-full-review rank 5; test_evaluator_dispatcher_selfcheck.py precedent).
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def main() -> int:
    from cli import sensor_anomaly as _m
    rc = _m._self_check()
    return rc if isinstance(rc, int) else 0


if __name__ == "__main__":
    sys.exit(main())
