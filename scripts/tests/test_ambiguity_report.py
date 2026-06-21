#!/usr/bin/env python3
"""Tests for lib/ambiguity_report.py — read-only per-component ambiguity surface."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


class _Score:
    """Duck-typed AmbiguityScore (avoids re-running the real scorer)."""
    def __init__(self, gap, ent, mark, *, threshold=0.2,
                 weights=(0.5, 0.3, 0.2)):
        self.coverage_gap = gap
        self.lexical_entropy = ent
        self.unknown_marker_density = mark
        self.weights = weights
        self.aggregate = weights[0] * gap + weights[1] * ent + weights[2] * mark
        self.threshold = threshold
        self.passes_gate = self.aggregate <= threshold


def test_breakdown_identifies_dominant_axis():
    from lib.ambiguity_report import component_breakdown
    # coverage_gap high, weight 0.5 -> dominant contribution
    s = _Score(0.8, 0.2, 0.1)
    b = component_breakdown(s)
    assert b["dominant_axis"] == "coverage_gap"
    assert b["axes"]["coverage_gap"]["contribution"] == round(0.5 * 0.8, 4)
    assert b["passes_gate"] is False


def test_breakdown_passes_gate_low_ambiguity():
    from lib.ambiguity_report import component_breakdown
    s = _Score(0.1, 0.1, 0.1)
    b = component_breakdown(s)
    assert b["passes_gate"] is True


def test_delta_detects_improvement_and_regression():
    from lib.ambiguity_report import component_delta
    prev = _Score(0.8, 0.4, 0.2)
    cur = _Score(0.3, 0.5, 0.2)   # coverage improved, entropy regressed
    d = component_delta(prev, cur)
    assert d["axes_delta"]["coverage_gap"] == round(0.3 - 0.8, 4)
    assert "lexical_entropy" in d["regressed_axes"]
    assert d["improved"] is True   # aggregate dropped overall (coverage weight dominates)


def test_render_breakdown_and_round_strings():
    from lib.ambiguity_report import render_breakdown, render_round
    s_hi = _Score(0.8, 0.2, 0.1)
    out = render_breakdown(s_hi)
    assert "coverage_gap" in out and "focus here" in out  # dominant + failing -> focus hint
    s_lo = _Score(0.2, 0.1, 0.05)
    r = render_round(s_hi, s_lo)
    assert "ambiguity" in r and ("improved" in r or "no change" in r)


def main() -> int:
    tests = [
        test_breakdown_identifies_dominant_axis,
        test_breakdown_passes_gate_low_ambiguity,
        test_delta_detects_improvement_and_regression,
        test_render_breakdown_and_round_strings,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  [OK] {t.__name__}")
        except Exception as e:
            import traceback
            print(f"  [FAIL] {t.__name__}: {type(e).__name__}: {e}")
            traceback.print_exc()
            failed += 1
    if failed == 0:
        print(f"[OK] {len(tests)} tests passed")
        return 0
    print(f"[FAIL] {failed}/{len(tests)} tests failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
