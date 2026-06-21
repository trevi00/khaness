#!/usr/bin/env python3
"""Tests for lib.breakers.composite (v15.10 D3).

Coverage map (every D3 contract clause hit):
  - Composite key isolation: separate (agent_type, failure_mode) breakers
    have independent state.
  - Primary trip: 3 failures within rolling 10-event window → OPEN.
  - Sub-threshold (2 failures in 10) → stays CLOSED.
  - History window enforcement (>10 entries → oldest dropped).
  - Backoff escalation: 2^trip_count * 60s, capped at 3600s.
  - HALF_OPEN promotion: try_acquire after cool_off elapsed.
  - HALF_OPEN single-probe budget: second try_acquire while in flight → False.
  - HALF_OPEN success → CLOSED + trip_count reset.
  - HALF_OPEN failure → re-OPEN with trip_count++ and backoff doubled.
  - try_acquire blocks while cool_off has not elapsed.
  - Secondary trip: 5 failures in 20 across other modes triggers OPEN.
  - Event emission via emit_fn for opened / closed / probe / reopened.
  - Constructor input validation.
  - Snapshot is read-only / immutable.
  - Persistence round-trip via on-disk JSON.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from lib.breakers import composite as comp  # noqa: E402
from lib.breakers.composite import (  # noqa: E402
    BACKOFF_BASE_SEC,
    BACKOFF_CAP_SEC,
    BreakerSnapshot,
    CompositeBreaker,
    State,
    TRIP_ANY_MODE,
    TRIP_ANY_WINDOW,
    TRIP_PER_MODE,
    TRIP_WINDOW,
)


# Time fixture — monkey-patch _now() so tests run deterministically.
class _Clock:
    def __init__(self) -> None:
        self.t = 1_000_000.0
    def now(self) -> float:
        return self.t
    def advance(self, dt: float) -> None:
        self.t += dt


def _captured_emit():
    events: list[tuple[str, dict]] = []
    def emit(event_type: str, payload: dict) -> None:
        events.append((event_type, dict(payload)))
    return events, emit


def _make_breaker(td: Path, agent_type: str, failure_mode: str,
                  any_mode_keys=None, emit_fn=None):
    if emit_fn is None:
        events, emit_fn = _captured_emit()
    return CompositeBreaker(
        agent_type=agent_type,
        failure_mode=failure_mode,
        project_id="proj_test",
        base_dir=str(td),
        emit_fn=emit_fn,
        any_mode_keys=any_mode_keys,
    )


# ---- tests ----------------------------------------------------------------------

def test_constructor_validation():
    try:
        CompositeBreaker(agent_type="", failure_mode="x", project_id="p")
    except ValueError:
        pass
    else:
        raise AssertionError("empty agent_type must raise ValueError")
    try:
        CompositeBreaker(agent_type="a", failure_mode="", project_id="p")
    except ValueError:
        pass
    else:
        raise AssertionError("empty failure_mode must raise ValueError")
    try:
        CompositeBreaker(agent_type="a", failure_mode="x", project_id="")
    except ValueError:
        pass
    else:
        raise AssertionError("empty project_id must raise ValueError")


def test_initial_state_is_closed():
    with tempfile.TemporaryDirectory() as td:
        b = _make_breaker(Path(td), "researcher", "evidence_fabrication")
        snap = b.snapshot()
        assert snap.state == State.CLOSED
        assert snap.trip_count == 0
        assert snap.history == ()
        assert snap.opened_at is None
        assert snap.probe_in_flight is False


def test_composite_keys_are_isolated():
    with tempfile.TemporaryDirectory() as td:
        b1 = _make_breaker(Path(td), "researcher", "evidence_fabrication")
        b2 = _make_breaker(Path(td), "researcher", "schema_violation")
        b3 = _make_breaker(Path(td), "executor", "evidence_fabrication")
        # trip b1
        for _ in range(TRIP_PER_MODE):
            b1.record_failure()
        assert b1.snapshot().state == State.OPEN
        assert b2.snapshot().state == State.CLOSED
        assert b3.snapshot().state == State.CLOSED


def test_primary_trip_at_three_in_ten():
    with tempfile.TemporaryDirectory() as td:
        events, emit = _captured_emit()
        b = _make_breaker(Path(td), "researcher", "evidence_fabrication", emit_fn=emit)
        for _ in range(TRIP_PER_MODE - 1):
            assert b.record_failure() == State.CLOSED
        assert b.record_failure() == State.OPEN
        assert any(et == "breaker.opened" for et, _ in events)
        snap = b.snapshot()
        assert snap.state == State.OPEN
        assert snap.trip_count == 1


def test_sub_threshold_stays_closed():
    with tempfile.TemporaryDirectory() as td:
        b = _make_breaker(Path(td), "researcher", "evidence_fabrication")
        # 2 failures + 1 success in 10-window → 2 failures, below 3
        b.record_failure()
        b.record_failure()
        b.record_success()
        assert b.snapshot().state == State.CLOSED


def test_history_window_drops_old_entries():
    with tempfile.TemporaryDirectory() as td:
        b = _make_breaker(Path(td), "researcher", "evidence_fabrication")
        # 2 ancient failures, then 9 successes → failures should age out
        b.record_failure()
        b.record_failure()
        for _ in range(TRIP_WINDOW - 1):
            b.record_success()
        # one more failure → only THIS failure in the window (others fell off)
        b.record_failure()
        snap = b.snapshot()
        assert snap.state == State.CLOSED  # one failure ≠ trip
        assert len(snap.history) == TRIP_WINDOW


def test_open_to_half_open_after_cool_off():
    clock = _Clock()
    comp._now = clock.now
    try:
        with tempfile.TemporaryDirectory() as td:
            events, emit = _captured_emit()
            b = _make_breaker(Path(td), "researcher", "evidence_fabrication", emit_fn=emit)
            for _ in range(TRIP_PER_MODE):
                b.record_failure()
            assert b.snapshot().state == State.OPEN
            # try_acquire BEFORE cool_off → False
            assert b.try_acquire() is False
            # advance past cool_off (60s for first trip)
            clock.advance(BACKOFF_BASE_SEC * 2 + 1)
            assert b.try_acquire() is True
            snap = b.snapshot()
            assert snap.state == State.HALF_OPEN
            assert snap.probe_in_flight is True
            assert any(et == "breaker.probe_started" for et, _ in events)
    finally:
        comp._now = __import__("time").time


def test_half_open_single_probe_budget():
    clock = _Clock()
    comp._now = clock.now
    try:
        with tempfile.TemporaryDirectory() as td:
            b = _make_breaker(Path(td), "researcher", "evidence_fabrication")
            for _ in range(TRIP_PER_MODE):
                b.record_failure()
            clock.advance(BACKOFF_BASE_SEC * 2 + 1)
            assert b.try_acquire() is True
            # second concurrent acquire while probe in flight → False
            assert b.try_acquire() is False
    finally:
        comp._now = __import__("time").time


def test_half_open_success_closes_and_resets_trip_count():
    clock = _Clock()
    comp._now = clock.now
    try:
        with tempfile.TemporaryDirectory() as td:
            events, emit = _captured_emit()
            b = _make_breaker(Path(td), "researcher", "evidence_fabrication", emit_fn=emit)
            for _ in range(TRIP_PER_MODE):
                b.record_failure()
            clock.advance(BACKOFF_BASE_SEC * 2 + 1)
            assert b.try_acquire() is True
            assert b.record_success() == State.CLOSED
            snap = b.snapshot()
            assert snap.state == State.CLOSED
            assert snap.trip_count == 0   # Azure canonical: reset on close
            assert snap.probe_in_flight is False
            assert any(et == "breaker.closed" for et, _ in events)
    finally:
        comp._now = __import__("time").time


def test_half_open_failure_reopens_with_doubled_backoff():
    clock = _Clock()
    comp._now = clock.now
    try:
        with tempfile.TemporaryDirectory() as td:
            events, emit = _captured_emit()
            b = _make_breaker(Path(td), "researcher", "evidence_fabrication", emit_fn=emit)
            for _ in range(TRIP_PER_MODE):
                b.record_failure()
            first_trip_backoff = BACKOFF_BASE_SEC * 2  # 2^1 * 60 = 120
            clock.advance(first_trip_backoff + 1)
            assert b.try_acquire() is True
            assert b.record_failure() == State.OPEN
            snap = b.snapshot()
            assert snap.state == State.OPEN
            assert snap.trip_count == 2
            # cool_off_until should reflect 2^2 * 60 = 240s from re-open time
            expected_backoff = BACKOFF_BASE_SEC * (2 ** 2)
            assert snap.cool_off_until is not None
            assert abs(snap.cool_off_until - (clock.now() + expected_backoff)) < 1e-6
            assert any(et == "breaker.reopened" for et, _ in events)
    finally:
        comp._now = __import__("time").time


def test_backoff_caps_at_one_hour():
    clock = _Clock()
    comp._now = clock.now
    try:
        with tempfile.TemporaryDirectory() as td:
            b = _make_breaker(Path(td), "researcher", "evidence_fabrication")
            # Simulate trip_count > 6 so 2^trip_count*60 exceeds 3600
            for _ in range(TRIP_PER_MODE):
                b.record_failure()
            for cycle in range(8):
                # Advance enough to pass cool_off (max cap 3600 + slack)
                clock.advance(BACKOFF_CAP_SEC + 1)
                assert b.try_acquire() is True
                b.record_failure()
            snap = b.snapshot()
            assert snap.cool_off_until is not None
            # Cool_off should never exceed now + cap
            assert snap.cool_off_until - clock.now() <= BACKOFF_CAP_SEC + 1e-6
    finally:
        comp._now = __import__("time").time


def test_secondary_trip_across_modes():
    """5 failures across multiple modes for the same agent_type → secondary trip."""
    clock = _Clock()
    comp._now = clock.now
    try:
        with tempfile.TemporaryDirectory() as td:
            # b_target watches all 3 modes for secondary signal
            mode_a = "evidence_fabrication"
            mode_b = "schema_violation"
            mode_c = "tool_misuse"
            # Pre-populate sibling histories with failures
            b_sib1 = _make_breaker(Path(td), "researcher", mode_b)
            b_sib2 = _make_breaker(Path(td), "researcher", mode_c)
            for _ in range(2):
                b_sib1.record_failure()
            for _ in range(2):
                b_sib2.record_failure()
            # The target — fails twice (own mode), and secondary should trip at the SECOND
            # because 2 + 2 + 2 = 6 ≥ TRIP_ANY_MODE (5) within ANY_WINDOW (20).
            b_target = _make_breaker(
                Path(td), "researcher", mode_a,
                any_mode_keys=(mode_b, mode_c),
            )
            # First failure: own=1, others=4 → 5 total ≥ 5 → trip on secondary
            new_state = b_target.record_failure()
            assert new_state == State.OPEN
    finally:
        comp._now = __import__("time").time


def test_record_failure_in_open_state_no_state_change():
    clock = _Clock()
    comp._now = clock.now
    try:
        with tempfile.TemporaryDirectory() as td:
            b = _make_breaker(Path(td), "researcher", "evidence_fabrication")
            for _ in range(TRIP_PER_MODE):
                b.record_failure()
            assert b.snapshot().state == State.OPEN
            # additional failure while OPEN — should not crash, no transition
            assert b.record_failure() == State.OPEN
    finally:
        comp._now = __import__("time").time


def test_persistence_round_trip():
    """Snapshot survives a fresh CompositeBreaker instance pointing at same dir."""
    with tempfile.TemporaryDirectory() as td:
        b1 = _make_breaker(Path(td), "researcher", "evidence_fabrication")
        b1.record_failure()
        b1.record_failure()
        # New instance, same paths
        b2 = _make_breaker(Path(td), "researcher", "evidence_fabrication")
        snap = b2.snapshot()
        assert snap.history == (False, False)


def test_snapshot_is_immutable():
    with tempfile.TemporaryDirectory() as td:
        b = _make_breaker(Path(td), "researcher", "evidence_fabrication")
        snap = b.snapshot()
        try:
            snap.trip_count = 99  # type: ignore[misc]
        except Exception:
            pass
        else:
            raise AssertionError("BreakerSnapshot must be frozen")


def test_event_emission_payload_shape():
    clock = _Clock()
    comp._now = clock.now
    try:
        with tempfile.TemporaryDirectory() as td:
            events, emit = _captured_emit()
            b = _make_breaker(Path(td), "researcher", "evidence_fabrication", emit_fn=emit)
            for _ in range(TRIP_PER_MODE):
                b.record_failure()
            opened = [(et, p) for et, p in events if et == "breaker.opened"]
            assert opened
            _, payload = opened[0]
            assert payload["agent_type"] == "researcher"
            assert payload["failure_mode"] == "evidence_fabrication"
            assert payload["trip_count"] == 1
            assert payload["backoff_sec"] == BACKOFF_BASE_SEC * 2  # 2^1 * 60
            assert payload["cool_off_until"] is not None
            assert payload["trigger"] in ("primary", "secondary")
    finally:
        comp._now = __import__("time").time


def _poison_record(b, record: dict) -> None:
    """Write an arbitrary (poisoned) JSON record to the breaker's state file."""
    os.makedirs(os.path.dirname(b.record_path), exist_ok=True)
    with open(b.record_path, "w", encoding="utf-8") as f:
        json.dump(record, f)


