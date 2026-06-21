#!/usr/bin/env python3
"""Tests for M22 telemetry→threshold-tuning: registry, metrics, gate, proposer, policy.

Converged design debate-1781603679-a14912. Auto-discovered by run_units.py via main()->int.
"""
from __future__ import annotations

import importlib
import math
import sys
import tempfile
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.calibration import threshold_registry as reg  # noqa: E402
from lib.calibration import threshold_metrics as tm  # noqa: E402
from lib.no_degradation_gate import evaluate_threshold_change, ThresholdGateResult  # noqa: E402


def _ev(ts, entries):
    return {"ts": ts, "top": [{"name": f"k{i}", "score": s, "body_chars": bc}
                              for i, (s, bc) in enumerate(entries)]}


def _corpus(n=40, pattern=((3, 500), (3, 500), (5, 500), (6, 500))):
    return [_ev(f"2026-06-1{0 + i // (n // 2)}T00:00:{i % 60:02d}Z", list(pattern)) for i in range(n)]


_BOUNDARY = "2026-06-11T00:00:00Z"


# ---- registry (D1) ----

def test_registry_disjoint_from_locked():
    reg.assert_locked_disjoint()  # must not raise
    assert not ({e.qualified() for e in reg.REGISTRY.values()} & reg.LOCKED_DENY)


def test_assert_locked_disjoint_raises_on_overlap():
    bad = reg.TunableThreshold(
        name="x", module="lib.repeat_error_tracker", constant="STRIKE_THRESHOLD",
        default=2, telemetry_source="t", target_metric="a", guard_metric="b",
        direction_safety="either", step=1, process_lifetime="short_hook")
    with mock.patch.dict(reg.REGISTRY, {"x": bad}, clear=False):
        try:
            reg.assert_locked_disjoint()
            raise AssertionError("expected ValueError on locked overlap")
        except ValueError as e:
            assert "LOCKED_DENY" in str(e)


def test_is_locked():
    assert reg.is_locked("lib.repeat_error_tracker.STRIKE_THRESHOLD") is True
    assert reg.is_locked("handlers.prompt.skill_match.FULL_BODY_MIN_SCORE") is False


# ---- metrics (D3 oracle) ----

def test_admit_precision_raise_improves_on_borderline_corpus():
    evs = _corpus()
    assert tm.full_body_admit_precision(evs, 4) > tm.full_body_admit_precision(evs, 3)


def test_non_truncation_rate_nan_without_body_chars():
    evs = [{"ts": "x", "top": [{"name": "a", "score": 3}]}]  # no body_chars
    assert math.isnan(tm.non_truncation_rate(evs, 3))


def test_split_by_holdout_half_open():
    evs = [_ev("2026-06-10T00:00:00Z", [(3, 1)]), _ev("2026-06-11T00:00:00Z", [(3, 1)]),
           _ev("2026-06-12T00:00:00Z", [(3, 1)])]
    trailing, holdout = tm.split_by_holdout(evs, _BOUNDARY)
    assert len(trailing) == 1 and len(holdout) == 2  # boundary itself is held-out (>=)


# ---- gate (D3) ----

def test_gate_accepts_generalizing_raise():
    g = evaluate_threshold_change(events=_corpus(), old_value=3, proposed_value=4,
                                  metric_fn=tm.full_body_admit_precision,
                                  guard_fn=tm.non_truncation_rate, holdout_boundary=_BOUNDARY, min_corpus=5)
    assert isinstance(g, ThresholdGateResult) and g.accept is True


def test_gate_fail_closed_corpus_too_small():
    g = evaluate_threshold_change(events=_corpus()[:3], old_value=3, proposed_value=4,
                                  metric_fn=tm.full_body_admit_precision,
                                  guard_fn=tm.non_truncation_rate, holdout_boundary=_BOUNDARY, min_corpus=5)
    assert g.accept is False and g.reason == "corpus_too_small"


def test_gate_fail_closed_non_finite_guard():
    # guard NaN (no body_chars) -> non_finite -> no accept
    evs = [_ev(f"2026-06-1{0 + i // 20}T00:00:{i:02d}Z", [(3, None)]) for i in range(40)]
    for e in evs:
        for t in e["top"]:
            t.pop("body_chars", None)
    g = evaluate_threshold_change(events=evs, old_value=3, proposed_value=4,
                                  metric_fn=tm.full_body_admit_precision,
                                  guard_fn=tm.non_truncation_rate, holdout_boundary=_BOUNDARY, min_corpus=5)
    assert g.accept is False and g.reason == "non_finite_metric"


