#!/usr/bin/env python3
"""Tests for cron/check_brain_push.py — dual trigger (① live→file + ②③ file→remote)."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _evaluate_with(td: Path, *, divergence_status: dict, push_at_risk: bool) -> dict:
    """Run check_brain_push.evaluate() with brain_store.status + brain_git_status.at_risk
    stubbed and the flag/check paths redirected into a temp dir."""
    import cron.check_brain_push as c
    import lib.brain_store as bs
    import lib.brain_git_status as bgs
    with mock.patch.object(c, "FLAG_PATH", td / "brain-push-ready.flag"), \
         mock.patch.object(c, "CHECK_STATE_PATH", td / "brain-push-check.json"), \
         mock.patch.object(bs, "status", lambda: divergence_status), \
         mock.patch.object(bgs, "at_risk", lambda *a, **k: push_at_risk):
        return c.evaluate()


def test_fires_on_push_gap_only():
    """① divergence 0 (Stop-hook already saved) but ②③ unpushed → MUST fire (the gap
    D1 closes — otherwise the autopush would never run)."""
    with tempfile.TemporaryDirectory() as td:
        s = _evaluate_with(Path(td), divergence_status={}, push_at_risk=True)
        assert s["fired"] is True and s["push_gap"] is True
        assert s["live_not_in_brain_total"] == 0
        assert (Path(td) / "brain-push-ready.flag").exists()


def test_fires_on_live_divergence_only():
    """① live→file divergence fires even if ②③ is clean (a missed Stop tick)."""
    with tempfile.TemporaryDirectory() as td:
        status = {"l1": {"insight-index.jsonl": {"live_not_in_brain": 3}}}
        s = _evaluate_with(Path(td), divergence_status=status, push_at_risk=False)
        assert s["fired"] is True and s["live_not_in_brain_total"] == 3


def test_quiet_when_durable():
    """No live divergence AND on origin/brain-snapshots → QUIET, no flag."""
    with tempfile.TemporaryDirectory() as td:
        s = _evaluate_with(Path(td), divergence_status={}, push_at_risk=False)
        assert s["fired"] is False
        assert not (Path(td) / "brain-push-ready.flag").exists()


def test_failsoft_status_error():
    """A brain_store.status() error degrades to no-divergence (still honors push_gap)."""
    with tempfile.TemporaryDirectory() as td:
        s = _evaluate_with(Path(td), divergence_status={"error": "boom"}, push_at_risk=False)
        assert s["fired"] is False and s["live_not_in_brain_total"] == 0


def main() -> int:
    tests = [
        test_fires_on_push_gap_only,
        test_fires_on_live_divergence_only,
        test_quiet_when_durable,
        test_failsoft_status_error,
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
