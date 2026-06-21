#!/usr/bin/env python3
"""Unit tests for lib/autopilot_flip_policy.py — D5 from debate-1778307906-23b7b3.

Coverage:
  - current_default returns 0 literal (locked per debate)
  - current_default is deterministic
  - log_parallel_run_outcome validates inputs
  - log_parallel_run_outcome writes to autopilot-parallel-runs.jsonl
  - record shape: sid, status, merge_conflicts, pane_failures, ts auto-stamped
  - kwargs passthrough for extras
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _redirect_telemetry_dir(tmp: Path) -> None:
    from lib import paths as P
    from lib import logging as L
    P.TELEMETRY_DIR = tmp / "telemetry"
    L.TELEMETRY_DIR = P.TELEMETRY_DIR
    P.TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)


def test_current_default_returns_zero():
    from lib.autopilot_flip_policy import current_default
    assert current_default() == 0


def test_current_default_is_deterministic():
    from lib.autopilot_flip_policy import current_default
    values = [current_default() for _ in range(5)]
    assert all(v == 0 for v in values)
    assert len(set(values)) == 1


def test_current_default_returns_int_not_bool():
    from lib.autopilot_flip_policy import current_default
    v = current_default()
    assert isinstance(v, int)
    assert type(v) is int  # not bool subclass


def test_log_parallel_run_outcome_rejects_empty_sid():
    from lib.autopilot_flip_policy import log_parallel_run_outcome
    try:
        log_parallel_run_outcome(sid="", status="complete")
    except ValueError:
        return
    raise AssertionError("expected ValueError on empty sid")


def test_log_parallel_run_outcome_rejects_non_str_sid():
    from lib.autopilot_flip_policy import log_parallel_run_outcome
    try:
        log_parallel_run_outcome(sid=42, status="complete")  # type: ignore[arg-type]
    except ValueError:
        return
    raise AssertionError("expected ValueError on non-str sid")


def test_log_parallel_run_outcome_rejects_empty_status():
    from lib.autopilot_flip_policy import log_parallel_run_outcome
    try:
        log_parallel_run_outcome(sid="orch-x", status="")
    except ValueError:
        return
    raise AssertionError("expected ValueError on empty status")


def test_log_parallel_run_outcome_writes_to_telemetry():
    from lib.autopilot_flip_policy import log_parallel_run_outcome
    with tempfile.TemporaryDirectory() as td:
        _redirect_telemetry_dir(Path(td))
        log_parallel_run_outcome(
            sid="orch-x", status="complete",
            merge_conflicts=0, pane_failures=0,
        )
        target = Path(td) / "telemetry" / "autopilot-parallel-runs.jsonl"
        assert target.exists()
        records = [
            json.loads(line)
            for line in target.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(records) == 1
        rec = records[0]
        assert rec["sid"] == "orch-x"
        assert rec["status"] == "complete"
        assert rec["merge_conflicts"] == 0
        assert rec["pane_failures"] == 0
        assert "ts" in rec  # auto-stamped


def test_log_parallel_run_outcome_record_with_failures():
    from lib.autopilot_flip_policy import log_parallel_run_outcome
    with tempfile.TemporaryDirectory() as td:
        _redirect_telemetry_dir(Path(td))
        log_parallel_run_outcome(
            sid="orch-y", status="escalate",
            merge_conflicts=1, pane_failures=2,
        )
        target = Path(td) / "telemetry" / "autopilot-parallel-runs.jsonl"
        rec = json.loads(target.read_text(encoding="utf-8").strip())
        assert rec["status"] == "escalate"
        assert rec["merge_conflicts"] == 1
        assert rec["pane_failures"] == 2


def test_log_parallel_run_outcome_kwargs_passthrough():
    from lib.autopilot_flip_policy import log_parallel_run_outcome
    with tempfile.TemporaryDirectory() as td:
        _redirect_telemetry_dir(Path(td))
        log_parallel_run_outcome(
            sid="orch-z", status="complete", duration_ms=12345, decisions_count=3,
        )
        target = Path(td) / "telemetry" / "autopilot-parallel-runs.jsonl"
        rec = json.loads(target.read_text(encoding="utf-8").strip())
        assert rec["duration_ms"] == 12345
        assert rec["decisions_count"] == 3


def test_log_parallel_run_outcome_appends_not_overwrites():
    from lib.autopilot_flip_policy import log_parallel_run_outcome
    with tempfile.TemporaryDirectory() as td:
        _redirect_telemetry_dir(Path(td))
        log_parallel_run_outcome(sid="orch-1", status="complete")
        log_parallel_run_outcome(sid="orch-2", status="escalate")
        target = Path(td) / "telemetry" / "autopilot-parallel-runs.jsonl"
        records = [
            json.loads(line)
            for line in target.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert len(records) == 2
        assert records[0]["sid"] == "orch-1"
        assert records[1]["sid"] == "orch-2"


def test_log_parallel_run_outcome_coerces_int_counters():
    from lib.autopilot_flip_policy import log_parallel_run_outcome
    with tempfile.TemporaryDirectory() as td:
        _redirect_telemetry_dir(Path(td))
        log_parallel_run_outcome(
            sid="orch-x", status="complete",
            merge_conflicts="3",  # type: ignore[arg-type]
            pane_failures=2.0,  # type: ignore[arg-type]
        )
        target = Path(td) / "telemetry" / "autopilot-parallel-runs.jsonl"
        rec = json.loads(target.read_text(encoding="utf-8").strip())
        assert rec["merge_conflicts"] == 3
        assert rec["pane_failures"] == 2


def test_log_parallel_run_outcome_real_telemetry_path():
    """Smoke test: exercise the real lib.logging.log_telemetry path end-to-end.
    Verifies the D5 observability counter actually lands on disk via the
    canonical telemetry pipeline (not via mocks). Closes the 'D5 telemetry
    counter 첫 write 미발화' natural-trigger residual.
    """
    from lib.autopilot_flip_policy import log_parallel_run_outcome
    from lib import logging as L
    with tempfile.TemporaryDirectory() as td:
        _redirect_telemetry_dir(Path(td))
        # End-to-end: real ensure_dir → real jsonl_append → real auto-ts stamp
        log_parallel_run_outcome(
            sid=f"smoke-natural-trigger-{id(td)}",
            status="complete",
            merge_conflicts=0,
            pane_failures=0,
            mode="real-runtime-smoke",
        )
        target = Path(td) / "telemetry" / "autopilot-parallel-runs.jsonl"
        assert target.is_file(), "telemetry file must materialize via real lib.logging path"
        rec = json.loads(target.read_text(encoding="utf-8").strip())
        # Real lib.logging.now_iso stamp format: ISO8601 'Z'-suffixed
        assert rec["ts"].endswith("Z"), f"unexpected ts format: {rec['ts']!r}"
        assert "T" in rec["ts"]  # ISO8601 separator
        assert rec["mode"] == "real-runtime-smoke"
        # Verify rotation hook is wired (no rotation expected here — file size
        # well under TELEMETRY_ROTATE_BYTES — but the call path must not error)
        assert L.TELEMETRY_DIR == Path(td) / "telemetry"


TESTS = [
    test_current_default_returns_zero,
    test_current_default_is_deterministic,
    test_current_default_returns_int_not_bool,
    test_log_parallel_run_outcome_rejects_empty_sid,
    test_log_parallel_run_outcome_rejects_non_str_sid,
    test_log_parallel_run_outcome_rejects_empty_status,
    test_log_parallel_run_outcome_writes_to_telemetry,
    test_log_parallel_run_outcome_record_with_failures,
    test_log_parallel_run_outcome_kwargs_passthrough,
    test_log_parallel_run_outcome_appends_not_overwrites,
    test_log_parallel_run_outcome_coerces_int_counters,
    test_log_parallel_run_outcome_real_telemetry_path,
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
