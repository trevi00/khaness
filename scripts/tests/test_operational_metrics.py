#!/usr/bin/env python3
"""Tests for lib/operational_metrics.py — operational-validation N-target counters.

Each helper reads filesystem state set by real runs. Tests fixture by
mutating STATE_DIR / TELEMETRY_DIR to a tempdir and seeding the expected
artifacts (sid dirs / JSONL records / synthesis files), then asserting
the counter returns the seeded N.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _redirect_paths(tmp: Path) -> None:
    """STATE_DIR + TELEMETRY_DIR redirect to tmp + module-local re-bind."""
    from lib import paths as P
    from lib import operational_metrics as M
    P.STATE_DIR = tmp / "state"
    P.TELEMETRY_DIR = tmp / "telemetry"
    M.STATE_DIR = P.STATE_DIR
    M.TELEMETRY_DIR = P.TELEMETRY_DIR
    P.STATE_DIR.mkdir(parents=True, exist_ok=True)
    P.TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)


def test_autopilot_run_count_zero_when_dir_missing():
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        from lib.operational_metrics import (
            get_autopilot_run_count, AUTOPILOT_RUN_TARGET,
        )
        cur, tgt = get_autopilot_run_count()
        assert cur == 0
        assert tgt == AUTOPILOT_RUN_TARGET


def test_autopilot_run_count_returns_sid_dir_count():
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        from lib import paths as P
        orch = P.STATE_DIR / "orchestrator"
        for sid in ("orch-1", "orch-2", "orch-3"):
            (orch / sid).mkdir(parents=True)
        from lib.operational_metrics import get_autopilot_run_count
        cur, _ = get_autopilot_run_count()
        assert cur == 3


def test_autopilot_run_count_ignores_files_at_top_level():
    """Stray files under state/orchestrator/ must not count as sessions."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        from lib import paths as P
        orch = P.STATE_DIR / "orchestrator"
        orch.mkdir(parents=True)
        (orch / "stray.txt").write_text("ignored")
        (orch / "orch-real").mkdir()
        from lib.operational_metrics import get_autopilot_run_count
        cur, _ = get_autopilot_run_count()
        assert cur == 1


def test_autopilot_parallel_count_zero_when_telemetry_missing():
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        from lib.operational_metrics import get_autopilot_parallel_count
        cur, tgt = get_autopilot_parallel_count()
        assert cur == 0
        assert tgt == 1


def test_autopilot_parallel_count_lines_in_telemetry():
    # Canonical-file fix (debate-1781756389-x73qz8): the reader counts the file
    # the writer (log_parallel_run_outcome, category 'autopilot-parallel-runs')
    # actually targets, NOT the never-written parallel-run.jsonl.
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        from lib import paths as P
        path = P.TELEMETRY_DIR / "autopilot-parallel-runs.jsonl"
        with path.open("w", encoding="utf-8") as f:
            f.write(json.dumps({"sid": "orch-1", "status": "complete"}) + "\n")
            f.write(json.dumps({"sid": "orch-2", "status": "escalate"}) + "\n")
            f.write("\n")  # blank line should not count
            f.write(json.dumps({"sid": "orch-3", "status": "complete"}) + "\n")
        from lib.operational_metrics import get_autopilot_parallel_count
        cur, _ = get_autopilot_parallel_count()
        assert cur == 3


def test_autopilot_parallel_count_ignores_dead_file():
    """Regression for debate-1781756389-x73qz8: writing to the OLD never-read
    parallel-run.jsonl must NOT count — only the canonical writer file does."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        from lib import paths as P
        dead = P.TELEMETRY_DIR / "parallel-run.jsonl"
        with dead.open("w", encoding="utf-8") as f:
            f.write(json.dumps({"sid": "orch-x", "status": "complete"}) + "\n")
        from lib.operational_metrics import get_autopilot_parallel_count
        cur, _ = get_autopilot_parallel_count()
        assert cur == 0  # dead file ignored; canonical file absent -> 0


def test_dge_e2_cross_target_count_zero_when_no_axis_files():
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        from lib.operational_metrics import get_dge_e2_cross_target_count
        cur, tgt = get_dge_e2_cross_target_count()
        assert cur == 0
        assert tgt == 5


def test_dge_e2_cross_target_count_marker_field():
    """Records with cross_target_first_invocation=True count; others
    (clamp events, fallback events) must not."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        from lib import paths as P
        for sid in ("orch-a", "orch-b"):
            d = P.STATE_DIR / "evaluator" / sid
            d.mkdir(parents=True)
            with (d / "axis_scores.jsonl").open("w", encoding="utf-8") as f:
                f.write(json.dumps({
                    "event": "verdict",
                    "cross_target_first_invocation": True,
                }) + "\n")
                f.write(json.dumps({
                    "event": "clamp",
                    "cross_target_first_invocation": False,
                }) + "\n")
        from lib.operational_metrics import get_dge_e2_cross_target_count
        cur, _ = get_dge_e2_cross_target_count()
        assert cur == 2  # 2 sids × 1 marker-true record each