def test_gate_fail_closed_replay_error():
    def boom(events, threshold):
        raise RuntimeError("boom")
    g = evaluate_threshold_change(events=_corpus(), old_value=3, proposed_value=4,
                                  metric_fn=boom, guard_fn=tm.non_truncation_rate,
                                  holdout_boundary=_BOUNDARY, min_corpus=5)
    assert g.accept is False and g.reason.startswith("replay_error")


def test_gate_unresolved_metric_fn():
    g = evaluate_threshold_change(events=_corpus(), old_value=3, proposed_value=4,
                                  metric_fn=None, guard_fn=tm.non_truncation_rate,
                                  holdout_boundary=_BOUNDARY, min_corpus=5)
    assert g.accept is False and g.reason == "unresolved_metric_fn"


# ---- proposer + policy (D2/D4) ----

def _with_temp_state(fn):
    with tempfile.TemporaryDirectory() as td:
        import lib.paths as paths
        with mock.patch.object(paths, "STATE_DIR", Path(td) / "state"), \
                mock.patch.object(paths, "CLAUDE_HOME", Path(td)):
            import lib.calibration.threshold_proposer as tp
            import lib.threshold_policy as pol
            importlib.reload(tp)
            importlib.reload(pol)
            fn(tp, pol)


def test_proposer_min_sample_skips():
    def body(tp, pol):
        props = tp.propose_threshold_changes(events_by_source={"skill-match": _corpus(4)}, min_sample=10)
        assert all(p.name != "skill_match.FULL_BODY_MIN_SCORE" for p in props)
    _with_temp_state(body)


def test_proposer_accepts_and_emits_ready_flag():
    def body(tp, pol):
        props = tp.propose_threshold_changes(events_by_source={"skill-match": _corpus()}, min_sample=5)
        fb = [p for p in props if p.name == "skill_match.FULL_BODY_MIN_SCORE"]
        assert fb and fb[0].suggested == 4 and fb[0].gate_result.accept is True
        assert pol._ready_flag_path("skill_match.FULL_BODY_MIN_SCORE").exists()
    _with_temp_state(body)


def test_policy_resolve_default_and_token_apply():
    def body(tp, pol):
        assert pol.resolve_threshold("skill_match.FULL_BODY_MIN_SCORE", 3) == 3  # no override
        # unregistered name -> default, never crashes
        assert pol.resolve_threshold("not.a.real.threshold", 9) == 9
        tp.propose_threshold_changes(events_by_source={"skill-match": _corpus()}, min_sample=5)
        # wrong token
        try:
            pol.apply_threshold_override("skill_match.FULL_BODY_MIN_SCORE", 4, token="wrong")
            raise AssertionError("expected PermissionError")
        except PermissionError:
            pass
        # correct token (risky 'either' direction → graduate-validator + ready-flag)
        assert pol.apply_threshold_override("skill_match.FULL_BODY_MIN_SCORE", 4, token="graduate-validator") is True
        assert pol.resolve_threshold("skill_match.FULL_BODY_MIN_SCORE", 3) == 4
        # ready-flag consumed -> a second risky apply refuses
        try:
            pol.apply_threshold_override("skill_match.FULL_BODY_MIN_SCORE", 5, token="graduate-validator")
            raise AssertionError("expected PermissionError (consumed ready-flag)")
        except PermissionError:
            pass
    _with_temp_state(body)


def test_policy_apply_locked_name_raises():
    def body(tp, pol):
        try:
            pol.apply_threshold_override("lib.repeat_error_tracker.STRIKE_THRESHOLD", 5, token="graduate-validator")
            raise AssertionError("expected ValueError")
        except ValueError:
            pass
    _with_temp_state(body)


def test_policy_idempotent_noop():
    def body(tp, pol):
        # applying the current default value (after proposer emits ready-flag) — but value
        # already == default resolution -> no-op returns False without needing a token.
        assert pol.apply_threshold_override("skill_match.FULL_BODY_MIN_SCORE", 3, token=None) is False
    _with_temp_state(body)


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
