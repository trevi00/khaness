#!/usr/bin/env python3
"""Tests for lib/thin_skill_advisor.py — prompt-time thin-skill advisory (M2a).

Synthetic skill-match telemetry drives the classifier deterministically, then the
advisory is asserted to fire ONLY when a full-body-injected skill is a historical
thin-fire / false-positive candidate. Also pins the single-source contract: the
constants the M7 audit imports are the ones this module owns.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _ev(*entries):
    """A skill-match telemetry event: top=[{name, score}, ...]."""
    return {"top": [{"name": n, "score": s} for n, s in entries]}


def _thin_history(name, n=10):
    """n events where `name` scores 1 (thin) every time → FP candidate."""
    return [_ev((name, 1)) for _ in range(n)]


def test_is_fp_candidate_predicate():
    from lib.thin_skill_advisor import is_fp_candidate
    assert is_fp_candidate(count=5, thin_rate=0.9, median=1) is True
    assert is_fp_candidate(count=2, thin_rate=1.0, median=1) is False     # too few samples
    assert is_fp_candidate(count=9, thin_rate=0.5, median=1) is False     # not thin enough
    assert is_fp_candidate(count=9, thin_rate=0.9, median=3) is False     # median above band


def test_thin_fire_stats_aggregates():
    from lib.thin_skill_advisor import thin_fire_stats
    events = [_ev(("a", 1), ("b", 5)), _ev(("a", 1)), _ev(("a", 2))]
    stats = thin_fire_stats(events)
    assert stats["a"]["count"] == 3
    assert stats["a"]["thin_rate"] == 1.0      # all <= 2
    assert stats["b"]["thin_rate"] == 0.0      # 5 > 2
    assert stats["b"]["count"] == 1


def test_fp_candidate_names():
    from lib.thin_skill_advisor import fp_candidate_names
    events = _thin_history("broad.md", 10) + [_ev(("precise.md", 6)) for _ in range(10)]
    fps = fp_candidate_names(events)
    assert "broad.md" in fps
    assert "precise.md" not in fps


def test_advisory_fires_for_injected_fp_candidate():
    from lib.thin_skill_advisor import injected_thin_advisory
    events = _thin_history("broad.md", 10)
    # broad.md spiked high enough THIS prompt to be full-body-injected
    adv = injected_thin_advisory(["broad.md", "fine.md"], events)
    assert adv is not None
    assert "broad.md" in adv
    assert "fine.md" not in adv
    assert "skill_telemetry_audit" in adv      # points to the audit CLI


def test_advisory_silent_when_no_injected_candidate():
    from lib.thin_skill_advisor import injected_thin_advisory
    events = _thin_history("broad.md", 10)
    # broad.md is thin, but it is NOT injected this prompt → silent
    assert injected_thin_advisory(["fine.md", "other.md"], events) is None
    # nothing injected → silent
    assert injected_thin_advisory([], events) is None
    # injected skill has no thin history → silent
    assert injected_thin_advisory(["never-seen.md"], events) is None


def test_advisory_dedups_and_sorts():
    from lib.thin_skill_advisor import injected_thin_advisory
    events = _thin_history("zeta.md", 10) + _thin_history("alpha.md", 10)
    adv = injected_thin_advisory(["zeta.md", "alpha.md", "zeta.md"], events)
    assert adv is not None
    # alpha listed before zeta, each once
    assert adv.index("alpha.md") < adv.index("zeta.md")
    assert adv.count("zeta.md") == 1


def test_max_events_bounds_history():
    from lib.thin_skill_advisor import injected_thin_advisory
    # 10 thin events for old.md, then 5 non-thin for new.md; cap to last 5 → old.md
    # falls out of the window and is no longer a candidate.
    events = _thin_history("old.md", 10) + [_ev(("new.md", 6)) for _ in range(5)]
    assert injected_thin_advisory(["old.md"], events, max_events=5) is None
    # with full window old.md is a candidate again
    assert injected_thin_advisory(["old.md"], events, max_events=None) is not None


def test_failsoft_on_garbage_events():
    from lib.thin_skill_advisor import thin_fire_stats, injected_thin_advisory
    garbage = [None, 5, {"top": "not-a-list"}, {"top": [None, {"name": 1, "score": "x"}]}, {}]
    assert thin_fire_stats(garbage) == {}
    assert injected_thin_advisory(["x.md"], garbage) is None


def test_single_source_constants_match_m7_cli():
    """The M7 audit CLI must import its thin constants from this module (no drift)."""
    from lib import thin_skill_advisor as adv
    from cli import skill_telemetry_audit as m7
    assert m7.THIN_SCORE_CEILING is adv.THIN_SCORE_CEILING
    assert m7.MIN_SAMPLES is adv.MIN_SAMPLES
    assert m7.FP_THIN_RATE is adv.FP_THIN_RATE


def main() -> int:
    tests = [
        test_is_fp_candidate_predicate,
        test_thin_fire_stats_aggregates,
        test_fp_candidate_names,
        test_advisory_fires_for_injected_fp_candidate,
        test_advisory_silent_when_no_injected_candidate,
        test_advisory_dedups_and_sorts,
        test_max_events_bounds_history,
        test_failsoft_on_garbage_events,
        test_single_source_constants_match_m7_cli,
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
