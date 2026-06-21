#!/usr/bin/env python3
"""Tests for handlers/session/init.py status lines.

Covers the STEP 6 [aborted-kha-plan] consumer line (operator decision
2026-06-04 hybrid): the previously-silent autopilot/kha-bridge plan-edit abort
is now surfaced at SessionStart, while the l2/skill/atlas _completed promotion
stores remain forensic-only (NOT asserted here — they have no SessionStart line
by design).
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def test_aborted_kha_plan_line_silent_on_zero_and_counts_aborts():
    from handlers.session import init
    from lib.advisory_ack import resolve
    store = resolve("aborted_kha_plan_validator_fail")
    saved = store.ack_path
    with tempfile.TemporaryDirectory() as td:
        store.ack_path = Path(td) / "aborted_kha_plan_validator_fail.txt"
        try:
            # zero recorded → silent (None): preserves the all-silent invariant
            assert init._aborted_kha_plan_line() is None
            # the producer (lib/autopilot_kha_bridge.py) records each abort via .ack(key)
            store.ack("orch-1:phase_0_design:plan_a")
            store.ack("orch-2:phase_1_impl:plan_b")
            store.ack("orch-1:phase_0_design:plan_a")  # dup → not double-counted
            line = init._aborted_kha_plan_line()
            assert line is not None
            assert line.startswith("[aborted-kha-plan] 2 "), line
            assert "aborted_kha_plan_validator_fail.txt" in line
        finally:
            store.ack_path = saved


def test_compose_includes_aborted_kha_when_present():
    """The line is actually WIRED into the unified <harness-status> block."""
    from handlers.session import init
    from lib.advisory_ack import resolve
    store = resolve("aborted_kha_plan_validator_fail")
    saved = store.ack_path
    with tempfile.TemporaryDirectory() as td:
        store.ack_path = Path(td) / "aborted.txt"
        try:
            store.ack("orch-9:phase_2:plan_z")
            block = init._compose_harness_status(cwd="")
            # additive assertion — other lines may or may not be present
            # depending on isolation, but the aborted-kha line must appear.
            assert block is not None
            assert "<harness-status>" in block
            assert "[aborted-kha-plan] 1 " in block
        finally:
            store.ack_path = saved


def test_graduation_ready_line_silent_until_ready():
    """Track 1 D4: [graduation] ready-line is silent unless a tracked validator's
    streak has reached N, then surfaces the token-gated flip command."""
    from handlers.session import init
    from lib import graduation as g
    saved = g.STATE_DIR
    with tempfile.TemporaryDirectory() as td:
        g.STATE_DIR = Path(td)
        try:
            assert init._graduation_ready_line() is None, "silent when nothing ready"
            st = g.load_state()
            g._entry(st, "doc_code_drift")["ready"] = True
            g.save_state(st)
            line = init._graduation_ready_line()
            assert line is not None and line.startswith("[graduation] 1 ready:"), line
            assert "doc_code_drift" in line and g.TOKEN_GRADUATE in line
        finally:
            g.STATE_DIR = saved


def test_compose_includes_graduation_when_ready():
    from handlers.session import init
    from lib import graduation as g
    saved = g.STATE_DIR
    with tempfile.TemporaryDirectory() as td:
        g.STATE_DIR = Path(td)
        try:
            st = g.load_state()
            g._entry(st, "self_model_drift")["ready"] = True
            g.save_state(st)
            block = init._compose_harness_status(cwd="")
            assert block is not None and "[graduation] 1 ready:" in block
        finally:
            g.STATE_DIR = saved


def test_graduation_streak_tick_failsoft_smoke():
    """The SessionStart-amortized tick must never raise (fail-soft hook). State
    is redirected to temp so a standalone run never writes production state."""
    from handlers.session import init
    from lib import graduation as g
    saved = g.STATE_DIR
    with tempfile.TemporaryDirectory() as td:
        g.STATE_DIR = Path(td)
        try:
            init._graduation_streak_tick()  # must not raise
        finally:
            g.STATE_DIR = saved


def test_brain_divergence_line_fires_on_divergence():
    """M23: fires one advisory line when status() shows live_not_in_brain > 0."""
    from unittest import mock
    from handlers.session import init
    status = {"l1": {"insight-index.jsonl": {"live_not_in_brain": 3},
                     "retractions.jsonl": {"live_not_in_brain": 0}},
              "l2": {"global-facts.jsonl": {"live_not_in_brain": 1}}}
    with mock.patch("lib.brain_store.status", return_value=status):
        line = init._brain_divergence_line()
    assert line is not None and "[brain-divergence] 4 live insight" in line
    assert "brain_snapshot save" in line


def test_brain_divergence_line_silent_on_zero():
    """M23: divergence is the SOLE source of truth — silent when status() shows 0
    (NOT triggered by a stale cron flag)."""
    from unittest import mock
    from handlers.session import init
    with mock.patch("lib.brain_store.status",
                    return_value={"l1": {"x.jsonl": {"live_not_in_brain": 0}}, "l2": {}}):
        assert init._brain_divergence_line() is None


def test_brain_divergence_line_failsoft():
    """M23: status() raising must not break the hook — returns None."""
    from unittest import mock
    from handlers.session import init
    with mock.patch("lib.brain_store.status", side_effect=RuntimeError("boom")):
        assert init._brain_divergence_line() is None


def test_compose_includes_brain_divergence_when_present():
    from unittest import mock
    from handlers.session import init
    with mock.patch("lib.brain_store.status",
                    return_value={"l1": {"x.jsonl": {"live_not_in_brain": 2}}, "l2": {}}):
        block = init._compose_harness_status()
    assert block is not None and "[brain-divergence] 2 live insight" in block


def main() -> int:
    tests = [
        test_aborted_kha_plan_line_silent_on_zero_and_counts_aborts,
        test_compose_includes_aborted_kha_when_present,
        test_graduation_ready_line_silent_until_ready,
        test_compose_includes_graduation_when_ready,
        test_graduation_streak_tick_failsoft_smoke,
        test_brain_divergence_line_fires_on_divergence,
        test_brain_divergence_line_silent_on_zero,
        test_brain_divergence_line_failsoft,
        test_compose_includes_brain_divergence_when_present,
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
