#!/usr/bin/env python3
"""Tests for the threshold_registry_locked validator (M22 D1, run_all gate).

Exercises the validator's PASS path (live REGISTRY disjoint from LOCKED_DENY) and its FAIL
path (a locked invariant mistakenly registered). Un-skips the validator in run_all (the
M3 atlas-validator precedent: a validator stays skipped until a dedicated test exists).
Auto-discovered via main() -> int.
"""
from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import validators.threshold_registry_locked as vmod  # noqa: E402
from lib.calibration import threshold_registry as reg  # noqa: E402


def _run() -> str:
    buf = io.StringIO()
    with redirect_stdout(buf):
        vmod.main()
    return buf.getvalue()


def test_pass_on_disjoint_registry():
    out = _run()
    assert "[PASS]" in out and "[FAIL]" not in out, out


def test_fail_when_locked_invariant_registered():
    bad = reg.TunableThreshold(
        name="x", module="lib.repeat_error_tracker", constant="STRIKE_THRESHOLD",
        default=2, telemetry_source="t", target_metric="a", guard_metric="b",
        direction_safety="either", step=1, process_lifetime="short_hook")
    with mock.patch.dict(reg.REGISTRY, {"x": bad}, clear=False):
        out = _run()
    assert "[FAIL]" in out and "STRIKE_THRESHOLD" in out, out


def test_validator_registered_in_builtin():
    from validators import _BUILTIN
    assert "threshold_registry_locked" in _BUILTIN


def main() -> int:
    failed = 0
    n = 0
    for name, obj in list(globals().items()):
        if not name.startswith("test_"):
            continue
        n += 1
        try:
            obj()
            print(f"  [OK] {name}")
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {name}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  [ERR] {name}: {e!r}")
    if failed:
        print(f"\n{failed}/{n} failed")
        return 1
    print(f"\n[OK] {n} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
