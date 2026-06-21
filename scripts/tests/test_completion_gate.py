#!/usr/bin/env python3
"""Wire lib/completion_gate.py::_self_check() into the run_units regression +
fixture tests for the E2-enforcement freshness helpers (debate-1780564679).

completion_gate ships an inline _self_check() covering the autopilot goal-gate
truth table (decide_completion, including the require_evaluator E2-enforcement
cases) + count_orchestrator_iterations / iteration_started_ts /
latest_fresh_evaluator_verdict input-guard edge cases. _self_check has no I/O,
so the I/O-backed freshness behavior of iteration_started_ts +
latest_fresh_evaluator_verdict is covered here with tmp-dir fixtures (the
silent-skip gap this guards was: shared-sid autopilot completing on Tier-1
mechanical tests alone, completion_gate line 83 evaluator_verdict=None path).
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _redirect_state_dir(tmp: Path):
    from lib import paths as P
    P.STATE_DIR = tmp / "state"
    P.STATE_DIR.mkdir(parents=True, exist_ok=True)
    return P.STATE_DIR


def _write_iteration_started(state_dir: Path, sid: str, iso_ts: str) -> None:
    """Append an orchestrator iteration_started event with an explicit ISO ts
    (mirrors engine.orchestrator._append_event shape)."""
    d = state_dir / "orchestrator" / sid
    d.mkdir(parents=True, exist_ok=True)
    rec = {"ts": iso_ts, "type": "iteration_started", "sid": sid,
           "payload": {"iteration": 1}}
    with (d / "events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def _write_verdict_event(sid: str, verdict: str, ts: float,
                         event: str = "evaluator_verdict") -> None:
    """Write an axis_scores verdict event with an explicit ts (log_axis_event
    honors a caller-supplied ts via setdefault)."""
    from lib.axis_scores_log import log_axis_event
    ok = log_axis_event(sid, {"event": event, "verdict": verdict,
                              "phase_id": "phase_3.5", "ts": ts})
    assert ok, "log_axis_event should succeed"


# ---- iteration_started_ts ----

def test_iteration_started_ts_parses_iso_to_epoch():
    import calendar
    from lib.completion_gate import iteration_started_ts
    with tempfile.TemporaryDirectory() as td:
        sd = _redirect_state_dir(Path(td))
        sid = "orch-iso-1"
        _write_iteration_started(sd, sid, "2026-06-04T12:00:00Z")
        got = iteration_started_ts(sid)
        expected = float(calendar.timegm(
            time.strptime("2026-06-04T12:00:00Z", "%Y-%m-%dT%H:%M:%SZ")))
        assert got == expected, f"{got} != {expected}"


def test_iteration_started_ts_returns_max_of_multiple():
    from lib.completion_gate import iteration_started_ts
    with tempfile.TemporaryDirectory() as td:
        sd = _redirect_state_dir(Path(td))
        sid = "orch-iso-2"
        _write_iteration_started(sd, sid, "2026-06-04T12:00:00Z")
        _write_iteration_started(sd, sid, "2026-06-04T12:05:00Z")  # later
        _write_iteration_started(sd, sid, "2026-06-04T12:02:00Z")
        got = iteration_started_ts(sid)
        import calendar
        expected = float(calendar.timegm(
            time.strptime("2026-06-04T12:05:00Z", "%Y-%m-%dT%H:%M:%SZ")))
        assert got == expected, f"expected MAX {expected}, got {got}"


def test_iteration_started_ts_none_when_no_event():
    from lib.completion_gate import iteration_started_ts
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        assert iteration_started_ts("orch-missing") is None


# ---- latest_fresh_evaluator_verdict ----

def test_fresh_approved_verdict_returned():
    from lib.completion_gate import iteration_started_ts, latest_fresh_evaluator_verdict
    with tempfile.TemporaryDirectory() as td:
        sd = _redirect_state_dir(Path(td))
        sid = "orch-fresh"
        _write_iteration_started(sd, sid, "2026-06-04T12:00:00Z")
        floor = iteration_started_ts(sid)
        _write_verdict_event(sid, "approved", floor + 5.0)  # fresh
        assert latest_fresh_evaluator_verdict(sid, floor) == "approved"


def test_stale_approved_verdict_filtered_out():
    """A verdict written BEFORE the current iteration_started (ts < floor) is
    stale and MUST be filtered — defeating the silent stale-complete vector."""
    from lib.completion_gate import iteration_started_ts, latest_fresh_evaluator_verdict
    with tempfile.TemporaryDirectory() as td:
        sd = _redirect_state_dir(Path(td))
        sid = "orch-stale"
        _write_iteration_started(sd, sid, "2026-06-04T12:00:00Z")
        floor = iteration_started_ts(sid)
        _write_verdict_event(sid, "approved", floor - 5.0)  # STALE
        assert latest_fresh_evaluator_verdict(sid, floor) is None, (
            "stale prior-iteration approved must NOT pass the freshness floor"
        )


def test_same_second_verdict_is_fresh():
    """A verdict at exactly the floor (same wall-clock second) counts as fresh
    (>= inclusive, D2a same-second tolerance)."""
    from lib.completion_gate import iteration_started_ts, latest_fresh_evaluator_verdict
    with tempfile.TemporaryDirectory() as td:
        sd = _redirect_state_dir(Path(td))
        sid = "orch-samesec"
        _write_iteration_started(sd, sid, "2026-06-04T12:00:00Z")
        floor = iteration_started_ts(sid)
        _write_verdict_event(sid, "approved", floor)  # exactly at floor
        assert latest_fresh_evaluator_verdict(sid, floor) == "approved"


def test_tail_wins_latest_verdict():
    from lib.completion_gate import iteration_started_ts, latest_fresh_evaluator_verdict
    with tempfile.TemporaryDirectory() as td:
        sd = _redirect_state_dir(Path(td))
        sid = "orch-tail"
        _write_iteration_started(sd, sid, "2026-06-04T12:00:00Z")
        floor = iteration_started_ts(sid)
        _write_verdict_event(sid, "iterate", floor + 1.0)
        _write_verdict_event(sid, "approved", floor + 9.0)  # latest ts wins
        _write_verdict_event(sid, "escalate", floor + 4.0)
        assert latest_fresh_evaluator_verdict(sid, floor) == "approved"


def test_verdict_value_filter_accepts_any_event_name():
    """Reader filters on the verdict VALUE not the event-type string, so the
    'verdict' (harness-evaluate) producer name is accepted just like
    'evaluator_verdict'."""
    from lib.completion_gate import iteration_started_ts, latest_fresh_evaluator_verdict
    with tempfile.TemporaryDirectory() as td:
        sd = _redirect_state_dir(Path(td))
        sid = "orch-evtname"
        _write_iteration_started(sd, sid, "2026-06-04T12:00:00Z")
        floor = iteration_started_ts(sid)
        _write_verdict_event(sid, "approved", floor + 2.0, event="verdict")
        assert latest_fresh_evaluator_verdict(sid, floor) == "approved"


def test_no_verdict_event_returns_none():
    from lib.completion_gate import iteration_started_ts, latest_fresh_evaluator_verdict
    with tempfile.TemporaryDirectory() as td:
        sd = _redirect_state_dir(Path(td))
        sid = "orch-noverdict"
        _write_iteration_started(sd, sid, "2026-06-04T12:00:00Z")
        floor = iteration_started_ts(sid)
        assert latest_fresh_evaluator_verdict(sid, floor) is None


def test_since_ts_none_fail_closed_even_with_events():
    """C4/C5: even if a fresh-looking verdict exists, since_ts=None (floor
    unresolvable) MUST return None — never treat None as 0.0."""
    from lib.completion_gate import latest_fresh_evaluator_verdict
    with tempfile.TemporaryDirectory() as td:
        _redirect_state_dir(Path(td))
        sid = "orch-failclosed"
        _write_verdict_event(sid, "approved", time.time())
        assert latest_fresh_evaluator_verdict(sid, None) is None, (
            "since_ts=None must fail closed regardless of present events"
        )


_IO_TESTS = [
    test_iteration_started_ts_parses_iso_to_epoch,
    test_iteration_started_ts_returns_max_of_multiple,
    test_iteration_started_ts_none_when_no_event,
    test_fresh_approved_verdict_returned,
    test_stale_approved_verdict_filtered_out,
    test_same_second_verdict_is_fresh,
    test_tail_wins_latest_verdict,
    test_verdict_value_filter_accepts_any_event_name,
    test_no_verdict_event_returns_none,
    test_since_ts_none_fail_closed_even_with_events,
]


def main() -> int:
    from lib import completion_gate as _m
    # Pure truth-table + input-guard self-check (raises AssertionError on fail).
    _m._self_check()
    # I/O-backed freshness fixtures.
    failed = 0
    for fn in _IO_TESTS:
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL: {fn.__name__}: {e}")
    if failed:
        print(f"completion_gate I/O fixtures: {failed} FAILED")
        return 1
    print(f"OK: {len(_IO_TESTS)} I/O fixture tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
