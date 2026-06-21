#!/usr/bin/env python3
"""Tests for lib.no_degradation_gate — the M18 collapsed skill_gotcha acceptance gate.

accept == (probe_passed AND secret_clean). Auto-discovered by run_units.py via main().
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.no_degradation_gate import evaluate_skill_gotcha, GateResult  # noqa: E402
from lib.repro_probe import Probe  # noqa: E402

_PROBE = Probe("a" * 16, "Bash", "sig")


def _cand(secret_clean: bool):
    return SimpleNamespace(secret_scan_clean=secret_clean)


def test_accept_when_probe_and_secret_clean():
    g = evaluate_skill_gotcha(_cand(True), _PROBE)
    assert isinstance(g, GateResult)
    assert g.accept is True and g.probe_passed is True and g.secret_clean is True


def test_reject_when_probe_none():
    g = evaluate_skill_gotcha(_cand(True), None)
    assert g.accept is False and g.probe_passed is False
    assert "escalate" in g.reason


def test_reject_when_secret_dirty():
    g = evaluate_skill_gotcha(_cand(False), _PROBE)
    assert g.accept is False and g.probe_passed is True and g.secret_clean is False
    assert "secret" in g.reason


def test_malformed_probe_fails_safe():
    bad = SimpleNamespace()  # no passed() method

    class Boom:
        def passed(self):
            raise RuntimeError("boom")

    g = evaluate_skill_gotcha(_cand(True), Boom())
    assert g.accept is False and "probe_eval_error" in g.reason


def test_malformed_candidate_fails_safe():
    # candidate missing secret_scan_clean -> getattr default False -> non-accept
    g = evaluate_skill_gotcha(object(), _PROBE)
    assert g.accept is False


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