def test_dge_e2_cross_target_count_skips_corrupt_lines():
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        from lib import paths as P
        d = P.STATE_DIR / "evaluator" / "orch-corrupt"
        d.mkdir(parents=True)
        with (d / "axis_scores.jsonl").open("w", encoding="utf-8") as f:
            f.write("not-json-at-all\n")
            f.write(json.dumps({"cross_target_first_invocation": True}) + "\n")
        from lib.operational_metrics import get_dge_e2_cross_target_count
        cur, _ = get_dge_e2_cross_target_count()
        assert cur == 1  # corrupt skipped, valid counted


def test_team_runtime_count_zero_when_dir_missing():
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        from lib.operational_metrics import get_team_runtime_count
        cur, tgt = get_team_runtime_count()
        assert cur == 0
        assert tgt == 3


def test_team_runtime_count_counts_session_dirs():
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        from lib import paths as P
        team = P.STATE_DIR / "team"
        for sid in ("orch-x", "orch-y"):
            (team / sid).mkdir(parents=True)
        from lib.operational_metrics import get_team_runtime_count
        cur, _ = get_team_runtime_count()
        assert cur == 2


def test_allsolution_run_count_zero_when_no_artifacts():
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        from lib.operational_metrics import get_allsolution_run_count
        cur, tgt = get_allsolution_run_count()
        assert cur == 0
        assert tgt == 1


def test_allsolution_run_count_counts_md_files():
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        from lib import paths as P
        d = P.STATE_DIR / "allsolution"
        d.mkdir(parents=True)
        for ts in ("1778250000", "1778260000", "1778270000"):
            (d / f"{ts}.md").write_text("# synthesis", encoding="utf-8")
        from lib.operational_metrics import get_allsolution_run_count
        cur, _ = get_allsolution_run_count()
        assert cur == 3


def test_all_metrics_returns_5_keys_with_met_flag():
    """all_metrics aggregates 5 sub_phase metrics with consistent shape."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        from lib.operational_metrics import all_metrics
        d = all_metrics()
        expected_keys = {
            "autopilot_runs", "autopilot_parallel_enables",
            "dge_e2_cross_target", "team_runtime_sessions", "allsolution_runs",
        }
        assert set(d.keys()) == expected_keys
        for key, payload in d.items():
            assert "current" in payload
            assert "target" in payload
            assert "met" in payload
            assert payload["met"] == (payload["current"] >= payload["target"])


def test_all_metrics_met_flag_flips_when_target_reached():
    """When current >= target, met=True. Pin so dashboard collapse logic
    has a stable contract."""
    with tempfile.TemporaryDirectory() as td:
        _redirect_paths(Path(td))
        # Seed enough autopilot sids to exceed AUTOPILOT_RUN_TARGET=10
        from lib import paths as P
        orch = P.STATE_DIR / "orchestrator"
        for i in range(11):
            (orch / f"orch-{i}").mkdir(parents=True)
        from lib.operational_metrics import all_metrics
        d = all_metrics()
        assert d["autopilot_runs"]["met"] is True
        assert d["autopilot_runs"]["current"] == 11
        # Other metrics still unmet
        assert d["autopilot_parallel_enables"]["met"] is False


TESTS = [
    test_autopilot_run_count_zero_when_dir_missing,
    test_autopilot_run_count_returns_sid_dir_count,
    test_autopilot_run_count_ignores_files_at_top_level,
    test_autopilot_parallel_count_zero_when_telemetry_missing,
    test_autopilot_parallel_count_lines_in_telemetry,
    test_autopilot_parallel_count_ignores_dead_file,
    test_dge_e2_cross_target_count_zero_when_no_axis_files,
    test_dge_e2_cross_target_count_marker_field,
    test_dge_e2_cross_target_count_skips_corrupt_lines,
    test_team_runtime_count_zero_when_dir_missing,
    test_team_runtime_count_counts_session_dirs,
    test_allsolution_run_count_zero_when_no_artifacts,
    test_allsolution_run_count_counts_md_files,
    test_all_metrics_returns_5_keys_with_met_flag,
    test_all_metrics_met_flag_flips_when_target_reached,
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
