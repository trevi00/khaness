#!/usr/bin/env python3
"""Tests for cli.skill_telemetry_audit — M7 skill-match weight/FP audit.

Auto-discovered by run_units.py via main() -> int.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import cli.skill_telemetry_audit as audit_cli  # noqa: E402


def _ev(top: list[dict]) -> dict:
    return {"ts": "2026-06-16T00:00:00Z", "top": top}


def test_empty_telemetry_graceful():
    rep = audit_cli.audit([])
    assert rep["invocations"] == 0 and rep["skills"] == {}
    assert rep["false_positive_candidates"] == []
    # render must not crash on empty
    assert "no skill-match telemetry" in audit_cli.render_text(rep)


def test_per_skill_score_aggregation():
    events = [
        _ev([{"name": "backend", "score": 5, "dims": ["intent:API"]}]),
        _ev([{"name": "backend", "score": 3, "dims": ["kw:db"]}]),
        _ev([{"name": "backend", "score": 1, "dims": ["kw:test"]}]),
    ]
    rep = audit_cli.audit(events)
    b = rep["skills"]["backend"]
    assert b["count"] == 3
    assert b["score_min"] == 1 and b["score_max"] == 5 and b["score_median"] == 3
    assert b["thin_rate"] == round(1 / 3, 3)  # only the score-1 match is thin


def test_false_positive_candidate_flagged():
    # fires 4x, all thin (<=2) -> FP candidate; dominant dim = kw
    events = [_ev([{"name": "example_gateway", "score": s, "dims": ["kw:approve"]}])
              for s in (1, 2, 2, 1)]
    rep = audit_cli.audit(events)
    fps = rep["false_positive_candidates"]
    assert len(fps) == 1 and fps[0]["name"] == "example_gateway"
    assert fps[0]["dominant_dim"] == "kw"
    assert "Narrow the kw surface" in fps[0]["reason"]


def test_strong_skill_not_flagged():
    events = [_ev([{"name": "code-quality", "score": s, "dims": ["intent:refactor", "kw:clean"]}])
              for s in (6, 5, 4)]
    rep = audit_cli.audit(events)
    assert rep["false_positive_candidates"] == []


def test_below_min_samples_not_flagged():
    # only 2 thin matches (< MIN_SAMPLES=3) -> not judged
    events = [_ev([{"name": "x", "score": 1, "dims": ["kw:a"]}]),
              _ev([{"name": "x", "score": 2, "dims": ["kw:a"]}])]
    rep = audit_cli.audit(events)
    assert rep["false_positive_candidates"] == []


def test_dim_weight_categories():
    events = [
        _ev([{"name": "a", "score": 3, "dims": ["intent:x", "kw:y"]}]),
        _ev([{"name": "b", "score": 4, "dims": ["path:src/z", "pat:spring"]}]),
    ]
    rep = audit_cli.audit(events)
    dw = rep["dim_weight"]
    assert dw.get("intent") == 1 and dw.get("kw") == 1
    assert dw.get("path") == 1 and dw.get("pat") == 1


def test_dims_missing_backward_compat():
    # old telemetry (pre-M7) has no 'dims' key -> no crash, dim_weight empty
    events = [_ev([{"name": "old", "score": 2}]) for _ in range(3)]
    rep = audit_cli.audit(events)
    assert rep["skills"]["old"]["count"] == 3
    assert rep["skills"]["old"]["dominant_dim"] is None
    assert rep["dim_weight"] == {}
    # still FP-flaggable from score alone
    assert rep["false_positive_candidates"][0]["name"] == "old"


def test_main_json_runs():
    events = [_ev([{"name": "a", "score": 4, "dims": ["intent:x"]}])]
    with mock.patch.object(audit_cli, "iter_events", return_value=iter(events)):
        rc = audit_cli.main(["--json"])
    assert rc == 0


def test_main_bad_since_exit_2():
    with mock.patch.object(audit_cli, "iter_events", return_value=iter([])):
        rc = audit_cli.main(["--since", "10x"])
    assert rc == 2


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