def test_load_coerces_poisoned_trip_count():
    # deep-audit pass-2: a hand-edited / torn state file with a non-numeric
    # trip_count must NOT crash snapshot()/record_failure() — those run on the
    # post_tool hook path, where a raise is a fail-CLOSED wedge. _load coerces it.
    with tempfile.TemporaryDirectory() as td:
        b = _make_breaker(Path(td), "researcher", "evidence_fabrication")
        _poison_record(b, {"state": "open", "trip_count": "not-a-number",
                           "history": [], "opened_at": None,
                           "cool_off_until": None, "probe_in_flight": False})
        snap = b.snapshot()           # must not raise
        assert snap.trip_count == 0   # coerced to safe default
        assert b.record_failure() in (State.OPEN, State.HALF_OPEN, State.CLOSED)  # no raise


def test_load_coerces_poisoned_timestamp():
    # A poisoned non-numeric cool_off_until would crash `now < cool_off` in
    # try_acquire() (str vs float). _load coerces it to None (treated as unset).
    with tempfile.TemporaryDirectory() as td:
        b = _make_breaker(Path(td), "researcher", "evidence_fabrication")
        _poison_record(b, {"state": "open", "trip_count": 1,
                           "history": [], "opened_at": "garbage",
                           "cool_off_until": "not-a-timestamp",
                           "probe_in_flight": False,
                           "probe_reserved_at": "also-garbage"})
        # try_acquire must not raise; poisoned cool_off → unset → OPEN promotes
        assert b.try_acquire() is True
        snap = b.snapshot()
        assert snap.opened_at is None
        assert snap.cool_off_until is None


TESTS = [
    test_constructor_validation,
    test_initial_state_is_closed,
    test_composite_keys_are_isolated,
    test_primary_trip_at_three_in_ten,
    test_sub_threshold_stays_closed,
    test_history_window_drops_old_entries,
    test_open_to_half_open_after_cool_off,
    test_half_open_single_probe_budget,
    test_half_open_success_closes_and_resets_trip_count,
    test_half_open_failure_reopens_with_doubled_backoff,
    test_backoff_caps_at_one_hour,
    test_secondary_trip_across_modes,
    test_record_failure_in_open_state_no_state_change,
    test_persistence_round_trip,
    test_snapshot_is_immutable,
    test_event_emission_payload_shape,
    test_load_coerces_poisoned_trip_count,
    test_load_coerces_poisoned_timestamp,
]


def main() -> int:
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"  [OK] {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  [FAIL] {fn.__name__}: {e}")
        except Exception as e:
            failed += 1
            print(f"  [ERROR] {fn.__name__}: {type(e).__name__}: {e}")
    if failed:
        print(f"\n[FAIL] {failed}/{len(TESTS)} tests failed")
        return 1
    print(f"\n[OK] {len(TESTS)} tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
