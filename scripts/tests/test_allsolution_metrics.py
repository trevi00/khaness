#!/usr/bin/env python3
"""Tests for lib/allsolution_metrics.py — composition break-frequency instrumentation."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _with_state(td: Path):
    import lib.paths as P
    return mock.patch.object(P, "STATE_DIR", td / "state")


def test_record_and_read_run():
    from lib import allsolution_metrics as m
    with tempfile.TemporaryDirectory() as td, _with_state(Path(td)):
        assert m.record_phase("sid1", "A_interview", "ok", ts_ms=1) is True
        assert m.record_phase("sid1", "B_research", "skipped", ts_ms=2) is True
        assert m.record_phase("sid1", "C_autopilot", "escalated", detail="hard_cap", ts_ms=3) is True
        recs = m.run_phases("sid1")
        assert [r["phase"] for r in recs] == ["A_interview", "B_research", "C_autopilot"]
        assert recs[2]["status"] == "escalated" and recs[2]["detail"] == "hard_cap"


def test_invalid_phase_or_status_rejected():
    from lib import allsolution_metrics as m
    with tempfile.TemporaryDirectory() as td, _with_state(Path(td)):
        assert m.record_phase("sid", "Z_bogus", "ok") is False
        assert m.record_phase("sid", "A_interview", "weird") is False
        assert m.record_phase("", "A_interview", "ok") is False
        assert m.run_phases("sid") == []


def test_break_summary_aggregates_fragility():
    from lib import allsolution_metrics as m
    with tempfile.TemporaryDirectory() as td, _with_state(Path(td)):
        # run1: interview ok, research ok, autopilot broke
        m.record_phase("r1", "A_interview", "ok"); m.record_phase("r1", "B_research", "ok")
        m.record_phase("r1", "C_autopilot", "broke")
        # run2: interview escalated (chain dies early)
        m.record_phase("r2", "A_interview", "escalated")
        # run3: interview ok, autopilot escalated
        m.record_phase("r3", "A_interview", "ok"); m.record_phase("r3", "C_autopilot", "escalated")
        s = m.break_summary()
        assert s["runs"] == 3 and s["total_breaks"] == 3
        # C_autopilot reached twice, broke+escalated twice -> break_rate 1.0 (most fragile)
        assert s["by_phase"]["C_autopilot"]["reached"] == 2
        assert s["by_phase"]["C_autopilot"]["break_rate"] == 1.0
        assert s["most_fragile_phase"] == "C_autopilot"
        # A_interview reached 3x, 1 escalated -> break_rate 0.333
        assert s["by_phase"]["A_interview"]["break_rate"] == round(1 / 3, 3)


def test_summary_empty_forward_looking():
    from lib import allsolution_metrics as m
    with tempfile.TemporaryDirectory() as td, _with_state(Path(td)):
        s = m.break_summary()
        assert s["runs"] == 0 and s["most_fragile_phase"] is None
        assert "forward-looking" in m.render_break_summary()


def main() -> int:
    tests = [
        test_record_and_read_run,
        test_invalid_phase_or_status_rejected,
        test_break_summary_aggregates_fragility,
        test_summary_empty_forward_looking,
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
